"""
Sensor registry — loads sensors.yaml and manages driver lifecycle.

Usage::

    registry = SensorRegistry.from_yaml()   # reads SEZ_SENSORS_PATH or ./sensors.yaml
    registry.start_polling()                # launches asyncio background poller

    reading = registry.latest("env_lab499_west")   # ZoneSnapshot or None
    registry.close()                               # stop + release hardware

File resolution order for ``from_yaml()``::

    1. ``sensors_path`` argument
    2. ``SEZ_SENSORS_PATH`` env var
    3. ``./sensors.yaml`` (cwd)
    4. ``~/.sense_every_zone/sensors.yaml``

The registry is a thin coordinator: it owns the driver objects, runs
the polling loop, and stores the latest ``ZoneSnapshot`` in a dict
keyed by zone_id.  The FastAPI server calls ``latest()`` on every
``GET /zones/{zone_id}/status`` request.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .drivers.base import BaseSensor, RawReading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Driver registry — maps yaml ``driver:`` value to class
# ---------------------------------------------------------------------------

def _driver_map() -> dict:
    """Lazily import driver classes to avoid hard deps at import time."""
    from .drivers.mock import MockSensor
    drivers = {"mock": MockSensor}
    try:
        from .drivers.sen55 import SEN55Sensor
        drivers["sen55"] = SEN55Sensor
    except ImportError:
        pass
    try:
        from .drivers.alphasense_co_b4 import AlphaCOB4Sensor
        drivers["alphasense_co_b4"] = AlphaCOB4Sensor
    except ImportError:
        pass
    try:
        from .drivers.alphasense_ox import AlphaOXSensor
        drivers["alphasense_ox"] = AlphaOXSensor
    except ImportError:
        pass
    try:
        from .drivers.pisugar import PiSugar3Sensor
        drivers["pisugar"] = PiSugar3Sensor
    except ImportError:
        pass
    return drivers


# ---------------------------------------------------------------------------
# Zone snapshot — latest aggregated state for one zone
# ---------------------------------------------------------------------------

@dataclass
class ZoneSnapshot:
    zone_id: str
    display_name: str
    polled_at: float = field(default_factory=time.time)
    readings: List[RawReading] = field(default_factory=list)
    healthy_count: int = 0
    total_count: int = 0

    @property
    def all_healthy(self) -> bool:
        return self.total_count > 0 and self.healthy_count == self.total_count

    @property
    def any_healthy(self) -> bool:
        return self.healthy_count > 0

    @property
    def active_alerts(self) -> List[str]:
        alerts = []
        for r in self.readings:
            alerts.extend(r.alerts)
        return alerts


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class _ZoneConfig:
    zone_id: str
    display_name: str
    poll_interval_s: float
    sensors: List[BaseSensor]


class SensorRegistry:
    def __init__(self, zones: List[_ZoneConfig]) -> None:
        self._zones: Dict[str, _ZoneConfig] = {z.zone_id: z for z in zones}
        self._snapshots: Dict[str, ZoneSnapshot] = {
            z.zone_id: ZoneSnapshot(zone_id=z.zone_id, display_name=z.display_name)
            for z in zones
        }
        self._polling_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, sensors_path: Optional[Path] = None) -> "SensorRegistry":
        path = _resolve_sensors_path(sensors_path)
        logger.info("Loading sensor registry from %s", path)
        with open(path) as f:
            raw = yaml.safe_load(f)
        if raw is None or "zones" not in raw:
            raise ValueError(f"sensors.yaml at {path} has no 'zones' key")
        drivers = _driver_map()
        zones = []
        for zone_cfg in raw["zones"]:
            zone_id = zone_cfg["id"]
            display_name = zone_cfg.get("display_name", zone_id)
            poll_interval_s = float(zone_cfg.get("poll_interval_s", 5))
            sensor_objs: List[BaseSensor] = []
            for scfg in zone_cfg.get("sensors", []):
                driver_name = scfg.get("driver", "mock")
                driver_cls = drivers.get(driver_name)
                if driver_cls is None:
                    logger.warning(
                        "Zone %r: unknown driver %r — skipping sensor %r",
                        zone_id, driver_name, scfg.get("id"),
                    )
                    continue
                try:
                    sensor = driver_cls(
                        sensor_id=scfg["id"],
                        zone_id=zone_id,
                        config=scfg,
                    )
                    sensor_objs.append(sensor)
                    logger.info("Zone %r: registered %r (%s)", zone_id, scfg["id"], driver_name)
                except Exception as exc:
                    logger.error(
                        "Zone %r: failed to create sensor %r: %s",
                        zone_id, scfg.get("id"), exc,
                    )
            zones.append(_ZoneConfig(
                zone_id=zone_id,
                display_name=display_name,
                poll_interval_s=poll_interval_s,
                sensors=sensor_objs,
            ))
        logger.info("Registry loaded: %d zone(s)", len(zones))
        return cls(zones)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def zone_ids(self) -> List[str]:
        return list(self._zones.keys())

    def latest(self, zone_id: str) -> Optional[ZoneSnapshot]:
        return self._snapshots.get(zone_id)

    def start_polling(self) -> None:
        """Start the background asyncio polling loop."""
        if self._polling_task is not None:
            return
        self._polling_task = asyncio.create_task(self._poll_loop())
        logger.info("Polling loop started for %d zone(s)", len(self._zones))

    def stop_polling(self) -> None:
        if self._polling_task is not None:
            self._polling_task.cancel()
            self._polling_task = None

    def close(self) -> None:
        """Stop polling and release all hardware resources."""
        self.stop_polling()
        for zone in self._zones.values():
            for sensor in zone.sensors:
                try:
                    sensor.close()
                except Exception as exc:
                    logger.warning("Error closing sensor %r: %s", sensor.sensor_id, exc)

    # ------------------------------------------------------------------
    # Internal polling loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Round-robin poll each zone on its own interval."""
        next_poll: Dict[str, float] = {zid: 0.0 for zid in self._zones}
        while True:
            now = time.monotonic()
            for zone_id, zone in self._zones.items():
                if now >= next_poll[zone_id]:
                    await self._poll_zone(zone)
                    next_poll[zone_id] = time.monotonic() + zone.poll_interval_s
            await asyncio.sleep(0.1)

    async def _poll_zone(self, zone: _ZoneConfig) -> None:
        readings: List[RawReading] = []
        healthy = 0
        for sensor in zone.sensors:
            try:
                reading = await asyncio.get_event_loop().run_in_executor(
                    None, sensor.read
                )
                readings.append(reading)
                healthy += 1
            except Exception as exc:
                logger.warning(
                    "Zone %r sensor %r read error: %s",
                    zone.zone_id, sensor.sensor_id, exc,
                )
        self._snapshots[zone.zone_id] = ZoneSnapshot(
            zone_id=zone.zone_id,
            display_name=zone.display_name,
            polled_at=time.time(),
            readings=readings,
            healthy_count=healthy,
            total_count=len(zone.sensors),
        )


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_sensors_path(override: Optional[Path]) -> Path:
    if override is not None:
        return Path(override)
    if env := os.environ.get("SEZ_SENSORS_PATH"):
        return Path(env)
    for candidate in (
        Path("sensors.yaml"),
        Path.home() / ".sense_every_zone" / "sensors.yaml",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "sensors.yaml not found. Set SEZ_SENSORS_PATH or place sensors.yaml "
        "in the working directory."
    )

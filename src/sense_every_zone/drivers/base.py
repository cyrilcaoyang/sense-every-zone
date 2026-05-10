"""
Abstract base driver interface for all sense_every_zone sensor drivers.

Every concrete driver must:
  1. Accept ``(sensor_id, zone_id, config)`` in ``__init__``.
  2. Implement ``read() -> RawReading``.
  3. Implement ``healthy() -> bool`` (non-raising).
  4. Implement ``close()`` (idempotent, non-raising).

``RawReading`` is a plain dataclass — it travels from the driver up to
the registry poller, which converts it to a Pydantic ``SensorReading``
for the API layer.  Keeping the dataclass free of Pydantic lets drivers
run without importing the API stack (useful in test scripts and hardware
bringup).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RawReading:
    """Flat sensor reading from one physical sensor."""
    sensor_id: str
    zone_id: str
    timestamp: float = field(default_factory=time.time)

    # T / RH (SHT45, SEN55)
    temperature_c: Optional[float] = None
    humidity_rh: Optional[float] = None

    # Air quality (SGP40, SEN55)
    voc_index: Optional[int] = None    # Sensirion 1–500
    nox_index: Optional[int] = None    # Sensirion 1–500

    # Particulate matter (SEN55)
    pm1_ug_m3: Optional[float] = None
    pm25_ug_m3: Optional[float] = None
    pm4_ug_m3: Optional[float] = None
    pm10_ug_m3: Optional[float] = None

    # Safety gases (Alphasense)
    co_ppm: Optional[float] = None
    o2_percent: Optional[float] = None
    h2_ppm: Optional[float] = None

    # UPS / battery (PiSugar 3)
    battery_pct: Optional[int] = None
    battery_charging: Optional[bool] = None
    battery_power_plugged: Optional[bool] = None
    battery_voltage_v: Optional[float] = None

    # Threshold breaches populated by the driver if alert_thresholds are set
    alerts: List[str] = field(default_factory=list)


class BaseSensor(ABC):
    """Abstract sensor driver."""

    def __init__(self, sensor_id: str, zone_id: str, config: dict) -> None:
        self.sensor_id = sensor_id
        self.zone_id = zone_id
        self.config = config

    @abstractmethod
    def read(self) -> RawReading:
        """Return the latest reading.  May raise on hardware error."""
        ...

    @abstractmethod
    def healthy(self) -> bool:
        """Return True if the sensor is reachable.  Must not raise."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Release hardware resources.  Must be idempotent and non-raising."""
        ...

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    def _blank(self) -> RawReading:
        """Return an empty reading stamped with current time."""
        return RawReading(sensor_id=self.sensor_id, zone_id=self.zone_id)

    def _check_threshold(
        self,
        reading: RawReading,
        field_name: str,
        label: str,
        high: Optional[float] = None,
        low: Optional[float] = None,
    ) -> None:
        """Append an alert string to reading.alerts if a threshold is crossed."""
        value = getattr(reading, field_name, None)
        if value is None:
            return
        if high is not None and value > high:
            reading.alerts.append(f"{label}_HIGH:{value:.2f}")
        if low is not None and value < low:
            reading.alerts.append(f"{label}_LOW:{value:.2f}")

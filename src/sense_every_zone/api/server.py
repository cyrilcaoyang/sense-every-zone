"""
sense_every_zone FastAPI server — STATUS_SPEC v1.0.

Endpoints
---------
GET  /                              ProbeResponse
GET  /health                        HealthResponse
GET  /zones                         list[ZoneSummary]
GET  /zones/{zone_id}/status        EquipmentStatus  (polled by aggregator)

Each zone has its own STATUS_SPEC v1.0 envelope accessible at
``/zones/{zone_id}/status``.  This matches the equipment.yaml pattern:

    - id: env_lab499_west
      base_url: http://pi-fumehood:8030
      status_path: /zones/env_lab499_west/status

Run
---
    uvicorn sense_every_zone.api.server:app --host 0.0.0.0 --port 8030 \\
        --reload --reload-include "*.yaml"

Or via env vars:
    SEZ_SENSORS_PATH=/etc/sez/sensors.yaml uvicorn ...
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from .logging_config import configure as _configure_logging
from .models import (
    BatteryStatus,
    ComponentStatus,
    DependencyHealth,
    EquipmentStatus,
    ErrorInfo,
    HealthResponse,
    MetricValue,
    ProbeResponse,
    SensorReading,
    SenzZoneDetails,
    ZoneSummary,
)
from ..registry import SensorRegistry, ZoneSnapshot

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: SensorRegistry | None = None


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _registry
    _configure_logging()
    try:
        _registry = SensorRegistry.from_yaml()
        _registry.start_polling()
        logger.info(
            "sense_every_zone started — serving %d zone(s): %s",
            len(_registry.zone_ids()),
            ", ".join(_registry.zone_ids()),
        )
    except FileNotFoundError as exc:
        logger.error("Cannot start: %s", exc)
        # Start without a registry — /health will report unhealthy
        _registry = None
    yield
    logger.info("sense_every_zone shutting down")
    if _registry is not None:
        _registry.close()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Sense Every Zone",
    description="Environmental sensor nodes — STATUS_SPEC v1.0",
    version="1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def _log_requests(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    path = request.url.path
    msg = "%s %s → %d (%.0f ms)", request.method, path, response.status_code, elapsed_ms
    if "/status" in path and response.status_code == 200:
        logger.debug(*msg)
    else:
        logger.info(*msg)
    return response


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RuntimeError)
async def _runtime_error(request: Request, exc: RuntimeError):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc)},
    )


# ---------------------------------------------------------------------------
# Read-only endpoints
# ---------------------------------------------------------------------------

@app.get("/", response_model=ProbeResponse)
async def probe():
    """Minimal identity probe — always 200."""
    return ProbeResponse()


@app.get("/health", response_model=HealthResponse)
async def health():
    """Service liveness. ``ok`` reflects whether sensors are reachable."""
    deps: list[DependencyHealth] = []
    ok = True

    if _registry is None:
        ok = False
        deps.append(DependencyHealth(
            name="registry", ok=False,
            message="sensors.yaml not loaded — check SEZ_SENSORS_PATH",
        ))
    else:
        for zone_id in _registry.zone_ids():
            snap = _registry.latest(zone_id)
            if snap is None or snap.total_count == 0:
                deps.append(DependencyHealth(name=zone_id, ok=False, message="no readings yet"))
            elif not snap.any_healthy:
                ok = False
                deps.append(DependencyHealth(
                    name=zone_id, ok=False,
                    message=f"0/{snap.total_count} sensors healthy",
                ))
            else:
                deps.append(DependencyHealth(
                    name=zone_id, ok=True,
                    message=f"{snap.healthy_count}/{snap.total_count} sensors healthy",
                ))

    return HealthResponse(ok=ok, dependencies=deps)


@app.get("/zones", response_model=List[ZoneSummary])
async def list_zones():
    """List all zones served by this process."""
    if _registry is None:
        return []
    summaries = []
    for zone_id in _registry.zone_ids():
        snap = _registry.latest(zone_id)
        if snap is None:
            state = "unknown"
            alert_count = 0
        elif not snap.any_healthy:
            state = "error"
            alert_count = 0
        elif not snap.all_healthy:
            state = "degraded"
            alert_count = len(snap.active_alerts)
        else:
            state = "ready" if not snap.active_alerts else "degraded"
            alert_count = len(snap.active_alerts)
        summaries.append(ZoneSummary(
            zone_id=zone_id,
            display_name=snap.display_name if snap else zone_id,
            state=state,
            sensor_count=snap.total_count if snap else 0,
            active_alert_count=alert_count,
        ))
    return summaries


@app.get("/zones/{zone_id}/status", response_model=EquipmentStatus)
async def zone_status(zone_id: str):
    """Full STATUS_SPEC v1.0 envelope for one zone — polled by aggregator."""
    if _registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Registry not initialised",
        )
    snap = _registry.latest(zone_id)
    if snap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Zone {zone_id!r} not found",
        )
    return _build_status(snap)


# ---------------------------------------------------------------------------
# Status builder
# ---------------------------------------------------------------------------

def _build_status(snap: ZoneSnapshot) -> EquipmentStatus:
    # --- state ---
    if snap.total_count == 0 or (snap.polled_at == 0):
        state = "unknown"
    elif not snap.any_healthy:
        state = "error"
    elif not snap.all_healthy:
        state = "degraded"
    elif snap.active_alerts:
        state = "degraded"
    else:
        state = "ready"

    # --- components (one per sensor) ---
    components: dict[str, ComponentStatus] = {}
    for reading in snap.readings:
        components[reading.sensor_id] = ComponentStatus(
            connected=True,
            state="ready",
            last_event_at=datetime.fromtimestamp(reading.timestamp, tz=timezone.utc),
        )
    # Mark sensors that failed to read as disconnected
    # (they won't appear in snap.readings, so we note them via total_count)
    # Healthy count mismatch is already captured by state above.

    # --- metrics (flat STATUS_SPEC shape) ---
    metrics: dict[str, MetricValue] = {}
    ts = datetime.fromtimestamp(snap.polled_at, tz=timezone.utc)
    for r in snap.readings:
        if r.temperature_c is not None:
            metrics["temperature_c"] = MetricValue(value=r.temperature_c, unit="°C", timestamp=ts)
        if r.humidity_rh is not None:
            metrics["humidity_rh"] = MetricValue(value=r.humidity_rh, unit="%RH", timestamp=ts)
        if r.voc_index is not None:
            metrics["voc_index"] = MetricValue(value=r.voc_index, unit="index", timestamp=ts)
        if r.nox_index is not None:
            metrics["nox_index"] = MetricValue(value=r.nox_index, unit="index", timestamp=ts)
        if r.pm25_ug_m3 is not None:
            metrics["pm25_ug_m3"] = MetricValue(value=r.pm25_ug_m3, unit="µg/m³", timestamp=ts)
        if r.co_ppm is not None:
            metrics["co_ppm"] = MetricValue(value=r.co_ppm, unit="ppm", timestamp=ts)
        if r.o2_percent is not None:
            metrics["o2_percent"] = MetricValue(value=r.o2_percent, unit="%", timestamp=ts)
        if r.battery_pct is not None:
            metrics["battery_pct"] = MetricValue(value=r.battery_pct, unit="%", timestamp=ts)
        if r.battery_voltage_v is not None:
            metrics["battery_voltage_v"] = MetricValue(value=r.battery_voltage_v, unit="V", timestamp=ts)

    # --- errors / alerts ---
    errors: list[ErrorInfo] = []
    for alert in snap.active_alerts:
        # "CO_HIGH:34.20" → severity based on prefix
        code = alert.split(":")[0]
        is_critical = code in ("CO_HIGH", "O2_LOW", "H2_HIGH")
        is_warning = code in ("BATTERY_LOW",)
        errors.append(ErrorInfo(
            code=code,
            message=alert,
            severity="critical" if is_critical else ("warning" if is_warning else "error"),
        ))
    if state == "error":
        errors.append(ErrorInfo(
            code="SENSOR_FAILURE",
            message=f"0/{snap.total_count} sensors returning readings",
            severity="error",
        ))

    # --- battery (extracted from pisugar reading, if present) ---
    battery: BatteryStatus | None = None
    for r in snap.readings:
        if r.battery_pct is not None:
            battery = BatteryStatus(
                charge_pct=r.battery_pct,
                charging=bool(r.battery_charging),
                power_plugged=bool(r.battery_power_plugged),
                voltage_v=r.battery_voltage_v,
            )
            break  # only one pisugar per zone

    # --- details (structured per-sensor readings) ---
    sensor_readings = [
        SensorReading(
            sensor_id=r.sensor_id,
            timestamp=datetime.fromtimestamp(r.timestamp, tz=timezone.utc),
            temperature_c=r.temperature_c,
            humidity_rh=r.humidity_rh,
            voc_index=r.voc_index,
            nox_index=r.nox_index,
            pm1_ug_m3=r.pm1_ug_m3,
            pm25_ug_m3=r.pm25_ug_m3,
            pm4_ug_m3=r.pm4_ug_m3,
            pm10_ug_m3=r.pm10_ug_m3,
            co_ppm=r.co_ppm,
            o2_percent=r.o2_percent,
            h2_ppm=r.h2_ppm,
        )
        for r in snap.readings
        if r.battery_pct is None   # exclude pisugar reading from sensor_readings list
    ]
    details = SenzZoneDetails(
        zone_id=snap.zone_id,
        display_name=snap.display_name,
        sensor_readings=sensor_readings,
        active_alerts=snap.active_alerts,
        battery=battery,
    )

    return EquipmentStatus(
        equipment_id=snap.zone_id,
        equipment_name=snap.display_name,
        state=state,
        timestamp=ts,
        components=components,
        metrics=metrics,
        errors=errors,
        details=details,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import uvicorn

    uvicorn.run(
        "sense_every_zone.api.server:app",
        host=os.environ.get("SEZ_HOST", "0.0.0.0"),
        port=int(os.environ.get("SEZ_PORT", "8030")),
        log_level="info",
        reload=True,
        reload_includes=["*.yaml"],
    )

"""
STATUS_SPEC v1.0 Pydantic models for sense_every_zone.

Each zone served by this process gets its own EquipmentStatus envelope,
polled by the aggregator via GET /zones/{zone_id}/status.

The ``details`` block (SenzZoneDetails) carries structured per-sensor
readings. The standard ``metrics`` dict carries the same values in the
flat STATUS_SPEC shape so the dashboard can render them without knowing
the sensor kind.

Shape compatibility: identical to dose_every_well models.py except the
details payload and the narrower EquipmentState literal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

PROTOCOL_VERSION = "1.0"
EQUIPMENT_KIND = "environmental_sensor"


# ---------------------------------------------------------------------------
# Core spec types (v1.0)
# ---------------------------------------------------------------------------

EquipmentState = Literal[
    "ready",
    "degraded",   # some sensors healthy, some failing
    "error",      # all sensors failing or hardware fault
    "unknown",    # not yet polled
]


class ComponentStatus(BaseModel):
    connected: bool
    state: str
    message: Optional[str] = None
    last_event_at: Optional[datetime] = None


class MetricValue(BaseModel):
    value: float | int | str | bool
    unit: Optional[str] = None
    timestamp: Optional[datetime] = None


class ErrorInfo(BaseModel):
    code: Optional[str] = None
    message: str
    severity: Literal["info", "warning", "error", "critical"]


# ---------------------------------------------------------------------------
# sense_every_zone–specific details block
# ---------------------------------------------------------------------------

class SensorReading(BaseModel):
    """Structured reading from one physical sensor in a zone."""
    sensor_id: str
    timestamp: datetime
    temperature_c: Optional[float] = None
    humidity_rh: Optional[float] = None
    voc_index: Optional[int] = None       # Sensirion 1–500 scale
    nox_index: Optional[int] = None       # Sensirion 1–500 scale
    pm1_ug_m3: Optional[float] = None
    pm25_ug_m3: Optional[float] = None
    pm4_ug_m3: Optional[float] = None
    pm10_ug_m3: Optional[float] = None
    co_ppm: Optional[float] = None
    o2_percent: Optional[float] = None
    h2_ppm: Optional[float] = None


class BatteryStatus(BaseModel):
    """UPS battery state from PiSugar 3."""
    charge_pct: int                          # 0–100
    charging: bool
    power_plugged: bool
    voltage_v: Optional[float] = None


class SenzZoneDetails(BaseModel):
    """``EquipmentStatus.details`` payload for one zone."""
    zone_id: str
    display_name: str
    sensor_readings: List[SensorReading] = Field(default_factory=list)
    # Threshold breaches that were active at the last poll
    active_alerts: List[str] = Field(default_factory=list)
    # UPS battery — present when a pisugar driver is configured for this zone
    battery: Optional[BatteryStatus] = None


# ---------------------------------------------------------------------------
# Full EquipmentStatus envelope
# ---------------------------------------------------------------------------

class EquipmentStatus(BaseModel):
    """Full STATUS_SPEC v1.0 envelope polled by the aggregator every ~5 s."""

    # Identity — set per zone in server.py
    equipment_id: str
    equipment_name: str
    kind: str = EQUIPMENT_KIND
    protocol_version: str = PROTOCOL_VERSION

    # State
    state: EquipmentState
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Standard STATUS_SPEC v1.0 fields
    components: Dict[str, ComponentStatus] = Field(default_factory=dict)
    metrics: Dict[str, MetricValue] = Field(default_factory=dict)
    errors: List[ErrorInfo] = Field(default_factory=list)
    required_actions: List[str] = Field(default_factory=list)

    # sense_every_zone details payload
    details: Optional[SenzZoneDetails] = None


# ---------------------------------------------------------------------------
# Probe + Health responses
# ---------------------------------------------------------------------------

class ProbeResponse(BaseModel):
    """Returned by ``GET /``. Minimal machine-readable identity."""
    service: str = "sense_every_zone"
    protocol_version: str = PROTOCOL_VERSION
    kind: str = EQUIPMENT_KIND


class DependencyHealth(BaseModel):
    name: str
    ok: bool
    message: Optional[str] = None


class HealthResponse(BaseModel):
    """Returned by ``GET /health``."""
    ok: bool
    dependencies: List[DependencyHealth] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ZoneSummary(BaseModel):
    """One entry in ``GET /zones`` listing."""
    zone_id: str
    display_name: str
    state: EquipmentState
    sensor_count: int
    active_alert_count: int

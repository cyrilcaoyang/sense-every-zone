"""
STATUS_SPEC v1.2 Pydantic models for sense_every_zone.

The wire-contract types (``ComponentStatus``, ``MetricValue``, ``ErrorInfo``,
``EquipmentStatus``, ``ProbeResponse``, ``HealthResponse`` …) are imported from
the shared ``sdl-lab-contract`` package and re-exported here so every
``from .models import ...`` in this repo keeps working unchanged. This mirrors
the pattern in ``agilent_plateloc/src/agilent_plateloc_server/models.py``.

Conformance: the sense_every_zone REST API conforms to **STATUS_SPEC v1.2**
(``activity`` / ``activity_since`` for passive environmental monitors,
``details`` as a free-form dict carrying the structured ``SenzZoneDetails``
payload, ``last_error`` as a single most-severe error). ``PROTOCOL_VERSION``
below is the version THIS device speaks and deliberately overrides the
package's parse-time default ("1.0" — the honest reading of a device that does
not state a version).

Kept local: ``SensorReading``, ``BatteryStatus``, ``SenzZoneDetails`` (the
sense-every-zone–specific detail payload that goes into ``details`` as a dict),
``ZoneSummary`` and ``DependencyHealth`` (not part of the wire contract), and
the richer ``ZoneHealthResponse`` used for ``GET /health`` (the spec
``HealthResponse`` is a minimal liveness check; the local one is richer and
includes ``status: "healthy"`` semantics via ``ok: bool``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field

from sdl_lab_contract import (
    Activity,
    ClaimedBy,
    ClaimRejection,
    ClaimRequest,
    ClaimResponse,
    ComponentStatus,
    EquipmentKind,
    EquipmentState,
    EquipmentStatus,
    ErrorInfo,
    ErrorSeverity,
    HealthResponse as SpecHealthResponse,
    MetricValue,
    ProbeResponse,
)

PROTOCOL_VERSION = "1.2"
EQUIPMENT_KIND = "environmental_sensor"


# ---------------------------------------------------------------------------
# sense_every_zone–specific detail block (goes into EquipmentStatus.details dict)
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
    """Structured payload for one zone, embedded into ``details`` as a dict."""
    zone_id: str
    display_name: str
    sensor_readings: List[SensorReading] = Field(default_factory=list)
    # Threshold breaches that were active at the last poll
    active_alerts: List[str] = Field(default_factory=list)
    # UPS battery — present when a pisugar driver is configured for this zone
    battery: Optional[BatteryStatus] = None
    # Full errors list (backwards-compat) — the v1.2 envelope only carries
    # ``last_error`` (single most-severe), so the complete list is preserved
    # here for clients that want the full picture.
    errors: List[ErrorInfo] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Local (non-wire-contract) models
# ---------------------------------------------------------------------------

class DependencyHealth(BaseModel):
    name: str
    ok: bool
    message: Optional[str] = None


class ZoneHealthResponse(BaseModel):
    """Richer ``GET /health`` body — local, not the spec ``HealthResponse``.

    The spec ``HealthResponse`` is a minimal liveness check (just
    ``status: "healthy"``); this richer model includes per-zone dependency
    health. A response with ``ok: True`` plus extra fields is still
    spec-conformant (the spec requires ``status: "healthy"``; richer info is
    allowed).
    """
    ok: bool
    dependencies: List[DependencyHealth] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# Keep the name ``HealthResponse`` pointing at the richer local model so
# existing ``from .models import HealthResponse`` imports keep working. The
# spec-conformant minimal type is available as ``SpecHealthResponse`` for
# callers that want exactly the wire shape.
HealthResponse = ZoneHealthResponse


class ZoneSummary(BaseModel):
    """One entry in ``GET /zones`` listing."""
    zone_id: str
    display_name: str
    state: EquipmentState
    sensor_count: int
    active_alert_count: int


__all__ = [
    # Re-exported from sdl_lab_contract
    "Activity",
    "ClaimedBy",
    "ClaimRejection",
    "ClaimRequest",
    "ClaimResponse",
    "ComponentStatus",
    "EquipmentKind",
    "EquipmentState",
    "EquipmentStatus",
    "ErrorInfo",
    "ErrorSeverity",
    "MetricValue",
    "ProbeResponse",
    "SpecHealthResponse",
    # Local constants
    "PROTOCOL_VERSION",
    "EQUIPMENT_KIND",
    # Local detail / zone models
    "SensorReading",
    "BatteryStatus",
    "SenzZoneDetails",
    "DependencyHealth",
    "HealthResponse",
    "ZoneHealthResponse",
    "ZoneSummary",
]

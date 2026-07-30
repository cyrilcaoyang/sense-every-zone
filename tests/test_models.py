"""Tests for STATUS_SPEC v1.2 Pydantic models (sourced from sdl-lab-contract)."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from sense_every_zone.api.models import (
    ComponentStatus,
    EquipmentStatus,
    ErrorInfo,
    HealthResponse,
    MetricValue,
    ProbeResponse,
    SensorReading,
    SenzZoneDetails,
    ZoneSummary,
    PROTOCOL_VERSION,
    EQUIPMENT_KIND,
)


def test_probe_response_requires_identity():
    """v1.2 ProbeResponse requires equipment_id and equipment_name."""
    r = ProbeResponse(
        equipment_id="sense_every_zone",
        equipment_name="Sense Every Zone",
        protocol_version=PROTOCOL_VERSION,
    )
    assert r.protocol_version == PROTOCOL_VERSION
    assert r.equipment_id == "sense_every_zone"


def test_probe_response_defaults_protocol_version():
    """ProbeResponse without explicit protocol_version defaults to '1.0' (contract default)."""
    r = ProbeResponse(equipment_id="x", equipment_name="Y")
    assert r.protocol_version == "1.0"


def test_equipment_status_valid_states():
    for state in ("ready", "degraded", "error", "unknown"):
        s = EquipmentStatus(
            equipment_id="env_test",
            equipment_name="Test",
            equipment_kind=EQUIPMENT_KIND,
            equipment_status=state,
            device_time=datetime.now(timezone.utc),
        )
        assert s.equipment_status == state


def test_equipment_status_invalid_state():
    with pytest.raises(ValidationError):
        EquipmentStatus(
            equipment_id="env_test",
            equipment_name="Test",
            equipment_kind=EQUIPMENT_KIND,
            equipment_status="flying",
            device_time=datetime.now(timezone.utc),
        )


def test_equipment_status_metrics_populated():
    ts = datetime.now(timezone.utc)
    s = EquipmentStatus(
        equipment_id="env_test",
        equipment_name="Test Zone",
        equipment_kind=EQUIPMENT_KIND,
        equipment_status="ready",
        device_time=ts,
        metrics={
            "temperature_c": MetricValue(value=22.4, unit="°C", timestamp=ts),
            "co_ppm": MetricValue(value=3.1, unit="ppm", timestamp=ts),
        },
    )
    assert s.metrics["temperature_c"].value == 22.4
    assert s.metrics["co_ppm"].unit == "ppm"


def test_equipment_status_details_is_dict():
    """v1.2 details is dict[str, Any], not a typed model."""
    ts = datetime.now(timezone.utc)
    s = EquipmentStatus(
        equipment_id="env_test",
        equipment_name="Test Zone",
        equipment_kind=EQUIPMENT_KIND,
        equipment_status="ready",
        device_time=ts,
        details={"zone": {"zone_id": "env_test"}},
    )
    assert isinstance(s.details, dict)
    assert s.details["zone"]["zone_id"] == "env_test"


def test_equipment_status_last_error_single():
    """v1.2 replaces errors: List[ErrorInfo] with last_error: ErrorInfo | None."""
    ts = datetime.now(timezone.utc)
    err = ErrorInfo(message="test", severity="critical", timestamp=ts)
    s = EquipmentStatus(
        equipment_id="env_test",
        equipment_name="Test",
        equipment_kind=EQUIPMENT_KIND,
        equipment_status="error",
        device_time=ts,
        last_error=err,
    )
    assert s.last_error is not None
    assert s.last_error.message == "test"
    # default is None
    s2 = EquipmentStatus(
        equipment_id="env_test",
        equipment_name="Test",
        equipment_kind=EQUIPMENT_KIND,
        equipment_status="ready",
        device_time=ts,
    )
    assert s2.last_error is None


def test_equipment_status_activity_defaults():
    """v1.2 activity defaults to 'unknown', activity_since to None."""
    s = EquipmentStatus(
        equipment_id="env_test",
        equipment_name="Test",
        equipment_kind=EQUIPMENT_KIND,
        equipment_status="ready",
        device_time=datetime.now(timezone.utc),
    )
    assert s.activity == "unknown"
    assert s.activity_since is None
    assert s.allowed_actions == []


def test_sensor_reading_nullable_fields():
    ts = datetime.now(timezone.utc)
    r = SensorReading(sensor_id="sen55_west", timestamp=ts, temperature_c=21.0)
    assert r.humidity_rh is None
    assert r.co_ppm is None


def test_senz_zone_details():
    ts = datetime.now(timezone.utc)
    details = SenzZoneDetails(
        zone_id="env_fumehood",
        display_name="Fume Hood",
        sensor_readings=[
            SensorReading(sensor_id="co_hood", timestamp=ts, co_ppm=28.5),
        ],
        active_alerts=["CO_HIGH:28.50"],
    )
    assert len(details.sensor_readings) == 1
    assert "CO_HIGH:28.50" in details.active_alerts


def test_error_info_severity_validation():
    ts = datetime.now(timezone.utc)
    e = ErrorInfo(message="test", severity="critical", timestamp=ts)
    assert e.severity == "critical"
    with pytest.raises(ValidationError):
        ErrorInfo(message="test", severity="catastrophic", timestamp=ts)


def test_error_info_requires_timestamp():
    """v1.2 ErrorInfo requires a timestamp field."""
    with pytest.raises(ValidationError):
        ErrorInfo(message="test", severity="critical")  # missing timestamp


def test_zone_summary():
    s = ZoneSummary(
        zone_id="env_lab499_west",
        display_name="Lab 499 (West)",
        state="ready",
        sensor_count=1,
        active_alert_count=0,
    )
    assert s.state == "ready"


def test_health_response_ok():
    """Local HealthResponse (ZoneHealthResponse) requires ok, has dependencies."""
    r = HealthResponse(ok=True)
    assert r.ok is True
    assert r.dependencies == []
    assert r.timestamp is not None

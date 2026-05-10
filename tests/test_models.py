"""Tests for STATUS_SPEC v1.0 Pydantic models."""

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


def test_probe_response_defaults():
    r = ProbeResponse()
    assert r.protocol_version == PROTOCOL_VERSION
    assert r.kind == EQUIPMENT_KIND


def test_equipment_status_valid_states():
    for state in ("ready", "degraded", "error", "unknown"):
        s = EquipmentStatus(equipment_id="env_test", equipment_name="Test", state=state)
        assert s.state == state


def test_equipment_status_invalid_state():
    with pytest.raises(ValidationError):
        EquipmentStatus(equipment_id="env_test", equipment_name="Test", state="flying")


def test_equipment_status_metrics_populated():
    ts = datetime.now(timezone.utc)
    s = EquipmentStatus(
        equipment_id="env_test",
        equipment_name="Test Zone",
        state="ready",
        metrics={
            "temperature_c": MetricValue(value=22.4, unit="°C", timestamp=ts),
            "co_ppm": MetricValue(value=3.1, unit="ppm", timestamp=ts),
        },
    )
    assert s.metrics["temperature_c"].value == 22.4
    assert s.metrics["co_ppm"].unit == "ppm"


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
    e = ErrorInfo(message="test", severity="critical")
    assert e.severity == "critical"
    with pytest.raises(ValidationError):
        ErrorInfo(message="test", severity="catastrophic")


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
    r = HealthResponse(ok=True)
    assert r.ok is True
    assert r.dependencies == []
    assert r.timestamp is not None

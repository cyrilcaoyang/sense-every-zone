"""Tests for the STATUS_SPEC envelope built by ``_build_status``.

The metric-key naming here is a **cross-repo contract**, not a local style
choice: ``ac-organic-lab``'s ``web/src/components/LabMap.tsx`` renders
``temperature`` / ``humidity`` / ``o2`` / ``voc``, and its
``api/app/main.py::_write_sensor_readings`` records a curated subset into the
``sensor_readings`` history table by the same names. Renaming a key here
silently blanks a dashboard tile and stops a history series, so these tests
pin the names deliberately.
"""

from __future__ import annotations

import time

from sense_every_zone.api.server import _METRIC_MAP, _build_status
from sense_every_zone.drivers.base import RawReading
from sense_every_zone.registry import ZoneSnapshot


def _full_reading(sensor_id: str = "sen55_test") -> RawReading:
    """A reading with every measurement channel populated."""
    return RawReading(
        sensor_id=sensor_id,
        zone_id="env_test",
        timestamp=time.time(),
        temperature_c=22.0,
        humidity_rh=57.0,
        voc_index=79,
        nox_index=1,
        pm1_ug_m3=4.0,
        pm25_ug_m3=4.2,
        pm4_ug_m3=4.2,
        pm10_ug_m3=4.2,
        co_ppm=3.1,
        o2_percent=20.9,
        h2_ppm=0.4,
    )


def _snapshot(*readings: RawReading) -> ZoneSnapshot:
    return ZoneSnapshot(
        zone_id="env_test",
        display_name="Test Zone",
        polled_at=time.time(),
        readings=list(readings),
        healthy_count=len(readings),
        total_count=len(readings),
    )


def test_metric_keys_carry_no_unit_suffix():
    """Best practice #5: the unit lives in ``MetricValue.unit``, not the key."""
    status = _build_status(_snapshot(_full_reading()))

    assert set(status.metrics) == {
        "temperature", "humidity", "voc", "nox",
        "pm1", "pm25", "pm4", "pm10",
        "co", "o2", "h2",
    }

    forbidden = ("_c", "_rh", "_index", "_ug_m3", "_ppm", "_percent", "_pct", "_v")
    offenders = [k for k in status.metrics if k.endswith(forbidden)]
    assert offenders == [], f"unit-suffixed metric keys: {offenders}"


def test_units_are_declared_on_the_metric_value():
    status = _build_status(_snapshot(_full_reading()))

    assert status.metrics["temperature"].unit == "°C"
    assert status.metrics["temperature"].value == 22.0
    assert status.metrics["humidity"].unit == "%RH"
    assert status.metrics["voc"].unit == "index"
    assert status.metrics["pm25"].unit == "µg/m³"
    assert status.metrics["o2"].unit == "%"


def test_labmap_keys_are_present():
    """The four keys the dashboard's floorplan markers read by name."""
    status = _build_status(_snapshot(_full_reading()))
    for key in ("temperature", "humidity", "o2", "voc"):
        assert key in status.metrics, f"LabMap.tsx reads {key!r}; it is missing"


def test_absent_channels_are_omitted_not_zeroed():
    """A sensor that measures only T/RH must not report a phantom 0 ppm CO."""
    reading = RawReading(
        sensor_id="sht45_test", zone_id="env_test", timestamp=time.time(),
        temperature_c=21.0, humidity_rh=44.0,
    )
    status = _build_status(_snapshot(reading))

    assert set(status.metrics) == {"temperature", "humidity"}
    assert "co" not in status.metrics


def test_battery_metrics_come_from_the_ups_reading():
    """Battery lives on its own reading (pisugar), so it merges in separately."""
    ups = RawReading(
        sensor_id="ups_test", zone_id="env_test", timestamp=time.time(),
        battery_pct=91, battery_charging=True,
        battery_power_plugged=True, battery_voltage_v=4.096,
    )
    status = _build_status(_snapshot(_full_reading(), ups))

    assert status.metrics["battery"].value == 91
    assert status.metrics["battery"].unit == "%"
    assert status.metrics["battery_voltage"].unit == "V"
    # Still an unsuffixed name even though the RawReading attr is *_v.
    assert "battery_voltage_v" not in status.metrics


def test_metric_map_has_no_duplicate_keys():
    keys = [key for _, key, _ in _METRIC_MAP]
    assert len(keys) == len(set(keys)), "duplicate metric key in _METRIC_MAP"


def test_healthy_zone_is_ready_and_idle():
    """§2.3 consistency invariant: ``ready`` ⇒ ``activity: idle``."""
    status = _build_status(_snapshot(_full_reading()))

    assert status.equipment_status == "ready"
    assert status.activity == "idle"
    assert status.activity_since is not None
    assert status.protocol_version == "1.2"
    # Monitoring-only device: nothing to allow (§9 read-only clause).
    assert status.allowed_actions == []

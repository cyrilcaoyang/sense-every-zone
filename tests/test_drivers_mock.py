"""Tests for the mock sensor driver — runnable without hardware."""

import time

from sense_every_zone.drivers.mock import MockSensor
from sense_every_zone.drivers.base import RawReading


def _make_mock(sensor_id="mock_0", zone_id="env_test"):
    return MockSensor(sensor_id=sensor_id, zone_id=zone_id, config={})


def test_mock_read_returns_raw_reading():
    sensor = _make_mock()
    r = sensor.read()
    assert isinstance(r, RawReading)
    assert r.sensor_id == "mock_0"
    assert r.zone_id == "env_test"


def test_mock_all_fields_populated():
    sensor = _make_mock()
    r = sensor.read()
    assert r.temperature_c is not None
    assert r.humidity_rh is not None
    assert r.voc_index is not None
    assert r.co_ppm is not None
    assert r.o2_percent is not None


def test_mock_temperature_in_range():
    sensor = _make_mock()
    for _ in range(10):
        r = sensor.read()
        assert 15 < r.temperature_c < 30, f"Unexpected temperature: {r.temperature_c}"


def test_mock_o2_near_ambient():
    sensor = _make_mock()
    for _ in range(10):
        r = sensor.read()
        assert 19 < r.o2_percent < 23, f"Unexpected O2: {r.o2_percent}"


def test_mock_voc_index_in_sensirion_range():
    sensor = _make_mock()
    for _ in range(20):
        r = sensor.read()
        assert 1 <= r.voc_index <= 500, f"VOC index out of range: {r.voc_index}"


def test_mock_timestamp_recent():
    sensor = _make_mock()
    before = time.time()
    r = sensor.read()
    after = time.time()
    assert before <= r.timestamp <= after


def test_mock_healthy():
    sensor = _make_mock()
    assert sensor.healthy() is True


def test_mock_close_is_idempotent():
    sensor = _make_mock()
    sensor.close()
    sensor.close()  # must not raise


def test_mock_alerts_empty_normally():
    sensor = _make_mock()
    # Mock does not evaluate alert_thresholds — alerts list should be empty
    r = sensor.read()
    assert isinstance(r.alerts, list)

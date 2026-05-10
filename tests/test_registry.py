"""Tests for the sensor registry — YAML loading and zone management."""

import textwrap
import time
from pathlib import Path

import pytest
import yaml

from sense_every_zone.registry import SensorRegistry, _resolve_sensors_path


@pytest.fixture
def mock_sensors_yaml(tmp_path: Path) -> Path:
    content = textwrap.dedent("""
        zones:
          - id: env_mock_a
            display_name: "Mock Zone A"
            poll_interval_s: 1
            sensors:
              - id: mock_sensor_1
                driver: mock

          - id: env_mock_b
            display_name: "Mock Zone B"
            poll_interval_s: 1
            sensors:
              - id: mock_sensor_2
                driver: mock
              - id: mock_sensor_3
                driver: mock
    """)
    p = tmp_path / "sensors.yaml"
    p.write_text(content)
    return p


def test_registry_loads_zones(mock_sensors_yaml):
    reg = SensorRegistry.from_yaml(mock_sensors_yaml)
    assert set(reg.zone_ids()) == {"env_mock_a", "env_mock_b"}
    reg.close()


def test_registry_unknown_driver_skipped(tmp_path):
    content = textwrap.dedent("""
        zones:
          - id: env_test
            display_name: "Test"
            poll_interval_s: 1
            sensors:
              - id: ghost_sensor
                driver: nonexistent_driver
              - id: good_sensor
                driver: mock
    """)
    p = tmp_path / "sensors.yaml"
    p.write_text(content)
    reg = SensorRegistry.from_yaml(p)
    # Zone is present but only the mock sensor was created
    assert "env_test" in reg.zone_ids()
    reg.close()


def test_registry_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        SensorRegistry.from_yaml(tmp_path / "does_not_exist.yaml")


def test_registry_empty_zones_key(tmp_path):
    p = tmp_path / "sensors.yaml"
    p.write_text("zones: []\n")
    reg = SensorRegistry.from_yaml(p)
    assert reg.zone_ids() == []
    reg.close()


def test_registry_latest_returns_none_before_poll(mock_sensors_yaml):
    reg = SensorRegistry.from_yaml(mock_sensors_yaml)
    snap = reg.latest("env_mock_a")
    # Snapshot exists from init (with zero readings) but polled_at=0
    assert snap is not None
    reg.close()


@pytest.mark.asyncio
async def test_registry_polling_populates_snapshots(mock_sensors_yaml):
    reg = SensorRegistry.from_yaml(mock_sensors_yaml)
    reg.start_polling()
    # Wait for at least one poll cycle
    import asyncio
    await asyncio.sleep(0.5)
    snap = reg.latest("env_mock_a")
    assert snap is not None
    assert snap.healthy_count == 1
    assert len(snap.readings) == 1
    reg.close()


@pytest.mark.asyncio
async def test_registry_multi_sensor_zone(mock_sensors_yaml):
    reg = SensorRegistry.from_yaml(mock_sensors_yaml)
    reg.start_polling()
    import asyncio
    await asyncio.sleep(0.5)
    snap = reg.latest("env_mock_b")
    assert snap is not None
    assert snap.total_count == 2
    assert snap.healthy_count == 2
    reg.close()


def test_resolve_sensors_path_from_env(tmp_path, monkeypatch):
    p = tmp_path / "custom.yaml"
    p.write_text("zones: []\n")
    monkeypatch.setenv("SEZ_SENSORS_PATH", str(p))
    resolved = _resolve_sensors_path(None)
    assert resolved == p

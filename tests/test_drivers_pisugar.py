"""
Tests for the PiSugar 3 driver.

Hardware tests run against a real pisugar-server daemon and are skipped
automatically on machines where the daemon is not reachable.  All other
tests verify the driver's contract without any hardware dependency.
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from sense_every_zone.drivers.pisugar import PiSugar3Sensor
from sense_every_zone.drivers.base import RawReading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sensor(port: int, low_threshold: int = 20) -> PiSugar3Sensor:
    return PiSugar3Sensor(
        sensor_id="pisugar_test",
        zone_id="env_test",
        config={
            "host": "localhost",
            "port": port,
            "timeout_s": 1.0,
            "alert_thresholds": {"battery_pct_low": low_threshold},
        },
    )


class _FakePiSugarServer:
    """Minimal TCP server that mimics pisugar-server responses."""

    def __init__(self, responses: dict[str, str], port: int = 0) -> None:
        self._responses = responses
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("localhost", port))
        self._sock.listen(5)
        self._sock.settimeout(2.0)
        self.port = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            while True:
                try:
                    conn, _ = self._sock.accept()
                except socket.timeout:
                    return
                with conn:
                    data = b""
                    conn.settimeout(1.0)
                    try:
                        while True:
                            chunk = conn.recv(256)
                            if not chunk:
                                break
                            data += chunk
                    except socket.timeout:
                        pass
                    reply = ""
                    for line in data.decode(errors="replace").splitlines():
                        cmd = line.strip()
                        if cmd.startswith("get "):
                            key = cmd[4:]
                            if key in self._responses:
                                reply += f"{key}: {self._responses[key]}\n"
                    conn.sendall(reply.encode())
        except OSError:
            pass

    def stop(self) -> None:
        self._sock.close()


# ---------------------------------------------------------------------------
# Tests using fake server
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_server():
    srv = _FakePiSugarServer({
        "battery": "85",
        "battery_charging": "true",
        "battery_power_plugged": "true",
        "battery_voltage": "3950",   # mV
    })
    yield srv
    srv.stop()


def test_pisugar_read_returns_raw_reading(fake_server):
    sensor = _make_sensor(fake_server.port)
    r = sensor.read()
    assert isinstance(r, RawReading)
    assert r.sensor_id == "pisugar_test"
    assert r.zone_id == "env_test"


def test_pisugar_battery_pct(fake_server):
    sensor = _make_sensor(fake_server.port)
    r = sensor.read()
    assert r.battery_pct == 85


def test_pisugar_charging_flag(fake_server):
    sensor = _make_sensor(fake_server.port)
    r = sensor.read()
    assert r.battery_charging is True


def test_pisugar_power_plugged(fake_server):
    sensor = _make_sensor(fake_server.port)
    r = sensor.read()
    assert r.battery_power_plugged is True


def test_pisugar_voltage_converted_from_mv(fake_server):
    sensor = _make_sensor(fake_server.port)
    r = sensor.read()
    # 3950 mV → 3.950 V
    assert r.battery_voltage_v == pytest.approx(3.950, abs=0.001)


def test_pisugar_no_alerts_above_threshold(fake_server):
    sensor = _make_sensor(fake_server.port, low_threshold=20)
    r = sensor.read()
    # 85% > 20% threshold → no alert
    assert r.alerts == []


def test_pisugar_alert_below_threshold():
    srv = _FakePiSugarServer({
        "battery": "15",
        "battery_charging": "false",
        "battery_power_plugged": "false",
        "battery_voltage": "3500",
    })
    sensor = _make_sensor(srv.port, low_threshold=20)
    r = sensor.read()
    srv.stop()
    assert any("BATTERY" in a for a in r.alerts), f"Expected BATTERY alert, got {r.alerts}"


def test_pisugar_healthy_when_server_running(fake_server):
    sensor = _make_sensor(fake_server.port)
    assert sensor.healthy() is True


def test_pisugar_unhealthy_when_no_server():
    # Port 1 is privileged and never has pisugar-server — always refused
    sensor = _make_sensor(19999)   # random high port, nothing listening
    assert sensor.healthy() is False


def test_pisugar_read_raises_when_no_server():
    sensor = _make_sensor(19998)
    with pytest.raises(Exception):
        sensor.read()


def test_pisugar_close_is_idempotent(fake_server):
    sensor = _make_sensor(fake_server.port)
    sensor.close()
    sensor.close()


def test_pisugar_timestamp_recent(fake_server):
    sensor = _make_sensor(fake_server.port)
    before = time.time()
    r = sensor.read()
    after = time.time()
    assert before <= r.timestamp <= after

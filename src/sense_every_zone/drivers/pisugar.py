"""
PiSugar 3 UPS battery driver.

Hardware: PiSugar 3 (~$20, includes 1200 mAh LiPo)
          Attaches underneath the Pi Zero 2W via pogo pins.
          I2C address: 0x57 (no conflict with SEN55 @ 0x69 or ADS1115 @ 0x48)

Software: pisugar-server systemd daemon (installed on the Pi).
          This driver talks to it via its TCP socket API (default port 8423).
          No extra Python dependencies — uses stdlib ``socket`` only.

Install pisugar-server on the Pi::

    curl http://cdn.pisugar.com/release/pisugar-power-manager.sh | sudo bash

That installs and starts the ``pisugar-server`` systemd service automatically.

TCP socket protocol (pisugar-server default port 8423):
    Client sends:  ``get battery\\n``
    Server replies: ``battery: 85\\n``

    Multiple commands can be sent in one connection; replies arrive in order.

sensors.yaml config keys:
    host          str   hostname / IP of pisugar-server (default "localhost")
    port          int   TCP port (default 8423)
    timeout_s     float socket timeout in seconds (default 2.0)
    alert_thresholds:
        battery_pct_low  int  warn when charge drops below this % (default 20)
"""

from __future__ import annotations

import logging
import socket
from typing import Optional

from .base import BaseSensor, RawReading

logger = logging.getLogger(__name__)

_COMMANDS = [
    "get battery",
    "get battery_charging",
    "get battery_power_plugged",
    "get battery_voltage",
]


class PiSugar3Sensor(BaseSensor):
    """PiSugar 3 UPS battery state via pisugar-server TCP socket."""

    def __init__(self, sensor_id: str, zone_id: str, config: dict) -> None:
        super().__init__(sensor_id, zone_id, config)
        self._host: str = config.get("host", "localhost")
        self._port: int = int(config.get("port", 8423))
        self._timeout: float = float(config.get("timeout_s", 2.0))
        thresh = config.get("alert_thresholds", {})
        self._battery_low: int = int(thresh.get("battery_pct_low", 20))
        logger.info(
            "PiSugar3 %s configured (%s:%d low_threshold=%d%%)",
            self.sensor_id, self._host, self._port, self._battery_low,
        )

    # ------------------------------------------------------------------
    # BaseSensor interface
    # ------------------------------------------------------------------

    def read(self) -> RawReading:
        data = self._query()
        r = self._blank()

        raw_pct = data.get("battery")
        if raw_pct is not None:
            try:
                r.battery_pct = int(float(raw_pct))
            except ValueError:
                pass

        raw_charging = data.get("battery_charging")
        if raw_charging is not None:
            r.battery_charging = raw_charging.lower() == "true"

        raw_plugged = data.get("battery_power_plugged")
        if raw_plugged is not None:
            r.battery_power_plugged = raw_plugged.lower() == "true"

        raw_voltage = data.get("battery_voltage")
        if raw_voltage is not None:
            try:
                # pisugar-server reports voltage in mV
                r.battery_voltage_v = round(float(raw_voltage) / 1000, 3)
            except ValueError:
                pass

        self._check_threshold(r, "battery_pct", "BATTERY", low=self._battery_low)
        return r

    def healthy(self) -> bool:
        try:
            data = self._query()
            return "battery" in data
        except Exception:
            return False

    def close(self) -> None:
        pass  # stateless TCP calls — nothing to release

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _query(self) -> dict[str, str]:
        """Send all commands in one connection, parse key: value pairs."""
        payload = "".join(f"{cmd}\n" for cmd in _COMMANDS).encode()
        result: dict[str, str] = {}

        with socket.create_connection(
            (self._host, self._port), timeout=self._timeout
        ) as sock:
            sock.sendall(payload)
            # Signal we're done writing so the server flushes its replies
            sock.shutdown(socket.SHUT_WR)
            raw = b""
            while True:
                chunk = sock.recv(512)
                if not chunk:
                    break
                raw += chunk
                # Stop early once we have a reply line for every command
                if raw.count(b"\n") >= len(_COMMANDS):
                    break

        for line in raw.decode(errors="replace").strip().splitlines():
            if ": " in line:
                key, _, value = line.partition(": ")
                result[key.strip()] = value.strip()

        if not result:
            raise RuntimeError(
                f"pisugar-server at {self._host}:{self._port} returned no data"
            )
        return result

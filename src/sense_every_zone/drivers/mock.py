"""
Mock sensor driver — synthesized readings with realistic noise.

Used in CI, development on non-Pi machines, and as the placeholder
while hardware is being wired up.  Emulates a full SEN55 + CO + O2 node
so all dashboard tiles render with plausible data.
"""

from __future__ import annotations

import math
import random
import time

from .base import BaseSensor, RawReading


class MockSensor(BaseSensor):
    """Synthesized multi-measurement sensor for dev / CI."""

    def __init__(self, sensor_id: str, zone_id: str, config: dict) -> None:
        super().__init__(sensor_id, zone_id, config)
        self._start = time.time()
        self._healthy = True

    # Simulate a slow drift + noise on temperature
    def _temp(self) -> float:
        t = time.time() - self._start
        return round(22.0 + 0.5 * math.sin(t / 300) + random.gauss(0, 0.05), 2)

    def _hum(self) -> float:
        t = time.time() - self._start
        return round(48.0 + 3 * math.sin(t / 600 + 1) + random.gauss(0, 0.3), 1)

    def read(self) -> RawReading:
        r = self._blank()
        r.temperature_c = self._temp()
        r.humidity_rh = self._hum()
        r.voc_index = int(100 + random.gauss(0, 5))
        r.nox_index = int(10 + random.gauss(0, 1))
        r.pm1_ug_m3 = round(abs(random.gauss(2, 0.5)), 2)
        r.pm25_ug_m3 = round(abs(random.gauss(3, 0.8)), 2)
        r.pm4_ug_m3 = round(abs(random.gauss(3.5, 0.9)), 2)
        r.pm10_ug_m3 = round(abs(random.gauss(4, 1.0)), 2)
        r.co_ppm = round(abs(random.gauss(1.0, 0.2)), 2)
        r.o2_percent = round(20.9 + random.gauss(0, 0.05), 2)
        # Simulated PiSugar 3 battery — slowly discharging then recharging
        t = time.time() - self._start
        cycle = (t % 3600) / 3600      # 0–1 over a 1-hour fake cycle
        r.battery_pct = int(60 + 30 * math.sin(2 * math.pi * cycle))
        r.battery_charging = cycle > 0.5
        r.battery_power_plugged = True
        r.battery_voltage_v = round(3.6 + 0.6 * (r.battery_pct / 100), 3)
        return r

    def healthy(self) -> bool:
        return self._healthy

    def close(self) -> None:
        pass

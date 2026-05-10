"""
Alphasense OX-B431 electrochemical O2 sensor driver.

Hardware: Alphasense OX-B431 + ISB + ADS1115 (shared with CO-B4 if wired
          to a spare channel on the same board).
Library:  adafruit-circuitpython-ads1x15

The OX-B431 ISB outputs a single voltage proportional to O2 partial
pressure.  Calibration uses one zero-point and one sensitivity value
from the certificate.  At 20.9% O2 (ambient air) the output is typically
around 1.7–1.9 V depending on the unit.

Conversion:
    O2 % = (V_WE − WE_zero) / sensitivity_v_percent

where ``sensitivity_v_percent`` is in V per % O2.

sensors.yaml config keys:
    ads1115_i2c_bus        int    I2C bus number (default 1)
    ads1115_address        int    ADS1115 I2C address (default 0x48)
    channel_we             int    ADS1115 channel for WE output (0–3)
    calibration:
        we_zero_v              float  WE zero-gas offset (V) from certificate
        sensitivity_v_percent  float  V per % O2 from certificate
    alert_thresholds:
        o2_percent_low         float  Warn if O2 drops below this (default 19.5)
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import BaseSensor, RawReading

logger = logging.getLogger(__name__)

_O2_AMBIENT = 20.9   # % — used only for healthy() sanity check


class AlphaOXSensor(BaseSensor):
    """Alphasense OX-B431 O2 sensor via ISB + ADS1115 ADC."""

    def __init__(self, sensor_id: str, zone_id: str, config: dict) -> None:
        super().__init__(sensor_id, zone_id, config)
        self._ads = None
        self._ch_we = None
        cal = config.get("calibration", {})
        self._we_zero: float = float(cal.get("we_zero_v", 0.010))
        self._sensitivity: float = float(cal.get("sensitivity_v_percent", 0.0156))
        thresh = config.get("alert_thresholds", {})
        self._o2_low: float = float(thresh.get("o2_percent_low", 19.5))
        self._init_hardware()

    def _init_hardware(self) -> None:
        try:
            import board
            import adafruit_ads1x15.ads1115 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn

            bus_num = self.config.get("ads1115_i2c_bus", 1)
            addr = self.config.get("ads1115_address", 0x48)
            i2c = board.I2C()
            self._ads = ADS.ADS1115(i2c, address=addr)

            ch = self.config.get("channel_we", 2)
            channel_map = [ADS.P0, ADS.P1, ADS.P2, ADS.P3]
            self._ch_we = AnalogIn(self._ads, channel_map[ch])

            logger.info(
                "AlphaOX %s initialised (bus=%s ads=0x%02X WE=ch%d)",
                self.sensor_id, bus_num, addr, ch,
            )
        except Exception as exc:
            logger.error("AlphaOX %s init failed: %s", self.sensor_id, exc)
            self._ads = None

    def _concentration(self) -> float:
        v_we = self._ch_we.voltage
        return (v_we - self._we_zero) / self._sensitivity

    def read(self) -> RawReading:
        if self._ads is None:
            raise RuntimeError(f"AlphaOX {self.sensor_id!r} not initialised")
        r = self._blank()
        raw = self._concentration()
        r.o2_percent = round(max(0.0, min(100.0, raw)), 2)
        self._check_threshold(r, "o2_percent", "O2", low=self._o2_low)
        return r

    def healthy(self) -> bool:
        if self._ads is None:
            return False
        try:
            pct = self._concentration()
            # Sanity: O2 should be within 5% of ambient unless something is very wrong
            return 0 < pct < 30
        except Exception:
            return False

    def close(self) -> None:
        self._ads = None
        self._ch_we = None

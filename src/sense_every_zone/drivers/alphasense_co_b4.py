"""
Alphasense CO-B4 electrochemical CO sensor driver.

Hardware: Alphasense CO-B4 (4-electrode) + ISB (Individual Sensor Board)
          + Adafruit ADS1115 16-bit ADC (ID 1085, I2C address 0x48).
Library:  adafruit-circuitpython-ads1x15
          pip install adafruit-blinka adafruit-circuitpython-ads1x15

Theory (Alphasense Application Note AN-006):
    The ISB outputs two voltages:
        V_WE  — working electrode (proportional to CO + background)
        V_AE  — auxiliary electrode (background only, same as WE at zero gas)

    Concentration = ((V_WE − WE_zero) − (V_AE − AE_zero)) / sensitivity

All three calibration constants (we_zero_v, ae_zero_v, sensitivity_v_ppm)
are printed on the calibration certificate shipped with each sensor.
Record them in sensors.yaml under the ``calibration:`` key.

sensors.yaml config keys:
    ads1115_i2c_bus   int    I2C bus number (default 1)
    ads1115_address   int    ADS1115 I2C address (default 0x48)
    channel_we        int    ADS1115 channel for working electrode (0–3)
    channel_ae        int    ADS1115 channel for auxiliary electrode (0–3)
    calibration:
        we_zero_v          float  WE zero offset (V) from certificate
        ae_zero_v          float  AE zero offset (V) from certificate
        sensitivity_v_ppm  float  Sensitivity (V/ppm) from certificate
    alert_thresholds:
        co_ppm             float  Warn if CO exceeds this (ppm)
"""

from __future__ import annotations

import logging
from typing import Optional

from .base import BaseSensor, RawReading

logger = logging.getLogger(__name__)


class AlphaCOB4Sensor(BaseSensor):
    """Alphasense CO-B4 via ISB + ADS1115 ADC."""

    def __init__(self, sensor_id: str, zone_id: str, config: dict) -> None:
        super().__init__(sensor_id, zone_id, config)
        self._ads = None
        self._ch_we = None
        self._ch_ae = None
        cal = config.get("calibration", {})
        self._we_zero: float = float(cal.get("we_zero_v", 0.346))
        self._ae_zero: float = float(cal.get("ae_zero_v", 0.347))
        self._sensitivity: float = float(cal.get("sensitivity_v_ppm", 0.000421))
        thresh = config.get("alert_thresholds", {})
        self._co_high: Optional[float] = thresh.get("co_ppm")
        self._init_hardware()

    def _init_hardware(self) -> None:
        try:
            import board
            import busio
            import adafruit_ads1x15.ads1115 as ADS
            from adafruit_ads1x15.analog_in import AnalogIn

            bus_num = self.config.get("ads1115_i2c_bus", 1)
            addr = self.config.get("ads1115_address", 0x48)
            i2c = board.I2C()
            self._ads = ADS.ADS1115(i2c, address=addr)

            ch_we = self.config.get("channel_we", 0)
            ch_ae = self.config.get("channel_ae", 1)
            channel_map = [ADS.P0, ADS.P1, ADS.P2, ADS.P3]
            self._ch_we = AnalogIn(self._ads, channel_map[ch_we])
            self._ch_ae = AnalogIn(self._ads, channel_map[ch_ae])

            logger.info(
                "AlphaCO-B4 %s initialised (bus=%s ads=0x%02X WE=ch%d AE=ch%d)",
                self.sensor_id, bus_num, addr, ch_we, ch_ae,
            )
        except Exception as exc:
            logger.error("AlphaCO-B4 %s init failed: %s", self.sensor_id, exc)
            self._ads = None

    def _concentration(self) -> float:
        v_we = self._ch_we.voltage
        v_ae = self._ch_ae.voltage
        return ((v_we - self._we_zero) - (v_ae - self._ae_zero)) / self._sensitivity

    def read(self) -> RawReading:
        if self._ads is None:
            raise RuntimeError(f"AlphaCO-B4 {self.sensor_id!r} not initialised")
        r = self._blank()
        r.co_ppm = round(max(0.0, self._concentration()), 2)
        self._check_threshold(r, "co_ppm", "CO", high=self._co_high)
        return r

    def healthy(self) -> bool:
        if self._ads is None:
            return False
        try:
            _ = self._ch_we.voltage
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._ads = None
        self._ch_we = None
        self._ch_ae = None

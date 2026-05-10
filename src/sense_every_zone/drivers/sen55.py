"""
Sensirion SEN55 all-in-one environmental sensor driver.

Hardware: SparkFun SEN55 Environmental Sensor Node Breakout (DEV-21354)
          or bare Sensirion SEN55-SDN-T with JST ZH breakout adapter.
          Fixed I2C address: 0x69.
Library:  sensirion-i2c-driver + sensirion-i2c-sen5x
          pip install sensirion-i2c-driver sensirion-i2c-sen5x

Measurements provided in one read():
    temperature_c, humidity_rh, voc_index, nox_index,
    pm1_ug_m3, pm25_ug_m3, pm4_ug_m3, pm10_ug_m3

The SEN55 needs ~1 s between start_measurement() and the first valid
reading.  The driver starts measurement in __init__ and discards the
first poll if the sensor reports NaN (is_nan guard below).

sensors.yaml config keys:
    i2c_bus  int  Linux I2C bus number (default 1 → /dev/i2c-1)
"""

from __future__ import annotations

import logging
import time

from .base import BaseSensor, RawReading

logger = logging.getLogger(__name__)

_SEN55_I2C_ADDR = 0x69


class SEN55Sensor(BaseSensor):
    """Sensirion SEN55 PM + VOC + NOx + T + RH sensor."""

    def __init__(self, sensor_id: str, zone_id: str, config: dict) -> None:
        super().__init__(sensor_id, zone_id, config)
        self._device = None
        self._transceiver = None
        self._init_hardware()

    def _init_hardware(self) -> None:
        try:
            from sensirion_i2c_driver import LinuxI2cTransceiver, I2cConnection
            from sensirion_i2c_sen5x import Sen5xI2cDevice

            bus_num = self.config.get("i2c_bus", 1)
            bus_path = f"/dev/i2c-{bus_num}"
            self._transceiver = LinuxI2cTransceiver(bus_path)
            connection = I2cConnection(self._transceiver)
            self._device = Sen5xI2cDevice(connection)
            self._device.start_measurement()
            # Allow first measurement interval to complete
            time.sleep(1.1)
            logger.info(
                "SEN55 %s initialised (bus=%s addr=0x%02X)",
                self.sensor_id, bus_path, _SEN55_I2C_ADDR,
            )
        except Exception as exc:
            logger.error("SEN55 %s init failed: %s", self.sensor_id, exc)
            self._device = None

    def read(self) -> RawReading:
        if self._device is None:
            raise RuntimeError(f"SEN55 {self.sensor_id!r} not initialised")

        m = self._device.read_measured_values()
        r = self._blank()

        if not m.ambient_temperature.is_nan:
            r.temperature_c = round(m.ambient_temperature.degrees_celsius, 2)
        if not m.ambient_humidity.is_nan:
            r.humidity_rh = round(m.ambient_humidity.percent_rh, 1)
        if not m.voc_index.is_nan:
            r.voc_index = int(m.voc_index.scaled)
        if not m.nox_index.is_nan:
            r.nox_index = int(m.nox_index.scaled)
        if not m.mass_concentration_1p0.is_nan:
            r.pm1_ug_m3 = round(m.mass_concentration_1p0.physical, 2)
        if not m.mass_concentration_2p5p.is_nan:
            r.pm25_ug_m3 = round(m.mass_concentration_2p5p.physical, 2)
        if not m.mass_concentration_4p0.is_nan:
            r.pm4_ug_m3 = round(m.mass_concentration_4p0.physical, 2)
        if not m.mass_concentration_10p0.is_nan:
            r.pm10_ug_m3 = round(m.mass_concentration_10p0.physical, 2)

        return r

    def healthy(self) -> bool:
        if self._device is None:
            return False
        try:
            self._device.read_measured_values()
            return True
        except Exception:
            return False

    def close(self) -> None:
        try:
            if self._device is not None:
                self._device.stop_measurement()
        except Exception:
            pass
        try:
            if self._transceiver is not None:
                self._transceiver.close()
        except Exception:
            pass
        self._device = None
        self._transceiver = None

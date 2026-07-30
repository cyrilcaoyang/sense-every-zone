"""
Sensirion SEN55 environmental sensor driver — raw smbus2 implementation.

Hardware: SparkFun SEN55 Environmental Sensor Node Breakout (DEV-21354)
          or bare Sensirion SEN55-SDN-T with JST ZH breakout adapter.
          Fixed I2C address: 0x69.
Library:  smbus2 (raw I2C transactions, no Sensirion SDK dependency)

Migrated from the proven sen55-enviro-sensor repo. Uses the raw SEN5x
driver (``sen5x_i2c.py``) for direct I2C communication — the same code
that has been running in production on a Pi Zero 2 W.

Measurements provided in one read():
    temperature_c, humidity_rh, voc_index, nox_index,
    pm1_ug_m3, pm25_ug_m3, pm4_ug_m3, pm10_ug_m3

Robustness features carried over from the production sampler:
  * data_ready() polling — only reads when a new measurement is available
  * Reinit after N consecutive errors (not on a single transient glitch)
  * Warmup delay after start() before the first read attempt
  * Device status register read on every successful sample
  * Temperature offset compensation (applied on every boot, volatile)

sensors.yaml config keys:
    i2c_bus           int    Linux I2C bus number (default 1 → /dev/i2c-1)
    temp_offset_c     float  RH/T self-heating correction in °C (default 0)
    temp_offset_slope float  Slope component of temp compensation (default 0)
    fan_clean_interval_s int  Auto fan-clean interval in seconds (0 = disabled)
    alert_thresholds  dict   Threshold checks for alert generation
        pm25_high, pm10_high, voc_high, nox_high, temp_high, temp_low,
        humidity_high, humidity_low
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .base import BaseSensor, RawReading
from .sen5x_i2c import SEN5x

logger = logging.getLogger(__name__)

# Number of consecutive read failures before we tear down and re-init the
# sensor. A single failure (e.g. first poll before warm-up, one-off bus
# glitch) is tolerated without a disruptive reset/start cycle.
REINIT_AFTER_READ_ERRORS = 5

# Seconds to wait after start() before the first measurement read. The SEN5x
# needs the fan/laser to spin up and a first measurement to complete (~1 s
# per the datasheet); reading before then returns an I2C I/O error.
WARMUP_AFTER_START_S = 2.0


class SEN55Sensor(BaseSensor):
    """Sensirion SEN55 PM + VOC + NOx + T + RH sensor (raw smbus2 driver)."""

    def __init__(self, sensor_id: str, zone_id: str, config: dict) -> None:
        super().__init__(sensor_id, zone_id, config)
        self._device: Optional[SEN5x] = None
        self._consecutive_errors = 0
        self._last_status_raw: Optional[int] = None
        self._init_hardware()

    def _init_hardware(self) -> None:
        try:
            bus_num = self.config.get("i2c_bus", 1)
            self._device = SEN5x(bus_num=bus_num)
            self._device.reset()

            # Apply temperature offset compensation if configured.
            # The value is volatile on the SEN5x, so re-apply on every boot.
            temp_offset = self.config.get("temp_offset_c", 0.0)
            temp_slope = self.config.get("temp_offset_slope", 0.0)
            if temp_offset != 0.0 or temp_slope != 0.0:
                self._device.set_temp_offset(
                    offset_c=temp_offset, slope=temp_slope
                )
                logger.info(
                    "SEN55 %s temp offset applied: offset=%.2f°C slope=%.6f",
                    self.sensor_id, temp_offset, temp_slope,
                )

            # Configure auto fan-clean interval if set.
            fan_clean_s = self.config.get("fan_clean_interval_s", 0)
            if fan_clean_s > 0:
                self._device.set_auto_clean_interval(int(fan_clean_s))
                logger.info(
                    "SEN55 %s auto fan-clean set to every %ds",
                    self.sensor_id, fan_clean_s,
                )

            self._device.start()
            # Let the fan/laser spin up and the first measurement complete
            time.sleep(WARMUP_AFTER_START_S)

            # Capture device identity (best-effort)
            try:
                name = self._device.product_name()
                serial = self._device.serial_number()
                fw = self._device.firmware_version()
                logger.info(
                    "SEN55 %s initialised: %s serial=%s fw=v%s (bus=%d)",
                    self.sensor_id, name, serial, fw, bus_num,
                )
            except Exception:
                logger.info("SEN55 %s initialised (bus=%d)", self.sensor_id, bus_num)

        except Exception as exc:
            logger.error("SEN55 %s init failed: %s", self.sensor_id, exc)
            # Close the SMBus fd if the device was opened but init failed
            # partway through — otherwise repeated reinit attempts leak fds.
            if self._device is not None:
                try:
                    self._device.close()
                except Exception:
                    pass
            self._device = None

    def read(self) -> RawReading:
        if self._device is None:
            # Try to reinit if we lost the device
            self._init_hardware()
            if self._device is None:
                raise RuntimeError(f"SEN55 {self.sensor_id!r} not initialised")

        r = self._blank()

        try:
            if not self._device.data_ready():
                # Sensor answered but has no new measurement yet (normal
                # right after start() and between the ~1 Hz update cadence).
                return r

            values = self._device.read()

            if values["temp_c"] is not None:
                r.temperature_c = round(values["temp_c"], 2)
            if values["rh"] is not None:
                r.humidity_rh = round(values["rh"], 1)
            if values["voc"] is not None:
                r.voc_index = round(values["voc"])
            if values["nox"] is not None:
                r.nox_index = round(values["nox"])
            if values["pm1_0"] is not None:
                r.pm1_ug_m3 = round(values["pm1_0"], 2)
            if values["pm2_5"] is not None:
                r.pm25_ug_m3 = round(values["pm2_5"], 2)
            if values["pm4_0"] is not None:
                r.pm4_ug_m3 = round(values["pm4_0"], 2)
            if values["pm10"] is not None:
                r.pm10_ug_m3 = round(values["pm10"], 2)

            # Read device status register on successful sample
            try:
                status = self._device.device_status()
                self._last_status_raw = status["raw"]
                # Suppress fault alerts during scheduled fan cleaning —
                # fan_speed_out_of_range can legitimately assert while
                # the fan runs at max speed for the 10s clean cycle.
                if status["fan_cleaning_active"]:
                    logger.debug(
                        "SEN55 %s fan clean active — suppressing fault alerts",
                        self.sensor_id,
                    )
                else:
                    faults = (
                        status["gas_sensor_error"] or status["rht_comm_error"]
                        or status["laser_failure"] or status["fan_failure"]
                        or status["fan_speed_out_of_range"]
                    )
                    if faults:
                        fault_strs = [
                            k for k, v in status.items()
                            if v and k != "raw" and k != "fan_cleaning_active"
                        ]
                        r.alerts.append(
                            f"SEN55_DEVICE_FAULT:{','.join(fault_strs)}"
                        )
            except Exception as exc:
                logger.warning("SEN55 %s status read failed: %s",
                               self.sensor_id, exc)

            self._consecutive_errors = 0
            self._check_thresholds(r)

        except Exception as exc:
            self._consecutive_errors += 1
            logger.warning(
                "SEN55 %s read failed (%d in a row): %s",
                self.sensor_id, self._consecutive_errors, exc,
            )
            if self._consecutive_errors >= REINIT_AFTER_READ_ERRORS:
                logger.warning(
                    "SEN55 %s re-initialising after %d consecutive errors",
                    self.sensor_id, self._consecutive_errors,
                )
                self._safe_close()
                self._device = None
                self._consecutive_errors = 0
            raise

        return r

    def healthy(self) -> bool:
        if self._device is None:
            return False
        try:
            self._device.data_ready()
            return True
        except Exception:
            return False

    def close(self) -> None:
        self._safe_close()

    def _safe_close(self) -> None:
        try:
            if self._device is not None:
                self._device.stop()
                self._device.close()
        except Exception:
            pass
        self._device = None

    def _check_thresholds(self, r: RawReading) -> None:
        """Evaluate alert_thresholds from config and populate r.alerts."""
        thresholds = self.config.get("alert_thresholds", {})
        if not thresholds:
            return

        self._check_threshold(r, "pm25_ug_m3", "PM25",
                              high=thresholds.get("pm25_high"))
        self._check_threshold(r, "pm10_ug_m3", "PM10",
                              high=thresholds.get("pm10_high"))
        self._check_threshold(r, "voc_index", "VOC",
                              high=thresholds.get("voc_high"))
        self._check_threshold(r, "nox_index", "NOX",
                              high=thresholds.get("nox_high"))
        self._check_threshold(r, "temperature_c", "TEMP",
                              high=thresholds.get("temp_high"))
        self._check_threshold(r, "temperature_c", "TEMP",
                              low=thresholds.get("temp_low"))
        self._check_threshold(r, "humidity_rh", "HUMIDITY",
                              high=thresholds.get("humidity_high"))
        self._check_threshold(r, "humidity_rh", "HUMIDITY",
                              low=thresholds.get("humidity_low"))

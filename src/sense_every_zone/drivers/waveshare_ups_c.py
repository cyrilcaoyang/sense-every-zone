"""
Waveshare UPS HAT (C) battery driver — INA219-based.

Hardware: Waveshare UPS HAT (C)
          TI INA219 current/voltage monitor IC at I2C address 0x43.
          Measures bus voltage (load side), shunt voltage, current, power.
          Battery percentage is derived from bus voltage using the
          Waveshare formula:  pct = (Vbus - 3.0) / 1.2 * 100, clamped [0, 100].

Library:  smbus2 (raw I2C register reads — no extra dependency beyond what
          ``[pi]`` already pulls in).

sensors.yaml config keys:
    i2c_bus           int    Linux I2C bus number (default 1 → /dev/i2c-1)
    i2c_address       int    INA219 I2C address (default 0x43)
    shunt_resistor   float  Shunt resistance in ohms (default 0.01)
    alert_thresholds  dict   Threshold checks for alert generation
        battery_pct_low  int  warn when charge drops below this % (default 20)

Based on the Waveshare example code (INA219.py from the UPS_HAT_C archive),
adapted to the BaseSensor interface and using smbus2 instead of smbus.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .base import BaseSensor, RawReading

logger = logging.getLogger(__name__)

# INA219 register addresses
_REG_CONFIG = 0x00
_REG_SHUNTVOLTAGE = 0x01
_REG_BUSVOLTAGE = 0x02
_REG_POWER = 0x03
_REG_CURRENT = 0x04
_REG_CALIBRATION = 0x05

# Calibration constants (Waveshare defaults: 16V range, 5A max, Rshunt=0.01Ω)
_CAL_VALUE = 26868
_CURRENT_LSB_MA = 0.1524  # mA per bit (matches Waveshare example)
_POWER_LSB_W = 0.003048  # W per bit

# Config register value: 16V range, gain /2 (80mV), 12-bit 32-sample,
# shunt+bus continuous mode.
_CONFIG_VALUE = (
    (0x00 << 13)  # RANGE_16V
    | (0x01 << 11)  # GAIN_DIV_2_80MV
    | (0x0D << 7)  # ADCRES_12BIT_32S (bus)
    | (0x0D << 3)  # ADCRES_12BIT_32S (shunt)
    | 0x07  # SANDBVOLT_CONTINUOUS
)


class WaveshareUPSCSensor(BaseSensor):
    """Waveshare UPS HAT (C) battery state via INA219 I2C registers."""

    def __init__(self, sensor_id: str, zone_id: str, config: dict) -> None:
        super().__init__(sensor_id, zone_id, config)
        self._i2c_bus: int = int(config.get("i2c_bus", 1))
        self._addr: int = int(config.get("i2c_address", 0x43))
        thresh = config.get("alert_thresholds", {})
        self._battery_low: int = int(thresh.get("battery_pct_low", 20))
        self._smbus = None
        self._initialized = False
        logger.info(
            "WaveshareUPSC %s configured (bus=%d addr=0x%02X low_threshold=%d%%)",
            self.sensor_id, self._i2c_bus, self._addr, self._battery_low,
        )

    # ------------------------------------------------------------------
    # BaseSensor interface
    # ------------------------------------------------------------------

    def read(self) -> RawReading:
        self._ensure_initialized()
        r = self._blank()

        bus_v = self._read_bus_voltage_v()
        if bus_v is not None:
            r.battery_voltage_v = round(bus_v, 3)
            # Battery percentage from Waveshare formula
            pct = (bus_v - 3.0) / 1.2 * 100
            pct = max(0, min(100, pct))
            r.battery_pct = round(pct)

        # INA219 can also provide current, but the RawReading dataclass
        # only has battery fields — so we stop here. If current monitoring
        # is needed later, extend RawReading.

        # Charging / power-plugged: the INA219 doesn't directly report
        # charge state. We infer "plugged" from bus voltage > 3.3V
        # (below that the battery is nearly dead or disconnected).
        if bus_v is not None:
            r.battery_power_plugged = bus_v > 3.3
            # INA219 can't distinguish charging from plugged-in-full,
            # so we report charging == power_plugged (conservative).
            r.battery_charging = r.battery_power_plugged

        self._check_threshold(r, "battery_pct", "BATTERY", low=self._battery_low)
        return r

    def healthy(self) -> bool:
        try:
            self._ensure_initialized()
            return self._read_bus_voltage_v() is not None
        except Exception:
            return False

    def close(self) -> None:
        if self._smbus is not None:
            try:
                self._smbus.close()
            except Exception:
                pass
            self._smbus = None
            self._initialized = False

    # ------------------------------------------------------------------
    # Internal — INA219 register access via smbus2
    # ------------------------------------------------------------------

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        from smbus2 import SMBus

        self._smbus = SMBus(self._i2c_bus)
        # Write calibration register
        self._write_reg(_REG_CALIBRATION, _CAL_VALUE)
        # Write config register
        self._write_reg(_REG_CONFIG, _CONFIG_VALUE)
        self._initialized = True
        logger.debug(
            "WaveshareUPSC %s initialized (bus=%d addr=0x%02X)",
            self.sensor_id, self._i2c_bus, self._addr,
        )

    def _read_reg(self, reg: int) -> Optional[int]:
        """Read a 16-bit INA219 register. Returns None on error."""
        if self._smbus is None:
            return None
        try:
            data = self._smbus.read_i2c_block_data(self._addr, reg, 2)
            return (data[0] << 8) | data[1]
        except Exception as exc:
            logger.warning("WaveshareUPSC %s read reg 0x%02X failed: %s",
                            self.sensor_id, reg, exc)
            return None

    def _write_reg(self, reg: int, value: int) -> None:
        """Write a 16-bit INA219 register."""
        if self._smbus is None:
            return
        hi = (value >> 8) & 0xFF
        lo = value & 0xFF
        self._smbus.write_i2c_block_data(self._addr, reg, [hi, lo])

    def _read_bus_voltage_v(self) -> Optional[float]:
        """Read bus voltage from INA219 register 0x02.

        The bus voltage register format: bits [15:3] = voltage / 0.004,
        bits [2:1] = CNVR (conversion ready), bit [0] = OVF (overflow).
        We shift right 3 and multiply by 4mV (0.004) per the datasheet.
        """
        # Re-trigger calibration before reading (Waveshare example does this)
        self._write_reg(_REG_CALIBRATION, _CAL_VALUE)
        raw = self._read_reg(_REG_BUSVOLTAGE)
        if raw is None:
            return None
        return (raw >> 3) * 0.004
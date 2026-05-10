# sense-every-zone

Environmental sensor nodes for the AC Organic Self-Driving Lab.
Exposes temperature, humidity, VOC, NOx, PM, CO, and O₂ readings as
**STATUS_SPEC v1.0** HTTP endpoints, polled by the `ac-organic-lab`
dashboard aggregator.

## Architecture

```
ac-organic-lab aggregator
        │  GET /zones/{zone_id}/status  (every ~5 s)
        ▼
sense-every-zone (FastAPI :8030)
        │
        ├── Zone: env_lab499_west  ── SEN55 (T/RH/VOC/NOx/PM)
        ├── Zone: env_fumehood     ── SEN55 + CO-B4 + OX-B431
        ├── Zone: env_storage      ── SEN55
        └── Zone: env_sample_prep  ── SEN55
```

One process per Pi host; zones are configured in `sensors.yaml`.

## Hardware

| Driver | Hardware | Measurements |
|--------|----------|--------------|
| `sen55` | Sensirion SEN55 module (`SEN55-SDN-T`) | T, RH, VOC index, NOx index, PM1/2.5/4/10 |
| `alphasense_co_b4` | Alphasense CO-B4 + ISB + ADS1115 | CO ppm |
| `alphasense_ox` | Alphasense OX-B431 + ISB + ADS1115 | O₂ % |
| `pisugar` | PiSugar 3 (via pisugar-server daemon) | battery %, charging, voltage |
| `mock` | — | Synthesized readings (dev / CI) |

## Node design

Each zone node is self-contained on a single USB-C power plug in a 3D-printed case.
The SEN55 is 50 × 50 × 25 mm and must be open to ambient air — design intake and
exhaust vents in the case lid aligned to the sensor's grilles.

```
Wall plug (USB-C 5V 2.5A)
    │
    └──► PiSugar 3              ← attaches under Pi via pogo pins (no GPIO header used)
              │                    I2C 0x57, charges LiPo, powers Pi
         Pi Zero 2W
              │
         PiSugar 3 extension interface  (1.27 mm male header, position 7 on PCB)
         ┌──────────────────────────────────────────────────┐
         │  5V ── VDD  (pin 1 of SEN55 jumper cable)        │
         │  GND ── GND (pin 2)                              │
         │  SDAT ── SDA (pin 3)   ← Pi's GPIO2, I2C bus    │
         │  SSCL ── SCL (pin 4)   ← Pi's GPIO3, I2C bus    │
         │  GND ── SEL (pin 5)    ← selects I2C mode        │
         │         NC  (pin 6)    ← leave floating          │
         └──────────────────────────────────────────────────┘
              │
         Sensirion SEN5x Jumper Cable (6 individual female Dupont pins)
         [Mouser 403-SEN5XJUMPERCABLE — mates directly to SEN55's JST GHR-06V-S]
              │
         SEN55 module (SEN55-SDN-T)  I2C address 0x69
         [mounted in 3D-printed case with vented lid — needs airflow]
              │
              └──► ADS1115 breakout (0x48)   ← fumehood node only
                       ├── CH0 + CH1: CO-B4 ISB (working + auxiliary electrode)
                       └── CH2:       OX-B431 ISB
```

**SEN55 power note:** the SEN55 takes 5V on VDD (it has an internal 3.3V regulator).
The PiSugar 3 extension interface provides 5V — no level shifting or extra regulator needed.
I2C signal lines (SDA/SCL) are 3.3V logic, compatible with the Pi.

I2C address map (all distinct, verified conflict-free):

| Device | Address | Notes |
|--------|---------|-------|
| SEN55 | `0x69` | fixed |
| ADS1115 | `0x48` | ADDR pin → GND |
| PiSugar 3 MCU | `0x57` | battery stats |
| PiSugar 3 RTC | `0x68` | ds3231-compatible |

## Bill of Materials

### Basic zone node (×4 zones)

| Qty | Part | Source | Unit | Total |
|-----|------|--------|------|-------|
| 1 | Raspberry Pi Zero 2W (with headers) | raspberrypi.com | $15 | $15 |
| 1 | PiSugar 3 (includes 1200 mAh LiPo) | pisugar.com | $20 | $20 |
| 1 | Sensirion SEN55 module `SEN55-SDN-T` | Mouser | $60 | $60 |
| 1 | Sensirion SEN5x Jumper Cable | Mouser `403-SEN5XJUMPERCABLE` | $8 | $8 |
| 1 | USB-C 5V 2.5A wall adapter | — | $8 | $8 |
| — | 3D-printed case (PLA filament) | — | ~$2 | ~$2 |
| — | **Per node** | | | **~$113** |
| — | **4 basic nodes** | | | **~$452** |

### Fumehood node additions

| Qty | Part | Source | Unit | Total |
|-----|------|--------|------|-------|
| 1 | Alphasense CO-B4 sensor | alphasense.com (direct) | $95 | $95 |
| 1 | Alphasense ISB for CO-B4 | alphasense.com (direct) | $35 | $35 |
| 1 | Alphasense OX-B431 sensor | alphasense.com (direct) | $100 | $100 |
| 1 | Alphasense ISB for OX-B431 | alphasense.com (direct) | $35 | $35 |
| 1 | Adafruit ADS1115 ADC (ID 1085) | adafruit.com | $10 | $10 |
| — | **Fumehood additions** | | | **~$275** |
| — | **Fumehood node total** | | | **~$388** |

> Order Alphasense sensors directly from **alphasense.com** — each ships with
> a calibration certificate (PDF) containing the `we_zero_v`, `ae_zero_v`,
> and `sensitivity_v_ppm` values required in `sensors.yaml`.
>
> The [PiSugar 3D case files](https://github.com/PiSugar/PiSugar/tree/master/model3)
> are a good starting point for the enclosure — extend them to add SEN55 mounting
> tabs and intake/exhaust vents aligned to the sensor's grilles.

## Quick start

```bash
# 1. Install (Pi: add [pi] for hardware drivers)
pip install -e ".[api]"            # dev machine (mock sensors only)
pip install -e ".[api,pi]"         # Raspberry Pi with real hardware

# 2. Configure
cp sensors.yaml.example sensors.yaml
# Edit sensors.yaml for your zones and sensor IDs

# 3. Run
uvicorn sense_every_zone.api.server:app --host 0.0.0.0 --port 8030 \
    --reload --reload-include "*.yaml"
```

## sensors.yaml

Gitignored. Copy from `sensors.yaml.example` and fill in your zone IDs,
I2C bus numbers, and (for Alphasense sensors) the calibration coefficients
from the certificate shipped with each sensor.

Environment variable overrides:

| Variable | Default | Description |
|----------|---------|-------------|
| `SEZ_SENSORS_PATH` | `./sensors.yaml` | Path to sensors.yaml |
| `SEZ_LOG_DIR` | `/var/log/sense_every_zone` | Log directory |
| `SEZ_LOG_LEVEL` | `INFO` | Log level |
| `SEZ_HOST` | `0.0.0.0` | Bind address |
| `SEZ_PORT` | `8030` | Bind port |

## equipment.yaml integration

For each zone served by this process, add an entry in
`ac-organic-lab/equipment.yaml`:

```yaml
  - id: env_lab499_west
    name: Lab 499 (West) Sensors
    platform: lab
    kind: environmental_sensor
    adapter: http          # change from mock once deployed
    protocol: "1.0"
    base_url: http://100.64.254.100:8030
    status_path: /zones/env_lab499_west/status
    poll_timeout_seconds: 8.0
    location: { x: 20, y: 75, label: "Lab 499 · West" }
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Identity probe |
| `GET /health` | Service + sensor health |
| `GET /zones` | List all zones (summary) |
| `GET /zones/{zone_id}/status` | Full STATUS_SPEC v1.0 envelope |

## Alphasense calibration

Each CO-B4 and OX-B431 ships with a calibration certificate (PDF).
Record the three values per sensor in `sensors.yaml`:

```yaml
        calibration:
          we_zero_v: 0.346           # from certificate
          ae_zero_v: 0.347           # from certificate
          sensitivity_v_ppm: 0.000421  # from certificate
```

Without these values the driver falls back to datasheet typical values,
which reduces accuracy from ±2 ppm to roughly ±10 ppm.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

All 38 tests run without hardware (mock driver only).

## Pi setup

```bash
# 1. Flash Raspberry Pi OS Lite 64-bit, enable SSH in Imager
# 2. Boot, SSH in, then:
sudo raspi-config nonint do_i2c 0          # enable I2C
sudo apt update && sudo apt install -y i2c-tools

# 3. Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --authkey tskey-auth-XXXX --hostname sez-lab499-west

# 4. Install PiSugar 3 daemon
curl http://cdn.pisugar.com/release/pisugar-power-manager.sh | sudo bash

# 5. Verify I2C — expect 0x57 (PiSugar), 0x69 (SEN55), optionally 0x48 (ADS1115)
i2cdetect -y 1

# 6. Install sense-every-zone
pip install -e ".[api,pi]"
cp sensors.yaml.example sensors.yaml   # then edit for this node's zones
```

## Deployment (Pi systemd)

```ini
# /etc/systemd/system/sense-every-zone.service
[Unit]
Description=Sense Every Zone environmental sensor server
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/opt/sense-every-zone
EnvironmentFile=/opt/sense-every-zone/.env
ExecStart=/opt/sense-every-zone/.venv/bin/uvicorn \
    sense_every_zone.api.server:app \
    --host 0.0.0.0 --port 8030
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

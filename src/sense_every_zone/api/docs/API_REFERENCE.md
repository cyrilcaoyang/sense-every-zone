# Sense Every Zone API reference

Service version: 0.2.0. Status protocol: STATUS_SPEC 1.2.
Default local base URL: `http://localhost:8030`. All paths are relative to the
service base URL. No API authentication is implemented. All operations are GET
and read-only; there are no request bodies, pagination, or required query parameters.
JSON timestamps use ISO 8601 UTC. `/openapi.json` provides complete model schemas.

## Routes

| Method | Path | Success content type | Description |
| --- | --- | --- | --- |
| GET | `/` | application/json | Service identity |
| GET | `/health` | application/json | Service and zone reachability |
| GET | `/zones` | application/json | Array of configured zone summaries |
| GET | `/zones/{zone_id}/status` | application/json | Cached STATUS_SPEC 1.2 envelope |
| GET | `/agent-docs` | text/markdown | Agent integration guide |
| GET | `/agent-docs/api-reference` | text/markdown | This reference |
| GET | `/llms.txt` | text/plain | Documentation discovery |
| GET | `/openapi.json` | application/json | Generated OpenAPI schema |
| GET | `/docs` | text/html | Swagger UI |
| GET | `/redoc` | text/html | ReDoc |

## GET /

Always HTTP 200 while the application is serving, including without a registry:

```json
{"equipment_id":"sense_every_zone","equipment_name":"Sense Every Zone","protocol_version":"1.2"}
```

## GET /health

HTTP 200 with `ok` (boolean), `dependencies` (array of `name`, `ok`, optional
`message`), and `timestamp`. `ok` is false when configuration is missing or any
zone has no readings or no healthy sensors. A loaded registry with no zones
returns `ok: true` and an empty dependency list. A zone with at least one working
sensor is reachable, even if other sensors fail or thresholds are breached.
This is the service's local health shape, not the shared minimal health model.

## GET /zones

HTTP 200 with an array. Each item contains `zone_id`, `display_name`, `state`,
`sensor_count`, and `active_alert_count`. Without a registry the array is empty.
`sensor_count` counts registered drivers, including sensors whose reads fail;
configuration entries skipped during driver construction are not counted.
State uses the same rules as the full status endpoint.

## GET /zones/{zone_id}/status

`zone_id` is a required string path parameter discovered through `/zones`.
HTTP 200 returns an `EquipmentStatus` object:

| Field | Meaning |
| --- | --- |
| `protocol_version` | Always `"1.2"` in responses; shared schema defaults support older devices |
| `equipment_id`, `equipment_name` | Zone ID and display name |
| `equipment_kind` | `"environmental_sensor"` |
| `equipment_status` | `unknown` before first poll or with zero sensors; `error` if all reads fail; `degraded` for partial failure or active alerts; otherwise `ready` |
| `activity`, `activity_since` | `unknown` and null before first poll; otherwise `idle` and latest poll time |
| `device_time` | Response construction time |
| `uptime_seconds`, `host` | Service uptime and host name |
| `components` | Map of successfully read sensor IDs to connection state and reading time; failed sensors are omitted |
| `metrics` | Map of channel names to `{value, unit, timestamp}`; timestamp is zone poll completion time |
| `last_error` | First active alert, or `SENSOR_FAILURE` when all reads fail; otherwise null |
| `allowed_actions` | Always `[]` |
| `details.zone` | Zone-specific payload described below |

Additional shared-model fields may appear with default or null values. Clients
should tolerate additive fields. Status requests return cached snapshots; they
never initiate a sensor read. There is currently no automatic stale-data cutoff.

### Metrics

| Keys | Unit |
| --- | --- |
| `temperature` | °C |
| `humidity` | %RH |
| `voc`, `nox` | index |
| `pm1`, `pm25`, `pm4`, `pm10` | µg/m³ |
| `co`, `h2` | ppm |
| `o2`, `battery` | % |
| `battery_voltage` | V |

Example metric: `"temperature": {"value": 22.0, "unit": "°C", "timestamp": "2026-09-09T12:00:00Z"}`.
Unavailable channels are omitted. If multiple sensors provide a channel, the
last reading in configured sensor order wins in this flat map.

### Zone details

`details.zone` contains `zone_id`, `display_name`, `sensor_readings`,
`active_alerts`, `battery`, and `errors`.

Each sensor reading includes `sensor_id`, its own `timestamp`, and nullable
channels: `temperature_c`, `humidity_rh`, `voc_index`, `nox_index`, `pm1_ug_m3`,
`pm25_ug_m3`, `pm4_ug_m3`, `pm10_ug_m3`, `co_ppm`, `o2_percent`, `h2_ppm`.
Readings containing battery percentage are excluded from this list.

`battery` is null or an object with `charge_pct`, `charging`, `power_plugged`,
and nullable `voltage_v`, taken from the first reading with battery percentage.
`active_alerts` is the full list of raw alert strings (for example `CO_HIGH:34.20`).
`errors` is currently an empty list; use `active_alerts` for all alerts.
`last_error` has `code`, `message`, `severity`, and `timestamp`; it is not sorted
by severity, so it must not be treated as the complete alert summary.

### Errors

| HTTP status | Condition | JSON body |
| --- | --- | --- |
| 404 | Registry loaded, zone ID unknown | `{"detail":"Zone 'missing' not found"}` |
| 503 | Registry unavailable | `{"detail":"Registry not initialised"}` |

Registry availability is checked before zone lookup. FastAPI validation errors
use HTTP 422 with a `detail` array. Unsupported methods return HTTP 405.

## Documentation availability

The documentation endpoints return HTTP 200 UTF-8 text and work without a
sensor registry. Markdown is returned directly, not wrapped in JSON.
`/llms.txt` links to the guide, reference, and OpenAPI schema.

## Example workflow

```bash
curl --fail http://localhost:8030/agent-docs
curl --fail http://localhost:8030/health
curl --fail http://localhost:8030/zones
# Replace env_lab499_west with an ID returned by /zones:
curl --fail http://localhost:8030/zones/env_lab499_west/status
```

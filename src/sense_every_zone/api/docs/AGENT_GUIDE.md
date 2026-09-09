# Sense Every Zone agent guide

This service exposes cached environmental readings for configured zones using
STATUS_SPEC v1.2. It is read-only: there are no claim, control, configuration,
or calibration endpoints. `allowed_actions` is always an empty list.

## Discovery and polling

1. Fetch `GET /` to identify the service and protocol version.
2. Fetch `GET /health` and inspect `ok` and every dependency. HTTP 200 alone
   does not mean sensors are healthy.
3. Fetch `GET /zones` to discover zone IDs; do not assume example IDs exist.
4. Fetch `GET /zones/{zone_id}/status` for each required zone. URL-encode the ID
   as a path segment. A typical client interval is five seconds; GET requests
   read the cache and do not trigger hardware measurements.
5. Read `equipment_status`, `metrics`, and `details.zone.active_alerts` together.
   Use metric timestamps to judge freshness against your application's limit;
   `device_time` is response time, not measurement time.

Use a finite HTTP timeout (for example eight seconds) and bounded backoff for
connection failures or HTTP 503. Rediscover zones after HTTP 404; do not retry an
unknown ID indefinitely. Missing metrics are unavailable, never implicit zeros.
`unknown` means the zone has no sensors or has not completed a poll. `error`
means no sensors returned readings; `degraded` means partial failure or alerts.
Health tracks reachability, so a zone can have `ok: true` while alerts are active.

## Reading details

Metric keys omit units: for example `temperature`, `humidity`, `pm25`, and `co`.
Read each metric's `unit`. VOC and NOx are indices, not gas concentrations.
The flat metric map retains the last reading for a repeated measurement channel.
Use `details.zone.sensor_readings` when you need readings attributed to sensors.
Failed sensors are currently absent from `components`; absence is not health.
`last_error` currently contains the first active alert, not necessarily the most
severe. Inspect all `details.zone.active_alerts`.

The API implements no authentication. Use the deployment's configured network
access and base URL. Documentation requires no sensor registry and contains no
node configuration or credentials.

## Reference

Paths below are relative to the service base URL, including any proxy prefix:

- `GET /agent-docs/api-reference`: full Markdown API reference.
- `GET /openapi.json`: generated schemas and route definitions.
- `GET /docs`: Swagger UI.
- `GET /redoc`: ReDoc.
- `GET /llms.txt`: documentation discovery links.

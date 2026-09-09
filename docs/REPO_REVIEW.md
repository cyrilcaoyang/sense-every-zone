# Repository review

Review date: 2026-09-09. Scope: API, registry lifecycle, models, packaging,
and existing tests. Hardware behavior was not validated on a Pi.

## Implemented

- Added packaged Markdown agent guide and API reference endpoints, `/llms.txt`
  discovery, and documented 404/503 response schemas in OpenAPI.
- Corrected startup snapshots to preserve configured sensor counts and use
  `polled_at=0`; zone summaries and status now agree on `unknown` before polling.
- Corrected `/health` returning `ok: true` when a zone has no readings.
- Added HTTP regression coverage and corrected the README's test extras.

## Recommended next changes

1. **Detect stale polling and isolate slow reads.** In `registry.py`, `_poll_loop`
   awaits each zone and `_poll_zone` awaits each sensor without a deadline.
   One stuck read prevents subsequent zones from updating; `api/server.py`
   still constructs responses with a fresh `device_time` and cached healthy
   state. Track last successful sample age, expose stale state, and bound driver
   I/O. Preserve serialization for sensors sharing an I2C bus.
2. **Preserve failed sensor identities.** `SensorRegistry.from_yaml` skips unknown
   or failed driver construction; `_poll_zone` discards read exceptions after
   logging. `_build_status` only includes successful sensors in `components`.
   Retain configured sensor identities and failure details so clients can tell
   missing hardware from healthy reduced configurations.
3. **Rank alerts and populate error details.** `_build_status` breaks after the
   first active alert, even if a later alert is critical. Select the most severe
   error and populate `details.zone.errors`; currently that list is always empty.
4. **Validate configuration before creating hardware.** Reject duplicate zone
   and sensor IDs, nonpositive/nonfinite poll intervals, and malformed structure.
   Duplicate zones currently overwrite each other in the registry dictionary.
   Add cleanup for drivers already created when later configuration fails.
5. **Await shutdown of active reads.** `stop_polling` cancels the asyncio task
   without awaiting it; `close` immediately releases hardware while an executor
   read may still be running. Introduce an asynchronous shutdown sequence and
   reset uptime at application startup rather than module import.
6. **Make flat metric selection explicit.** Multiple sensors with the same
   channel overwrite earlier metrics in `_build_status`. Define a preferred
   sensor or aggregation policy and use each reading's acquisition timestamp;
   retain per-sensor data for traceability.
7. **Check distribution builds in CI.** `pyproject.toml` references a missing
   `LICENSE`, and the private/shared contract source is configured specifically
   for uv while the quick start uses pip. Verify a clean install and wheel
   contents, including documentation, under the intended deployment installer.

The API reference documents current limitations rather than claiming these
follow-up changes are already implemented.

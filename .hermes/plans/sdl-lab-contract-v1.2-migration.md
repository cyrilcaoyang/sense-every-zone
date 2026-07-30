# Migration Plan — STATUS_SPEC v1.0/v1.1 → sdl-lab-contract v1.2

**Date**: 2026-07-30
**Target package**: `sdl-lab-contract` @ `v1.2.0` (git source)
**Reference migrations**: `agilent_plateloc` (first, clean), `sense-every-zone` (this repo, 2026-07-29), `bambu-server`, `torry-pines-shaker`
**Fleet coordinator**: `ac-organic-lab/equipment.yaml`

## Scope: 6 device repos

All six currently carry a vendored copy of the v1.0/v1.1 STATUS_SPEC Pydantic
models and pin `protocol: "1.1"` in `equipment.yaml`. After migration each will
depend on `sdl-lab-contract` from git, re-export the contract types from its
`models.py`, and bump to `protocol: "1.2"` (with the v1.2 field renames +
new envelope fields).

| # | Repo | equipment.yaml id | kind | Current protocol | Notes |
|---|------|-------------------|------|------------------|-------|
| 1 | `xarm-translocation` | `xarm_translocation` | robot_arm | 1.1 | claim/heartbeat/release already wired (advisory) |
| 2 | `fume-hood-sash-automation` | `fume_hood_actuator` | fume_hood | 1.1 | |
| 3 | `opentrons-server` | `ot2_hte`, `ot2_complexation` | liquid_handler | 1.1 | one repo serves two instances |
| 4 | `dose_every_well` | `dose_every_well` | solid_doser | 1.1 | models.py is v1.0-shape but pinned 1.1 |
| 5 | `filter-every-well` | `filter_every_well` | press | 1.1 | |
| 6 | `agilent-cytation-server` | `cytation_5` | plate_reader | 1.1 | claim/heartbeat/release wired |

Out of scope this round (still on 1.0/1.1, migrate later): `agilent-hplcms-server`,
`kasa_tapo_services`, `dobot-MG400-server`, `pypoe`, `AnaliticaDB`, the
`ac-organic-lab` dashboard's own `/status`. Already on 1.2 (no work):
`agilent_plateloc`, `sense-every-zone`, `bambu-server`, `torry-pines-shaker`.

## Common migration pattern (applies to all 6)

The full per-file checklist with code patterns lives in the
`sdl-lab-contract-migration` skill (`references/migration-checklist.md`).
Summary:

1. **pyproject.toml**
   - Add `"sdl-lab-contract"` to `[project].dependencies`.
   - Add `[tool.uv.sources]`:
     `sdl-lab-contract = { git = "https://github.com/AccelerationConsortium/sdl-lab-contract", tag = "v1.2.0" }`
   - Update `description` to mention `STATUS_SPEC v1.2`.
   - Bump `requires-python` to `>=3.10` (sdl-lab-contract floor).
2. **models.py** — replace vendored `ComponentStatus`, `MetricValue`,
   `ErrorInfo`, `ErrorSeverity`, `EquipmentKind`, `EquipmentState`,
   `EquipmentStatus`, `ProbeResponse`, `HealthResponse`, `Activity`,
   `ClaimedBy`, `ClaimRequest`, `ClaimResponse`, `ClaimRejection` with
   `from sdl_lab_contract import …` and re-export. Set
   `PROTOCOL_VERSION = "1.2"`. Keep device-specific detail models local
   (typed `BaseModel`s that go inside the `details` dict). If the device has
   a richer health payload, alias the local richer model as `HealthResponse`
   and re-export the spec one as `SpecHealthResponse`.
3. **server.py** — `EquipmentStatus(...)` constructor field renames:
   - `state=` → `equipment_status=`
   - `kind=` → `equipment_kind=`
   - `timestamp=` → `device_time=`
   - `errors=[...]` → `last_error=<single most severe>` (full list goes into
     the device-specific details model as `errors: List[ErrorInfo]`)
   - `details=<typed model>` → `details={…: typed.model_dump(mode="json")}`
   - Add `protocol_version=PROTOCOL_VERSION` (contract defaults to `"1.0"`)
   - Add `activity=` / `activity_since=` (use `"idle"` for passive monitors,
     `"unknown"` until first poll, real values for active devices)
   - Add `host=socket.gethostname()`, `uptime_seconds=time.monotonic() - start`,
     `allowed_actions=[...]` (empty list for read-only).
4. **ProbeResponse** — v1.2 requires `equipment_id` + `equipment_name`
   (drops v1.0 `service`/`kind`). MUST pass `protocol_version=PROTOCOL_VERSION`
   explicitly — the contract defaults to `"1.0"` and that's the #1 migration bug.
5. **HealthResponse** — spec is now just `{status: "healthy"}`. Keep the
   richer local model (per-subsystem deps) and alias as `HealthResponse` so
   imports keep working.
6. **Every `ErrorInfo(...)`** — v1.2 requires `timestamp=`. The v1.0 models
   did not.
7. **Tests** — update field-name assertions (`s.equipment_status`, not
   `s.state`); add tests for `activity == "unknown"` default and
   `PROTOCOL_VERSION == "1.2"`; document the contract's intentional
   `ProbeResponse.protocol_version == "1.0"` default.
8. **README** — bump version references from v1.0/v1.1 to v1.2.
9. **equipment.yaml** — flip `protocol: "1.1"` → `protocol: "1.2"` for the
   affected entries (only `adapter: http` entries; mock entries have no
   `protocol` field).
10. **Verify** — `uv sync && uv run pytest -q`. All tests must pass. Then
    deploy, restart the service, hit `GET /` and `GET /status` to confirm
    `protocol_version: "1.2"` on the wire.

## Pitfalls (apply to every repo)

- **`ProbeResponse.protocol_version` defaults to `"1.0"`** in the contract
  package by design (honest reading of an unstated version). Pass it
  explicitly in both `ProbeResponse(...)` and `EquipmentStatus(...)`.
- **`ErrorInfo.timestamp` is required** in v1.2 (was absent in v1.0).
- **`details` must be a `dict[str, Any]`**, not a typed model. Use
  `.model_dump(mode="json")` (not plain `.model_dump()`) so datetimes
  serialize to ISO strings.
- **Don't touch drivers/registries** — those use local dataclasses
  (`RawReading`, `ZoneSnapshot`), not contract types.
- **`requires-python` floor** is `>=3.10` because sdl-lab-contract requires
  it. `xarm-translocation` and `dose_every_well` are on `>=3.8` and must bump.
- **`equipment.yaml` mock entries** (e.g. `env_*` sensors) have no `protocol`
  field — don't add one. Only flip `adapter: http` entries.

---

## Per-repo plans

### 1. `xarm-translocation` → v1.2

**Path**: `/Users/macbook_m2/Projects/xarm-translocation`
**Vendored copy**: `src/core/models.py` (header says "lab status spec v1.1")
**Server**: `src/web/server.py`
**equipment.yaml entry**: `xarm_translocation` (`protocol: "1.1"`)
**Current Python floor**: `>=3.8` — must bump to `>=3.10`.

Device-specific concerns:
- Already wires the v1.1 claim protocol (`POST /control/claim`,
  `/heartbeat`, `/release`) in advisory mode. v1.2 keeps these endpoints
  unchanged — the migration is wire-format only.
- Robot arm is an active device, not a passive monitor — populate `activity`
  from real state: `"busy"` while a motion graph is executing, `"idle"`
  otherwise. `activity_since` = start of current motion or last motion end.
- `allowed_actions` is already populated from the motion-graph node's
  outgoing edges — keep that logic, just route it into the v1.2 envelope
  field (same name).
- `details.claimed_by` — keep populating from the active claim; the v1.2
  contract also has a top-level `ClaimedBy` model if you want to lift it.

Steps:
1. Bump `requires-python = ">=3.10"` in pyproject.toml.
2. Add `sdl-lab-contract` dep + `[tool.uv.sources]` git pin.
3. Replace `src/core/models.py` vendored types with imports/re-exports.
   Keep any xarm-specific detail models (e.g. motion-graph state, track
   position) as local `BaseModel`s.
4. Update `src/web/server.py`:
   - `EquipmentStatus(protocol_version=PROTOCOL_VERSION, …)` with
     `equipment_kind="robot_arm"`, `equipment_status=…`, `device_time=…`.
   - Replace `errors=[ErrorInfo(...), ...]` with `last_error=<most severe>`
     plus stuffing the full list into the device details model.
   - Set `activity` / `activity_since` from motion-graph state.
   - Add `host`, `uptime_seconds`, `allowed_actions` (already computed).
5. Update probe endpoint to return
   `ProbeResponse(equipment_id="xarm_translocation", equipment_name="UFactory xArm5", protocol_version=PROTOCOL_VERSION)`.
6. Sweep for `ErrorInfo(...)` constructors and add `timestamp=ts` (v1.2
   requirement).
7. Update tests — field renames, `activity` default, `PROTOCOL_VERSION`.
8. Bump README to v1.2.
9. equipment.yaml: `protocol: "1.1"` → `"1.2"` for `xarm_translocation`.
10. `uv sync && uv run pytest -q`, deploy, restart, curl `/` and `/status`.

### 2. `fume-hood-sash-automation` → v1.2

**Path**: `/Users/macbook_m2/Projects/fume-hood-sash-automation`
**Vendored copy**: `src/hood_sash_automation/api/models.py`
**Server**: same package (FastAPI app; locate via `find src -name "server.py" -o -name "app.py" -o -name "main.py"`)
**equipment.yaml entry**: `fume_hood_actuator` (`protocol: "1.1"`)
**Python floor**: `>=3.10` — OK.

Device-specific concerns:
- Active device (sash actuator). `activity` should be `"busy"` while the
  sash is moving, `"idle"` when at rest, `"unknown"` only before first poll.
- Sash position / target / in-motion flag belong in the device details model.

Steps:
1. Add `sdl-lab-contract` dep + git source.
2. Replace vendored contract types in `api/models.py` with imports/re-exports.
   Keep `SashDetails` (or equivalent) local.
3. Update server: `EquipmentStatus(...)` v1.2 constructor with
   `equipment_kind="fume_hood"`, `activity` from sash motion state,
   `allowed_actions=["open", "close", "stop", "move_to"]` (or whatever the
   control surface actually exposes).
4. Probe endpoint → `equipment_id="fume_hood_actuator"`,
   `equipment_name="Fume Hood Actuator"`, explicit `protocol_version`.
5. Add `timestamp=` to every `ErrorInfo(...)`.
6. Tests, README, equipment.yaml (`fume_hood_actuator` → `"1.2"`).
7. Verify.

### 3. `opentrons-server` → v1.2

**Path**: `/Users/macbook_m2/Projects/opentrons-server`
**Vendored copy**: `src/opentrons_server/gateway/models.py`
**Server**: OT-2 gateway FastAPI app (one process per robot)
**equipment.yaml entries**: `ot2_hte` AND `ot2_complexation` — **both flip to
`"1.2"` together** (one repo serves both instances).
**Python floor**: `>=3.10` — OK.

Device-specific concerns:
- **Multi-instance**: one repo, two deployments (ports 8020 and 8021).
  `equipment_id`/`equipment_name` must come from instance config (env var or
  yaml), not hardcoded — otherwise both gateways will report the same
  identity and the dashboard will confuse them.
- The gateway builds `/status` from an SSH snapshot of the OT-2 — activity
  should reflect the last known run state from the robot (`"busy"` while a
  protocol is running, `"idle"` otherwise, `"unknown"` if SSH unreachable).
- `allowed_actions` should reflect the gateway's control surface
  (`run.submit`, `run.abort`, etc.).

Steps:
1. Add `sdl-lab-contract` dep + git source.
2. Replace vendored contract types in `gateway/models.py` with imports /
   re-exports. Keep OT-2-specific detail models (run state, deck layout,
   pipette info) local.
3. Update server: v1.2 `EquipmentStatus(...)` constructor,
   `equipment_kind="liquid_handler"`, `activity` from OT-2 run state,
   `host`/`uptime_seconds`/`allowed_actions`.
4. Probe endpoint: read `equipment_id` and `equipment_name` from instance
   config (e.g. `OT2_INSTANCE_ID=ot2_hte`). Pass `protocol_version`
   explicitly.
5. Add `timestamp=` to all `ErrorInfo(...)`.
6. Tests, README, equipment.yaml — flip BOTH `ot2_hte` and
   `ot2_complexation` to `"1.2"` together when both gateway instances are
   deployed.
7. Deploy to port 8020, verify, then 8021.

### 4. `dose_every_well` → v1.2

**Path**: `/Users/macbook_m2/Projects/dose_every_well`
**Vendored copy**: `src/dose_every_well/api/models.py` (header says "v1.0"
but `PROTOCOL_VERSION = "1.1"` — the file drifted; the migration cleans
this up)
**Server**: `src/dose_every_well/api/server.py`
**equipment.yaml entry**: `dose_every_well` (`protocol: "1.1"`)
**Python floor**: `>=3.8` — must bump to `>=3.10`.

Device-specific concerns:
- Runs on a Raspberry Pi (minicnc). Python floor bump is safe — deployed
  Pi OS already has 3.10+.
- Active device (weighing + dosing). `activity` should be `"busy"` while a
  dose cycle is running, `"idle"` otherwise.
- Richest local detail model of the fleet (per-well dosing results, tare
  state, plate type, lid state) — keep all of it as a local
  `DoseEveryWellDetails` and dump into `details` dict.

Steps:
1. Bump `requires-python = ">=3.10"`.
2. Add `sdl-lab-contract` dep + git source.
3. Replace vendored contract types with imports/re-exports. Keep
   `DoseEveryWellDetails` (and per-well / lifecycle sub-models) local.
4. Update server: v1.2 constructor, `equipment_kind="solid_doser"`,
   `activity` from dosing lifecycle, `allowed_actions` from the
   tare/dose/lid/plate control surface.
5. Probe endpoint → `equipment_id="dose_every_well"`,
   `equipment_name="Dose Every Well"`, explicit `protocol_version`.
6. Add `timestamp=` to all `ErrorInfo(...)`.
7. Tests, README, equipment.yaml (`dose_every_well` → `"1.2"`).
8. Verify.

### 5. `filter-every-well` → v1.2

**Path**: `/Users/macbook_m2/Projects/filter-every-well`
**Vendored copy**: `src/filter_every_well/models.py`
**Server**: locate FastAPI entry (likely `src/filter_every_well/server.py`
or `api/server.py` — confirm with `find`)
**equipment.yaml entry**: `filter_every_well` (`protocol: "1.1"`)
**Python floor**: `>=3.9` — must bump to `>=3.10`. Also fix the placeholder
`{ name = "Your Name", email = "you@example.com" }` author while you're
in there.

Device-specific concerns:
- Active device (Waters Positive Pressure-96 Processor). `activity` should
  be `"busy"` during a press cycle, `"idle"` otherwise.
- The pressure / plate-state / cycle-count data goes in a local
  `FilterDetails` model.

Steps:
1. Bump `requires-python = ">=3.10"`.
2. Add `sdl-lab-contract` dep + git source.
3. Replace vendored contract types in `models.py` with imports/re-exports.
   Keep `FilterDetails` local.
4. Update server: v1.2 constructor, `equipment_kind="press"`, `activity`
   from press-cycle state, `allowed_actions` from control surface.
5. Probe endpoint → `equipment_id="filter_every_well"`,
   `equipment_name="Waters Filtration"`, explicit `protocol_version`.
6. Add `timestamp=` to all `ErrorInfo(...)`.
7. Tests, README, equipment.yaml (`filter_every_well` → `"1.2"`).
8. Verify.

### 6. `agilent-cytation-server` → v1.2

**Path**: `/Users/macbook_m2/Projects/agilent-cytation-server`
**Vendored copy**: `src/agilent_cytation_server/models.py`
**Server**: same package (FastAPI app)
**equipment.yaml entry**: `cytation_5` (`protocol: "1.1"`)
**Python floor**: `>=3.10` — OK.

Device-specific concerns:
- Already wires the v1.1 claim protocol plus `/control/*` for drawer, plate
  load/unload, reads, imaging. v1.2 keeps the claim endpoints unchanged.
- Plate reader is mostly passive when idle, active during a read —
  `activity` should be `"busy"` while a read/imaging run is in progress,
  `"idle"` otherwise.
- `details.claimed_by` already populated while a claim is held — keep.
- Reads are the long-running operation: `activity_since` = read start time.

Steps:
1. Add `sdl-lab-contract` dep + git source.
2. Replace vendored contract types in `models.py` with imports/re-exports.
   Keep Cytation-specific detail models (read state, drawer state, plate
   carrier info, imaging config) local.
3. Update server: v1.2 constructor, `equipment_kind="plate_reader"`,
   `activity` from read/imaging state, `allowed_actions` from current
   state machine (already populated — keep).
4. Probe endpoint → `equipment_id="cytation_5"`,
   `equipment_name="BioTek Cytation 5"`, explicit `protocol_version`.
5. Add `timestamp=` to all `ErrorInfo(...)`.
6. Tests, README, equipment.yaml (`cytation_5` → `"1.2"`).
7. Verify.

---

## Suggested execution order

Order by risk / fleet impact — lowest first:

1. **`filter-every-well`** — smallest, no claim protocol, easy rollback.
2. **`fume-hood-sash-automation`** — small, single endpoint, low traffic.
3. **`dose_every_well`** — bigger detail model but well-tested.
4. **`agilent-cytation-server`** — claim protocol already wired, mechanical migration.
5. **`opentrons-server`** — multi-instance; deploy to one gateway first, verify, then the other.
6. **`xarm-translocation`** — most safety-critical (moving robot arm). Migrate
   last, with the claim protocol still in advisory mode, and consider
   scheduling during a maintenance window.

After all six are deployed and stable, do a single `equipment.yaml` PR that
flips all six `protocol` fields together — that keeps the dashboard's
claim-dance logic coherent across the fleet.

## Follow-ups (out of scope here)

- `agilent-hplcms-server`, `kasa_tapo_services`, `dobot-MG400-server`,
  `pypoe`, `AnaliticaDB`, `ac-organic-lab` dashboard `/status` — schedule
  the next migration batch.
- The `env_*` entries in equipment.yaml are `adapter: mock` — flip to
  `adapter: http` + `protocol: "1.2"` only when each sense-every-zone
  instance is deployed to its Pi.

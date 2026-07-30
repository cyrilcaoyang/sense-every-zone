# sdl-lab-contract v1.2 Migration Plan — 5 Device Repos

Reference contract: `~/Projects/sdl-lab-contract/src/sdl_lab_contract/models.py` (v1.2.0).
Already migrated: `agilent_plateloc`, `sense-every-zone`.
Migration skill: `sdl-lab-contract-migration` (loaded, followed).

---

## Common Steps (apply to all 5 repos)

1. **pyproject.toml**
   - Add `"sdl-lab-contract"` to `[project] dependencies`.
   - Add `[tool.uv.sources]` pin:
     ```toml
     [tool.uv.sources]
     sdl-lab-contract = { git = "https://github.com/AccelerationConsortium/sdl-lab-contract", tag = "v1.2.0" }
     ```
   - Update `description` to say `STATUS_SPEC v1.2`.
   - Bump `requires-python` to `>=3.10` (pypoe and xarm-translocation are on `>=3.8` and must bump).

2. **models.py**
   - Delete vendored copies of: `EquipmentKind`, `EquipmentState`, `ErrorSeverity`, `ComponentStatus`, `MetricValue`, `ErrorInfo`, `EquipmentStatus`, `ProbeResponse`, `HealthResponse`, `ClaimedBy`, `ClaimRequest`, `ClaimResponse`, `ClaimRejection`.
   - Import them from `sdl_lab_contract` (and `sdl_lab_contract.claims` for the claim types).
   - Keep device-specific models locally (MoveRequest, CameraDetails, LoadedPlate, DeckState, etc.).
   - Set `PROTOCOL_VERSION = "1.2"`.
   - Re-export via `__all__`.

3. **server / api / status_builder**
   - Every `EquipmentStatus(...)` and `ProbeResponse(...)` MUST pass `protocol_version=PROTOCOL_VERSION` explicitly. The contract package defaults the field to `"1.0"` (honest reading of silent devices); omitting it is the #1 migration bug.
   - Add v1.2 fields to `EquipmentStatus`: `activity` (`"idle"` for passive/ready devices, `"running"` when busy, `"unknown"` when not yet polled), `activity_since`, `host` (if not already set), `uptime_seconds`, `allowed_actions`.
   - v1.0/v1.1 field renames (only pypoe's raw-dict path needs these; the four Pydantic repos already use v1.1 names): `state`→`equipment_status`, `kind`→`equipment_kind`, `timestamp`→`device_time`, `errors`→`last_error` (single).

4. **Tests**
   - Update `protocol_version` assertions from `"1.0"`/`"1.1"` to `"1.2"`.
   - Add `activity` default test (`"unknown"` for un-polled devices, `"idle"` for ready devices).
   - Add explicit test that `ProbeResponse()` defaults to `"1.0"` (documents contract behavior).

5. **Verify**
   ```bash
   cd <repo> && uv sync  # or: pip install -e ".[dev]"
   uv run pytest -q
   ```

---

## Repo 1: fume-hood-sash-automation

**Risk: LOW** — already on v1.1 with Pydantic models, `ErrorInfo.timestamp` already present, `ClaimedBy` already spec-shaped.

### pyproject.toml
- Add `sdl-lab-contract` to `dependencies`.
- Add `[tool.uv.sources]` git pin.
- Update description: `Conforms to STATUS_SPEC v1.1.` → `Conforms to STATUS_SPEC v1.2.`
- `requires-python` already `>=3.10` — no change.

### src/hood_sash_automation/api/models.py
Current state (v1.1 vendored): extends `EquipmentKind` with `shaker`, `camera`, `smart_plug`, `power_strip` — all four are already in the v1.2 contract, so no local extension needed. `ClaimRequest` has `ge=1.0, le=300.0` constraint; contract version is plain `float = 30.0`. Keep the constraint by subclassing locally (or accept the contract's un-clamped version — device already clamps in `claims.py`).

Steps:
1. Delete lines 19–126 (vendored `EquipmentKind` … `ClaimRejection`).
2. Add:
   ```python
   from sdl_lab_contract import (
       Activity, ComponentStatus, EquipmentKind, EquipmentState, EquipmentStatus,
       ErrorInfo, ErrorSeverity, HealthResponse, MetricValue, ProbeResponse,
   )
   from sdl_lab_contract.claims import ClaimedBy, ClaimRejection, ClaimRequest, ClaimResponse

   PROTOCOL_VERSION = "1.2"

   # Device-specific request bodies stay local.
   class MoveRequest(BaseModel): ...
   ```
3. Keep `MoveRequest` exactly as-is.
4. If the `ttl_s` clamp on `ClaimRequest` is load-bearing for validation tests, keep a local subclass:
   ```python
   class ClaimRequest(ContractClaimRequest):
       ttl_s: float = Field(default=30.0, ge=1.0, le=300.0)
   ```
   Otherwise drop it and let `claims.py` clamp at runtime.

### src/hood_sash_automation/api/status_builder.py
- `build_status()` already passes `protocol_version=PROTOCOL_VERSION` — keep.
- Add `activity` and `activity_since`:
  ```python
  activity = "running" if is_moving else "idle"
  activity_since = datetime.now(timezone.utc)
  ```
  Pass `activity=activity, activity_since=activity_since` to `EquipmentStatus(...)`.
- `host=socket.gethostname()` and `uptime_seconds=time.monotonic() - _PROCESS_START_TIME` already set — keep.

### src/hood_sash_automation/api/api_service.py
- Probe endpoint already passes `protocol_version=PROTOCOL_VERSION` — keep.
- No other changes needed.

### tests/docker-test/tests/test_actuator_api.py
- Line 100: `assert body["protocol_version"] == "1.1"` → `"1.2"`.
- Add test:
  ```python
  def test_status_activity(client):
      body = client.get("/status").json()
      assert body["activity"] in ("idle", "running")
      assert body["activity_since"] is not None
  ```
- Fixture JSON files in `tests/fixtures/*.json` say `"protocol_version": "1.1"` — update all 5 to `"1.2"` and add `"activity": "idle"`/`"running"` as appropriate.

### Gotchas
- `EquipmentKind` extension is unnecessary — v1.2 contract already has all four extra kinds.
- `ClaimRequest` local clamp decision: if tests assert 422 on `ttl_s=999`, keep the subclass.

---

## Repo 2: kasa_tapo_services

**Risk: LOW** — no claims, no `ErrorInfo` usage in routes, models already use modern Pydantic v2 style.

### pyproject.toml
- Add `sdl-lab-contract` to `dependencies`.
- Add `[tool.uv.sources]` git pin.
- Update description: `STATUS_SPEC v1.0` → `STATUS_SPEC v1.2`.
- `requires-python` already `>=3.10` — no change.

### src/kasa_tapo_services/models.py
Current state (v1.0 vendored): `EquipmentKind` already includes `camera`, `smart_plug`, `power_strip` (now in contract). No claims.

Steps:
1. Delete lines 22–112 (vendored `PROTOCOL_VERSION` … `HealthResponse`).
2. Add:
   ```python
   from sdl_lab_contract import (
       Activity, ComponentStatus, EquipmentKind, EquipmentState, EquipmentStatus,
       ErrorInfo, ErrorSeverity, HealthResponse, MetricValue, ProbeResponse,
   )

   PROTOCOL_VERSION = "1.2"
   ```
3. Keep ALL device-specific models exactly as-is: `PtzNudgeRequest`, `PtzContinuousRequest`, `PresetSaveRequest`, `PresetGotoRequest`, `PrivacyRequest`, `StreamingRequest`, `PresetEntry`, `LensEntry`, `SnapshotRequest/Response`, `RecordingStart/Stop/Cancel*`, `RollingStart/Stop*`, `CameraDetails`, `PlugSwitchRequest`, `ControlAck`.
4. Keep `PtzDirection` Literal.
5. Update `__all__` to re-export contract types plus all locals.

### src/kasa_tapo_services/routes/plugs.py
- `_build_status()`:
  - Add `protocol_version=PROTOCOL_VERSION` to both `EquipmentStatus(...)` calls (unreachable path and ready path).
  - Add `activity="unknown"` for unreachable path; `activity="idle"` + `activity_since=device_time` for ready path.
  - `host`, `uptime_seconds`, `allowed_actions` already set on ready path — keep. Unreachable path should also set `allowed_actions=[]`.
- `probe()`:
  - Add `protocol_version=PROTOCOL_VERSION` to `ProbeResponse(...)`.

### src/kasa_tapo_services/routes/cameras.py
- `probe()`:
  - Add `protocol_version=PROTOCOL_VERSION` to `ProbeResponse(...)`.
- `status()` returns cached envelope from poller — the poller's builder must be updated (see below).
- Find the camera `_build_status` (in `routes/cameras.py` or a helper module) and add the same `protocol_version`, `activity`, `activity_since` fields. For cameras: `activity="idle"` when reachable and not recording, `"running"` when actively recording, `"unknown"` when unreachable.

### tests/test_poller.py, test_camera_routes.py, test_models.py
- `test_camera_routes.py` line 15: `assert body["protocol_version"] == "1.0"` → `"1.2"`.
- `test_models.py` line 27: `assert env.protocol_version == "1.0"` → `"1.2"`.
- Add `activity` default test.

### Gotchas
- Two `_build_status` implementations (plugs and cameras) — don't miss the camera one.
- The poller caches envelopes; a stale v1.0 cache survives restart only in-memory, so no migration of persisted state needed.

---

## Repo 3: opentrons-server

**Risk: MEDIUM** — largest device-specific model surface, older `Optional`/`Union` style hints, `EquipmentStatus` has class-level defaults (`equipment_id="ot2"`, etc.) that must be preserved or explicitly passed everywhere.

### pyproject.toml
- Add `sdl-lab-contract` to `dependencies`.
- Add `[tool.uv.sources]` git pin.
- Update description to mention STATUS_SPEC v1.2.
- `requires-python` already `>=3.10` — no change.

### src/opentrons_server/gateway/models.py
Current state (v1.1 vendored): uses `Optional[X]` / `Union[...]` / `Dict` / `List` throughout (older style, but Pydantic v2 handles it fine). `EquipmentStatus` has defaults: `equipment_id="ot2"`, `equipment_name="Opentrons OT-2"`, `equipment_kind="liquid_handler"` — **the contract version has NO defaults on these fields**. Every constructor must pass them explicitly (service.py already does).

Steps:
1. Delete lines 11–112 (vendored `PROTOCOL_VERSION` … `ClaimRejection`).
2. Add:
   ```python
   from sdl_lab_contract import (
       Activity, ComponentStatus, EquipmentKind, EquipmentState, EquipmentStatus,
       ErrorInfo, ErrorSeverity, HealthResponse, MetricValue, ProbeResponse,
   )
   from sdl_lab_contract.claims import ClaimedBy, ClaimRejection, ClaimRequest, ClaimResponse

   PROTOCOL_VERSION = "1.2"
   ```
3. Keep ALL device-specific models: `CommandResponse`, `StartupRequest`, `ProtocolSetupRequest`, `WellLocation`, `CoordinateLocation`, `MoveToRequest`, `LiquidMoveRequest`, `TipRequest`, `TipsResetRequest`, `TipRackState`, `MoveLabwareRequest`, `LightsRequest`, `WellSample`, `LoadedPlate`, `PlateLoadRequest`, `LabwareKind`, `SlotState`, `DeckSource`, `SlotLabware`, `SlotModule`, `DeckSlot`, `DeckState`, `DeckDeclareRequest`, `WellUpdateRequest`.
4. Consider modernizing `Optional[X]` → `X | None` in the kept models as a cleanup, but it's NOT required for the migration.

### src/opentrons_server/gateway/service.py
- `get_status()` (line 970):
  - Add `protocol_version=PROTOCOL_VERSION` to `EquipmentStatus(...)`.
  - Add `activity` / `activity_since`:
    ```python
    activity_map = {
        OT2ServiceState.READY: "idle",
        OT2ServiceState.BUSY: "running",
        OT2ServiceState.PAUSED: "running",
        OT2ServiceState.EXTERNAL_CONTROL: "running",
        OT2ServiceState.DRY_RUN: "idle",
    }
    activity = activity_map.get(self.state, "unknown")
    activity_since = now  # or track last state-change timestamp
    ```
  - `equipment_id`, `equipment_name`, `equipment_kind` already passed explicitly — keep.
  - `host` is not currently set — add `host=socket.gethostname()`.
- `ErrorInfo` usage: `last_error` is already a single `ErrorInfo` — check any constructors pass `timestamp=` (contract requires it). Search for `ErrorInfo(` and add `timestamp=datetime.now(timezone.utc)` where missing.

### src/opentrons_server/gateway/api.py
- `probe()` already passes `protocol_version=PROTOCOL_VERSION` — keep.
- No other changes.

### Tests
- `test_deck_status.py`, `test_deck_declare.py`, `test_gateway_service.py`: fixture JSON files with `"protocol_version": "1.1"` → update to `"1.2"` and add `"activity"` field.
- Add `activity` presence tests.
- `test_gateway_tips.py` asserts `last_error is None` — should still pass.

### Gotchas
- **Class-default trap**: the vendored `EquipmentStatus` defaults `equipment_id="ot2"` etc. The contract version requires them. If any code constructs `EquipmentStatus()` with no args (unlikely, but grep to confirm), it will break.
- **Optional/Union style**: no functional issue, but be careful not to break imports if you modernize.
- Fixture files: `tests/unit/fixtures/*.json` all carry `"protocol_version": "1.1"` — bulk update.

---

## Repo 4: pypoe

**Risk: HIGH** — no models.py; status is built as raw dicts. Two valid strategies.

### pyproject.toml
- Add `sdl-lab-contract` to the `web-ui` optional-dependencies list (NOT the core deps — the contract is only needed by the web interface):
  ```toml
  web-ui = [
      "fastapi>=0.104.0",
      ...
      "sdl-lab-contract",
  ]
  ```
- Add `[tool.uv.sources]` git pin.
- **Bump `requires-python` from `>=3.8` to `>=3.10`** (contract requires 3.10+).
- Update classifiers: drop `Programming Language :: Python :: 3.8` and `3.9`.
- Update description to mention STATUS_SPEC v1.2.

### Strategy A (recommended): use the real Pydantic models
In `src/pypoe/interfaces/web/app.py`:
1. Import:
   ```python
   from sdl_lab_contract import EquipmentStatus, ProbeResponse, ErrorInfo, ComponentStatus, MetricValue
   from sdl_lab_contract.claims import ClaimRequest as ContractClaimRequest, ClaimedBy, ClaimResponse, ClaimRejection
   PROTOCOL_VERSION = "1.2"
   ```
2. Replace `_status_payload()` dict construction (line 442) with a real `EquipmentStatus(...)`:
   ```python
   status = EquipmentStatus(
       protocol_version=PROTOCOL_VERSION,
       equipment_id="pypoe_web",
       equipment_name="PyPoe Web UI",
       equipment_kind="other",
       equipment_version="2.7.0",
       host=socket.gethostname(),
       equipment_status=equipment_status,
       activity="idle" if equipment_status == "ready" else "unknown",
       activity_since=device_time,
       message=message,
       required_actions=[],
       allowed_actions=[],
       device_time=device_time,
       uptime_seconds=None,
       components={k: ComponentStatus(**v) for k, v in components.items()},
       metrics={k: MetricValue(**v) for k, v in metrics.items()},
       last_error=ErrorInfo(**last_error) if last_error else None,
       details=details,
   )
   payload = status.model_dump(mode="json")
   ```
3. Replace `_probe_payload()` with `ProbeResponse(equipment_id=..., equipment_name=..., protocol_version=PROTOCOL_VERSION).model_dump(mode="json")`.
4. Replace the local `ClaimRequest(BaseModel)` class with the contract import (the endpoint's `request: ClaimRequest` will then use the contract shape — same fields, so no behavioral change).

### Strategy B (minimal diff): keep raw dicts, update strings
If you want the smallest possible change:
1. Update `"protocol_version": "1.1"` → `"1.2"` in `_probe_payload()` (line 271) and `_status_payload()` (line 443).
2. Add `"activity": "idle"` (or `"unknown"`) and `"activity_since": device_time.isoformat()` to the payload dict.
3. No new dependency needed.

**Recommendation**: Strategy A. It's ~30 lines changed, gives you validation for free, and prevents future drift. The dict-construction code is already a maintenance hazard (e.g. `_component()` returns a dict with `last_event_at: None` — works, but brittle).

### Gotchas
- **requires-python bump is mandatory** — contract requires 3.10.
- The `ClaimRequest` in app.py is a local class; the endpoint at line 500 uses it. Replacing with contract import is safe (same field names).
- No test directory exists at repo root — tests live in `src/pypoe/tests/` and don't cover the status endpoint. Manual verification: `curl localhost:8000/status | jq .protocol_version` should say `"1.2"`.
- The status cache (`self._status_cache`) stores the dict — if you switch to Strategy A, cache the dumped dict, not the model instance.

---

## Repo 5: xarm-translocation

**Risk: MEDIUM** — clean v1.1 Pydantic models, but `requires-python >=3.8` needs a bump, and the `ClaimedBy` construction in `claims.py` goes through a dict (`to_claimed_by_dict()`) which is fine, but the claim protocol is deeply wired.

### pyproject.toml
- Add `sdl-lab-contract` to `dependencies`.
- Add `[tool.uv.sources]` git pin.
- Update description to mention STATUS_SPEC v1.2.
- **Bump `requires-python` from `>=3.8` to `>=3.10`**.
- Update classifiers: drop `Programming Language :: Python :: 3.8` and `3.9`.
- Note: `xarm-python-sdk>=1.13.0` — verify it supports 3.10+ (it does; deployed venvs already run newer Python).

### src/core/models.py
Steps:
1. Delete lines 29–166 (vendored `PROTOCOL_VERSION` … `ClaimRejection`).
2. Add:
   ```python
   from sdl_lab_contract import (
       Activity, ComponentStatus, EquipmentKind, EquipmentState, EquipmentStatus,
       ErrorInfo, ErrorSeverity, HealthResponse, MetricValue, ProbeResponse,
   )
   from sdl_lab_contract.claims import ClaimedBy, ClaimRejection, ClaimRequest, ClaimResponse

   PROTOCOL_VERSION = "1.2"
   ```
3. `ClaimRequest` has `ge=1.0, le=300.0` — the contract version doesn't clamp. Either keep a local subclass with the constraint (recommended; `claims.py` has `MIN_TTL_S`/`MAX_TTL_S` constants that mirror these) or drop it.
4. `EquipmentKind` here does NOT include `shaker`/`camera`/etc. — the contract's superset is a strict upgrade, no issue.

### src/core/status_builder.py
- `_disconnected_envelope()` and `build_status()` both already pass `protocol_version=PROTOCOL_VERSION` — keep.
- Add `activity` / `activity_since`:
  ```python
  # In build_status(), after determining equipment_status:
  if equipment_status == "busy":
      activity = "running"
  elif equipment_status in ("ready", "degraded", "dry_run"):
      activity = "idle"
  else:
      activity = "unknown"
  activity_since = datetime.now(timezone.utc)
  ```
  Pass `activity=activity, activity_since=activity_since` to both `EquipmentStatus(...)` constructors.
- `host`, `uptime_seconds` already set — keep.
- `ErrorInfo` constructor at line 156 already passes `timestamp=` — good.

### src/core/xarm_api_server.py
- `probe()` (line 966) already passes `protocol_version=PROTOCOL_VERSION` — keep.
- No other changes.

### Tests
- `test/test_claims_api.py` lines 274, 280: `"1.1"` → `"1.2"`.
- `test/test_status_envelope.py`: uses `PROTOCOL_VERSION` constant — passes automatically once the constant is `"1.2"`. Add `activity` assertions.
- `test/test_xarm_api_server.py` line 65: uses `PROTOCOL_VERSION` constant — passes automatically.
- Add `test_activity_defaults_unknown` and `test_activity_idle_when_ready` in `test_status_envelope.py`.

### Gotchas
- **requires-python bump** is mandatory.
- `claims.py` `ClaimRecord.to_claimed_by_dict()` returns a dict that gets validated into the contract `ClaimedBy` when embedded in `details` — shapes match (`session_id`, `owner`, `expires_at`), no change needed.
- `ClaimRequest` clamp decision: keep the local subclass if any test asserts 422 on out-of-range `ttl_s`.

---

## Risk Summary

| Repo | Risk | Why |
|------|------|-----|
| fume-hood-sash-automation | **LOW** | v1.1 Pydantic, claims already spec-shaped, extended kinds already in contract |
| kasa_tapo_services | **LOW** | No claims, v1.0→v1.2 but models already modern, extended kinds already in contract |
| opentrons-server | **MEDIUM** | Large device-model surface, class-level defaults on EquipmentStatus, fixture JSONs to update |
| pypoe | **HIGH** | Raw dict construction (no models.py), requires-python 3.8→3.10, no existing status tests |
| xarm-translocation | **MEDIUM** | Clean models but requires-python 3.8→3.10, claim protocol deeply wired, large API surface |

## Suggested Migration Order
1. **fume-hood-sash-automation** (easiest, builds confidence)
2. **kasa_tapo_services** (no claims, simple)
3. **xarm-translocation** (claims + python bump)
4. **opentrons-server** (largest model surface)
5. **pypoe** (unique raw-dict migration, highest risk, do last)

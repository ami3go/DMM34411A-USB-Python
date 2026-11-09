# DMM34411A-NVM-BUFFER-001 — Buffered measurement acquisition, NVM persistence and retrieval

**Priority:** P1 — acquisition integrity and persistent measurement evidence  
**Repository:** https://github.com/ami3go/DMM34411A-USB-Python  
**Base:** `main` at v0.1.0, using `scpi-driver-core` v0.1.0.dev12 (pinned Git SHA)  
**Task status:** SPECIFIED, **NOT IMPLEMENTED**. This PR records the design and implementation work order; it contains no new acquisition feature.  
**Hardware:** Keysight/Agilent 34411A. 34410A/L4411A behavior is informative but must not be assumed without model-specific qualification.  
**Release target for implementation:** v0.2.0 (separate implementation PR; bump code and package versions together).

## 1. Mission

Implement a complete, auditable workflow for **capture into the instrument's volatile reading store**, **safe copy to nonvolatile memory (NVMEM)**, **non-destructive inspection/retrieval**, and **explicitly requested destructive reads/erase** using the existing `dmm34411a` package and `scpi-driver-core`. Add a traceable host export path so offline results can be retained even when instrument memory is overwritten.

Implement sequentially, with unit/integration tests, PR review, CI and separate operator-authorized HIL evidence. **Do not merge code claiming HIL qualification without evidence.** Keep the legacy `DMM_34411A` methods and their string return values unchanged. New batch APIs may return typed numeric values.

## 2. Verified device capabilities and important distinctions

| Property / command | 34411A behavior / design consequence | Evidence |
| --- | --- | --- |
| `RDG_STORE` volatile reading memory | Up to **1,000,000** readings; lost at power-off. Hardware capture is distinct from NVM logging. | Keysight datasheet (below) |
| `NVMEM` nonvolatile reading storage | Up to **50,000** readings; retained across power cycling. Never use the 1-million figure as its limit. | Keysight datasheet and user guide |
| `DATA:POINts? RDG_STORE` / `DATA:POINts? NVMEM` | Inspect volatile and persistent counts separately; validate syntax/return format in HIL. | Keysight SCPI comparison and quick reference |
| `DATA:COPY NVMEM, RDG_STORE` | Supported command to copy captured readings to NVM. **Overwrite, append, truncation and busy-state behavior require verification against the Programmer's Reference and HIL** before write policy is finalized. | Keysight SCPI quick reference |
| `DATA:DATA? NVMEM` | Read all NVM measurements; potentially large reply. Do not confuse with `FETCh?`. | Keysight user guide |
| `DATA:DELete NVMEM` | Destructive NVM deletion; only from an explicit confirmation-bearing API. | Keysight user guide |
| `DATA:REMove? <num_readings>` | Supported volatile-store retrieval primitive; **verify precise consumption/ordering rules in HIL**. | Keysight SCPI quick reference |
| `FETCh?` and `R? [<max_count>]` | Supported, but *do not assume* identical side effects or automatic completion. Determine exact scope and retention semantics from Programmer's Reference before exposing a convenience API. | Keysight quick reference |
| `INITiate`, `ABORt`, `SAMPle:COUNt`, `SAMPle:SOURce`, `SAMPle:TIMer`, `TRIGger:COUNt`, `TRIGger:SOURce`, `*TRG` | Supported building blocks for timed, immediate, external, and bus-trigger capture. Validate legal combinations per measurement function and firmware. | Keysight quick reference |

**Source of truth (official Keysight):**
1. [34410A/34411A Data Sheet](https://www.keysight.com/us/en/assets/7018-01326/data-sheets/5989-3738.pdf) — volatile memory 1,000,000 and NVM 50,000 for 34411A; speed and triggering.
2. [34410A/11A/L4411A User's Guide](https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf), pp. 50, 80–81 — FIFO and NVM data logging, power-cycle retention, memory commands and front-panel logger behavior.
3. [34410A/11A Command Quick Reference](https://www.keysight.com/us/en/assets/9018-61141/programming-guides/9018-61141.pdf), Reading Memory and Measurement Configuration sections — exact documented command names.
4. [34410A/11A Programmer's Reference Help ZIP](https://www.keysight.com/hk/en/assets/9018-83366/help-files/9018-83366.zip) — required for command side effects, limits, return formats, copy behavior and error codes before implementing destructive operations.
5. [Keysight SCPI Comparison Guide](https://www.keysight.com/us/en/assets/7018-02044/white-papers-archived/5990-3515.pdf), DATA subsystem — model support matrix.

**Qualification caveat:** The User's Guide contains potentially confusing wording about whether `FETCh?`/`R?` act on nonvolatile or volatile memory. Do **not** infer destructive behavior from that wording alone; consult Programmer's Reference and verify on actual 34411A firmware. Keep ambiguous commands out of the initial safe API until confirmed.

## 3. Public Python API — proposed contract

Keep `dmm34411a/driver.py` responsible for connection ownership and legacy methods. Add small model-specific modules at repository root level (do **not** create a new `src/` package layout): `dmm34411a/acquisition.py`, `dmm34411a/memory.py`, `dmm34411a/models.py` as needed. No generic driver-framework DSL.

Expose a single composed interface from `DMM_34411A`: `dmm.acquisition`, optionally plus backward-compatible thin convenience methods on the DMM instance.

```python
from dmm34411a import DMM_34411A
from dmm34411a.models import CaptureConfig

with DMM_34411A(resource_name="USB0::...::INSTR", timeout_s=10.0) as dmm:
    dmm.conf_voltage_dc()  # retain legacy measurement setup
    dmm.acquisition.configure(CaptureConfig(
        sample_count=10000,
        trigger_source="IMM",       # "IMM", "BUS", "EXT"
        sample_interval_s=0.001,    # None means instrument AUTO source
        pretrigger_count=0,
    ))
    dmm.acquisition.initiate()                  # arms/starts, does not block 10 seconds
    dmm.acquisition.wait_complete(timeout_s=30.0)
    n = dmm.acquisition.volatile_count()        # DATA:POINts? RDG_STORE
    dmm.acquisition.copy_to_nvm(overwrite=False)  # explicit write; capacity 50,000
    assert dmm.acquisition.nvm_count() == n
    samples = dmm.acquisition.read_nvm()        # DATA:DATA? NVMEM; non-destructive
    dmm.acquisition.export_csv("capture.csv", samples)
```

All API names and types above are **design targets**, not currently available. Implement tests using the same names or document any review-approved variation.

Required operations:

| API | SCPI | Semantics |
| --- | --- | --- |
| `configure(CaptureConfig)` | `SAMP:COUN`, `SAMP:SOUR`, optional `SAMP:TIM`, `SAMP:COUN:PRET`, `TRIG:SOUR`, `TRIG:COUN` | Finite sample count, validated timing and trigger; no implicit start |
| `initiate()` | `INIT` | Start/arm exactly once; no silent retry |
| `send_bus_trigger()` | `*TRG` | Only allowed for bus-trigger captures; explicit |
| `wait_complete(timeout_s)` | `*OPC?` or bounded instrument-status strategy | Strict wall-clock deadline; report unknown state after transport failure |
| `abort()` | `ABOR` | Explicitly stop the instrument acquisition; document what partial data remains |
| `volatile_count()` | `DATA:POINts? RDG_STORE` | Non-destructive count; zero valid |
| `nvm_count()` | `DATA:POINts? NVMEM` | Non-destructive count |
| `read_volatile()` | `FETCh?` (after exact semantics confirmed) | Non-destructive, bounded response; reject oversized capture before query |
| `drain_volatile(count, chunk_size)` | `DATA:REMove? n` (after precise semantics confirmed) | **Destructive**, explicit, incremental, count-checked; yield chunks |
| `copy_to_nvm(overwrite=False)` | `DATA:COPY NVMEM, RDG_STORE` | Never silently overwrite pre-existing data or exceed 50,000 readings |
| `read_nvm()` | `DATA:DATA? NVMEM` | Non-destructive; verify count unchanged; reply size budget |
| `delete_nvm(confirm=False)` | `DATA:DELete NVMEM` | **Destructive**; require explicit `confirm=True`; verify zero afterward |
| `export_csv(path, readings)` | Host file only | Atomic file creation/replacement policy, metadata sidecar, checksum, reading count; no fabricated device timestamps |

**Response types:** use typed `list[float]` or immutable sequence for small acquisitions, and iterated chunks for large ones. Export raw precision accurately. Distinguish instrument overrange/sentinel values from genuine nonfinite values; reject malformed replies deterministically.

**Metadata:** instrument model/serial/firmware from `*IDN?`, measurement function/range/NPLC/aperture as applicable, trigger/source/interval/count, UTC host acquisition boundary timestamps, core/driver version, VISA address, raw-count and checksum. Instrument sample timestamps **must not be invented**: a generated sample index or nominal time axis may be labeled *nominal/inferred* only.

## 4. Validations and state machine

- Validate integer sample count **1…1,000,000** for a 34411A one-shot capture. Reject bool, fractional, negative, zero, NaN and overflow. Separate NVM copy limit **1…50,000**.
- Pretrigger is supported for 34411A but only when the trigger configuration permits it; verify `pretrigger_count < sample_count` and device-specific firmware limits. Start with `pretrigger_count=0` implementation; add pretrigger after separate test evidence.
- Validate `sample_interval_s` as a finite positive number, then determine supported min/max from instrument queries/manual. A finite requested interval is not necessarily achievable under all NPLC/range settings.
- Restrict trigger source to documented `IMM`/`EXT`/`BUS` and avoid ambiguous implicit triggering.
- Distinguish states `IDLE / CONFIGURED / ARMED / COMPLETED / ABORTED / FAULTED / UNKNOWN`. Local state is not authoritative after lost I/O. After reconnect, require fresh instrument queries and operator decision, never repeat non-idempotent acquisition/copy/erase automatically.
- Hold the existing `ScpiSession.operation_lock()` for each multi-command critical transaction; do not introduce a second, conflicting mutex. Protect count-check plus copy as one serialized operation, but **do not** block close/STOP for the entire acquisition wait without a finite bound.
- Default to read-only memory inspection; `INIT`, `ABOR`, buffer draining, NVM copy, and NVM erase are explicitly commanded. No implicit device clear/reset, no `SYST:SEC:IMM`, no mass erase, no persistent setting changes without documentation.
- Fail closed if NVM already has data and `overwrite=False`. Even `overwrite=True` must verify actual `DATA:COPY` overwrite/append behavior and retain a deliberate host-side backup option.
- Never retry `DATA:REMove?`, `R?`, `DATA:COPY`, or `DATA:DELete` after uncertain I/O completion; stale-response recovery is delegated to core transport/session behavior.
- Bound all operations by overall deadlines. Use distinct expected acquisition duration and VISA-transfer timeout budgets; do not reuse the 5 s default for 50,000-readings NVM transfer.
- Treat interrupted NVM copy, power failure, memory capacity mismatch, and sample loss as explicit failures; compare readback count and checksum where applicable.

## 5. Large data transfer and precision design

`scpi-driver-core` currently defaults to a 1 MiB response bound. That may be too small for 50,000 ASCII NVM values or a 1-million-point volatile acquisition.

- Keep single-message `DATA:DATA? NVMEM` bounded but size the `ReadRequest` / `ScpiTextCodec.maximum_response_size` to an explicit, documented, finite budget (e.g. 8–16 MiB for NVM, with real format testing). Never silently truncate.
- For large volatile captures, prefer count-verified `DATA:REMove? <n>` chunks with clear **destructive** semantics, or a supported binary `FORMat REAL,32/64` fast path via core binary-block parsing **only if the Programmer's Reference confirms the specific instrument encoding**. Do not assume an IEEE definite-length block when unverified.
- `FETCh?` may require a single large reply; bound and refuse oversized nondestructive reads unless a verified safe streaming solution exists. Never replace a non-destructive request with destructive `DATA:REMove?` silently.
- For each chunk: snapshot count, request up to remaining available readings, parse all tokens, verify returned count, update durable host export, then continue. On failure, return/record how many values were definitely transferred and the resulting buffer state as **unknown** until re-queried.
- Implement explicit `FORMat:DATA ASCii` configuration for ASCII APIs, checking/restoring previous format where feasible. Never interpret binary bytes as CSV.
- For safe output write to temporary file, `fsync` as justified, atomically rename, and record SHA-256; never declare a complete capture on partial output.
- Favor offline simulators for small, boundary and large synthetic payloads. Large tests may use generated chunk responses without retaining 1M Python strings at once.

## 6. Deliverables and implementation sequence

Execute the following in order, committing small reviewable increments:

1. **Command/reference audit:** extract exact 34411A Programmer's Reference descriptions for each command, especially `FETCh?`, `R?`, `DATA:COPY`, `DATA:REMove?`, `SAMPle`, format and error behavior. Add an evidence table with literal expected request/response formats. Disambiguate NVM vs volatile side effects before any destructive operation.
2. **Models and validation:** create dataclasses/typed API and error types in root package, add input/boundary tests, keep public 0.1.x methods.
3. **Finite acquisition:** configure sample and trigger, initiate, bus trigger, wait and abort through shared core client/session; test no duplicate command on timeout.
4. **Volatile buffer:** count, bounded nondestructive fetch if confirmed, explicit destructive chunked drain; verify order/quantity/partial transfer.
5. **NVM:** count, non-destructive read, guarded copy with capacity/data-preservation semantics, guarded delete. Explicitly verify final count and store readback.
6. **Host capture export:** CSV and JSON metadata (machine-readable), atomic completion, numeric fidelity, integrity verification.
7. **Offline qualification:** scripted core transport, PyVISA-sim, Hypothesis, failure injection (timeout mid-transfer, disconnect, malformed/extra data, bad count, overflow, wrong model), pytest-timeout per test and job-level bounds.
8. **HIL qualification:** separate opt-in tests and reproducible operator guide. Physical test only after bench authorization; record instrument firmware, response traces and memory persistence over power-cycle.
9. **Review + release:** preserve installability, update README usage, command coverage matrix, CHANGELOG, `pyproject.toml` and `__version__` to **0.2.0** for implementation. CI Python 3.10–3.13 green, no unverified claim of hardware pass. PR review before merge.

## 7. Automated acceptance matrix

| Area | Required tests |
| --- | --- |
| Count/capacity | 0, 1, 49,999, 50,000, 50,001, 999,999, 1,000,000, 1,000,001; reject invalid types/values |
| Acquire | IMM, BUS, EXT; no implicit `*TRG`; invalid trigger; late trigger; abort; repeated start |
| Memory isolation | RDG_STORE vs NVMEM counts never confused; contents unchanged by non-destructive reads |
| NVM safety | Existing NVM blocks copy unless explicit policy; deletion requires confirmation; no silent clearing at open/close |
| Large transfer | 1 / 1000 / 50,000 NVM readings; 1M volatile count; chunked drain with exact ordering; malformed/truncated payload |
| Recovery | Faulted transfer does not retry destructively; no stale reply reuse; reopen and reconcile counts |
| Export | Numeric precision, explicit units/metadata, checksum, atomic output and partial failure recovery |
| Compatibility | Original `from dmm34411a import DMM_34411A` and legacy `src.DMM34411A_class` import remain usable |
| CI | `pytest -m "not hardware"`, package build and pip-check on 3.10–3.13 |

Use `scpi_driver_core.simulation.ScriptedScpiTransport`, existing PyVISA-sim fixture, and `pytest-timeout`. Avoid hand-written alternative VISA transports, blanket reruns or physical equipment in normal CI.

## 8. HIL gate — operator-authorized, not part of automatic CI

**Preflight:** identify 34411A serial/firmware, verify appropriate low-risk DC voltage source/connection, review calibration, test memory existing data and back it up. Do not change terminal selection while signals are present.

1. Query NVM and volatile counts before capture; preserve or export any existing data. Confirm software does not erase on open.
2. Capture exactly 10 known DC voltage readings in immediate mode; read volatile count and verify order/value using an explicitly permitted method.
3. Capture 1000 readings at a conservative supported interval, with programmed count and timer readback. Compare nominal sample period and actual acquisition duration.
4. Test bus trigger using `*TRG`, external trigger only when fixture is safely wired, and bounded abort. Confirm no stale data/duplicate triggers.
5. Copy **up to 50,000** readings to NVM only after explicitly approving handling of existing NVM; compare counts and data before/after copy.
6. Power-cycle only with bench authorization; verify NVM persistence; compare a host-side SHA-256 export and sample count. Volatile-memory loss after power-cycle is expected.
7. Test guarded deletion only with disposable test data, explicit operator approval and a saved backup. Verify memory count becomes zero.
8. Run failure injection against simulation first; only use safe physical cases on HIL. Log commands/responses, resource identity, versions, duration, pass/fail and discrepancies.

**Never** issue `DATA:DELete`, `SYSTem:SECurity:IMMediate`, `*RST`, or VISA device clear as part of initial connect, auto-recovery, or an unapproved HIL procedure. `DATA:DELete` is permitted only in an explicit protected deletion test.

## 9. Definition of done

- All features in §3 implemented, documented and covered by offline tests; proven startup and connection compatibility with original driver.
- No unsupported SCPI behavior assumed; source/firmware ambiguity explicitly resolved or a feature flagged gated/unavailable.
- Non-destructive retrieval verified; destructive actions isolated, safeguarded and **never retried** on timeout.
- Count, memory capacity, buffer ordering, CSV persistence and integrity verified under nominal and failure cases.
- GitHub PR includes test evidence and CI results. HIL status is reported truthfully and must not block merging a software-only PR if gated features remain physically disabled or explicitly marked unqualified.
- Firmware-specific limitations and NVM write-cycle considerations documented; operator controls how often flash-backed NVM is written.

## 10. Out of scope

Do not introduce a GUI, auto-delete existing instrument data, write to instrument calibration/state memory, fake sample timestamps, modify `scpi-driver-core` without demonstrated generic need, or automatically start an unattended high-speed HIL acquisition. Keep v0.1.1 task documentation separate from v0.2.0 feature implementation.

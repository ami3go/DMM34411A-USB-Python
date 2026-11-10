# DMM34411A-FULL-API-001 — Complete Missing Measurement, Metrology, Trigger and System Functions

**Priority:** P0 (safety and measurement integrity); P1 (essential function coverage); P2 (instrument convenience)  
**Repository:** https://github.com/ami3go/DMM34411A-USB-Python  
**Core dependency:** https://github.com/ami3go/scpi-driver-core  
**Baseline:** v0.2.0 / main commit `23bbf758cc4d8b43f2bb9aed8d1bd5eb170d8afe` (2026-11-10)  
**Planning release:** v0.2.1, documentation only. This document **is not an implementation**.  
**Implementation:** Sequential, self-contained software PRs with version increment and independent test/merge gates. First functional release should be at least **v0.3.0**; later increments follow SemVer and repository policy.  
**Hardware:** Agilent/Keysight **34411A** specifically; do not silently assume 34410A and L4411A have identical limits/features.  
**HIL:** NOT RUN for new functions. Never claim physical qualification based on a mock or LAN loopback.

## 1. Objective and boundary of work

Finish the currently missing **34411A measurement and instrumentation APIs** without replacing existing working code, duplicating generic SCPI infrastructure or erasing the meter's stored data. Preserve the installable package located at repository root (`dmm34411a/`) and existing `scpi-driver-core`-backed USB/VXI-11/TCP interfaces.

Deliver full model-specific command wrappers, validation, command/response coverage, documentation, deterministic offline tests and operator-authorized HIL procedures. Once each independent increment is reviewed and CI-green, it may be merged with truthful HIL status. Physical measurement capability must not be reported as hardware-verified until actual bench evidence exists.

**Do NOT** reimplement features already merged in PR #1 / v0.2.0, namely:
- USB VISA, Ethernet VXI-11, Ethernet raw SCPI/5025, injected Transport, ScpiClient and ScpiSession.
- Legacy basic DCV, DCI, 2-wire and 4-wire ohms methods (including their original misspelled names and **string** results).
- Basic finite `INITiate`/`ABORt` acquisition; IMM/EXT/BUS setup; `*TRG`, sample interval, trigger delay, point count/progress, guarded NVM copy/read/delete and bounded ASCII volatile readback.
- NVM retention policy: existing data must **never be deleted implicitly**. Reuse `dmm34411a/acquisition.py`, not a second acquisition engine.

Known limitations in v0.2.0 include no dedicated functions for several basic measurement modes and temperature probe variants (ACV, ACI, frequency, period, capacitance, continuity, diode, temperature thermistor, temperature RTD 2-/4-wire), incomplete metrology controls and model-specific trigger/buffer support. Not every documented SCPI operation is a sensible high-level method: implement an ergonomic, audited functional API while preserving raw `cmd_write`/`cmd_query` for advanced use.

## 2. Non-negotiable safeguards

1. **No implicit physical action on construction, opening, closing, reconnect or status query:** no `*RST`, `*CLS`, `ABORt`, `DATA:DELete`, `SYSTem:PRESet`, `SYSTem:SECurity:IMMediate`, calibration changes, VISA clear or other state-destroying command.
2. **Never automatically delete/overwrite NVM**. Existing NVM blocks destructive writes; only `delete_data_log(confirm=True)` may erase, and even that must be guarded/confirmed against real firmware before HIL. Never retry non-idempotent memory operations after an uncertain timeout.
3. Do not silently switch from voltage/resistance/diode mode into **current** mode on a physical DUT. Current input requires operator-approved fused wiring and test fixture; current HIL is always a distinct authorization gate.
4. Mode selection is **not necessarily harmless** (ohms, diode, capacitance may source an excitation). Separate configuration and measurement. No automatic all-mode scan on a connected DUT.
5. Reuse shared `scpi-driver-core` transport, framing, deadline, binary-block, error and session primitives. Never copy or fork the core. If a generic bug is proven, open a **separate core PR** and verify downstream compatibility; pin updated core by immutable commit.
6. API input validation before instrument writes: no bool-as-number, NaN/Inf, invalid units, unsupported function/trigger combinations, embedded SCPI line breaks, or unbounded responses.
7. Do not claim 50,000 readings/s by Python loop. This is a conditional **instrument** throughput under specific resolution/range/trigger/format settings, not universal throughput.
8. Model capability detection must not infer a 34411A from an arbitrary `*IDN?` string without parsing and documenting acceptable vendor/model variants. Non-34411A advanced features require explicit feature checks.
9. No unbounded sleeps, loops, waits or memory allocations. Use finite deadlines and cancellation/abort semantics. Any uncertain transfer must surface "UNKNOWN" state and require operator reconciliation before a new destructive action.
10. Preserve backwards compatibility: `DMM_34411A`, existing misspelled method names, raw SCPI commands, `from_ethernet()`, `src/DMM34411A_class.py` checkout shim, legacy string return types, and installable wheel.

## 3. Required preparatory audit (P0-AUDIT)

Before implementing any command, extract a **model-specific command catalog** from the official Keysight Programmer's Reference Help, cross-checking Quick Reference, User Guide and 34411A capabilities. Produce `docs/SCPI_COMMAND_COVERAGE.md` with these mandatory columns:

`Feature | SCPI set command | SCPI query | Valid parameters & units | Instrument mode | Supported model(s) | Method name | Current state | Offline test | Hardware test/evidence | Notes/side effects | Source page/URL`.

Distinguish **documented**, **confirmed against firmware**, and **implementation verified**. Review precise response formats (ASCII/binary), enum abbreviations, long/short SCPI command forms, reset side effects, allowable ranges, NPLC/aperture mutual exclusivity and firmware behavior. Do not use a speculative command just because another DMM supports it.

**Known documentation discrepancy:** the User Guide documents `TRIGger:SOURce INTernal` for the 34411A, but a Quick Reference list shows only immediate/external/bus. Resolve using model Programmer's Reference and a 34411A firmware HIL check; do not quietly omit the feature or assert it works on every firmware. Likewise verify `FETCh?`, `R?`, `DATA:REMove?` destructive/retention semantics before broad data-transfer use.

## 4. Implementation work packages — required sequence

### P0-01 — Safety, command integrity and readback foundation

- Build `dmm34411a/models.py` with typed `MeasurementFunction` enum, `MeasurementConfig` dataclass, `MeasurementResult` (value, units, function, range, host timestamp and metadata) and model capability constraints. Provide a clear separation between historical text-returning API and new typed API.
- Add `dmm34411a/meter.py` (or `measurement.py`) for model-specific configuration/reading, composed into `DMM_34411A`; avoid an all-purpose method with uncontrolled SCPI interpolation.
- Provide `get_config()` and `get_identity()` (read-only) plus `get_error()` / `drain_errors(max_errors)` with bounded queue depth. Do not clear errors automatically during connection.
- Structured, finite `timeout_s`, `ConfigurationError` on invalid input, and `UnsupportedOperationError` on unsupported model options.
- Validate function switching, terminal wiring requirements, input protection warnings and what `MEASure?` resets vs `CONFigure`/`READ?` preserves. Preserve user settings unless the explicit method contract says it configures them.
- Add typed parsing with explicit handling of Keysight overrange/sentinel values and nonfinite readings; distinguish an overload from a normally valid float. Preserve raw data for provenance where feasible.
- Write tests proving **invalid input sends zero instrument writes**, no implicit reset/clear/trigger, and all legacy APIs remain byte-compatible.

### P1-02 — Missing basic measurement modes (essential coverage)

Implement **configure + measure + typed-result** methods for each supported function. The raw SCPI forms below are documented **candidate command families**; exact suffixes, optional arguments and default side effects must be audited before coding.

| Function | SCPI configuration | One-shot query | Proposed Python API |
| --- | --- | --- | --- |
| AC voltage (true RMS) | `CONFigure:VOLTage:AC` | `MEASure:VOLTage:AC?` | `configure_ac_voltage(...)`, `measure_ac_voltage(...)` |
| AC current (true RMS) | `CONFigure:CURRent:AC` | `MEASure:CURRent:AC?` | `configure_ac_current(...)`, `measure_ac_current(...)` |
| Frequency | `CONFigure:FREQuency` | `MEASure:FREQuency?` | `configure_frequency(...)`, `measure_frequency(...)` |
| Period | `CONFigure:PERiod` | `MEASure:PERiod?` | `configure_period(...)`, `measure_period(...)` |
| Capacitance | `CONFigure:CAPacitance` | `MEASure:CAPacitance?` | `configure_capacitance(...)`, `measure_capacitance(...)` |
| Continuity | `CONFigure:CONTinuity` | `MEASure:CONTinuity?` | `configure_continuity()`, `measure_continuity()` |
| Diode | `CONFigure:DIODe` | `MEASure:DIODe?` | `configure_diode()`, `measure_diode()` |
| Thermistor temperature | `CONFigure:TEMPerature THERmistor,...` | `MEASure:TEMPerature? ...` | `configure_temperature(probe="thermistor", ...)` |
| 2-wire RTD temperature | `CONFigure:TEMPerature RTD,...` | `MEASure:TEMPerature? ...` | `configure_temperature(probe="rtd_2w", ...)` |
| 4-wire RTD temperature | `CONFigure:TEMPerature FRTD,...` | `MEASure:TEMPerature? ...` | `configure_temperature(probe="rtd_4w", ...)` |

**Requirements:** Decide whether the new `measure_*` returns a typed float/MeasurementResult or whether there should be a consistent `read_value()`; **never change old method return types**. Explicitly document SI units (V, A, Ω, Hz, s, F, °C/°F/K), meaning of continuity/diode return codes and special values, supported probe resistance/type options, temperature wiring and reference definitions. Thermistor types indicated by the reference include 2252/5000/10000 Ω; confirm applicable 34411A firmware options. Continuity/diode do not support all arbitrary range/resolution settings.

Each function must have: configure, query/readback, positive and negative tests, and **opt-in physical evidence**. Do not enable current or temperature fixture rewiring without operator authorization.

### P1-03 — Metrology settings and validated measurements

Design `MeasurementConfig` so each parameter is function-aware, not an unbounded list of generic SCPI strings.

| Parameter | Verified SCPI family/example | Scope |
| --- | --- | --- |
| Measurement function readback | `CONFigure?` | Query and parse function and arguments |
| Manual/auto range | `SENSe:VOLTage:DC:RANGe`, `:RANGe:AUTO` | V/I/Ω/C as supported; query effective range |
| Resolution | `SENSe:VOLTage:DC:RESolution` (and DCI/Ω variants) | Validate or use MIN/MAX/DEF with documented effects |
| DC integration time | `SENSe:VOLTage:DC:NPLC` (and relevant variants) | NPLC bounds, timing impact, readback |
| Aperture | `SENSe:VOLTage:DC:APERture`, `:APERture:ENABled?` | Detect conflicts with NPLC |
| Autozero | `SENSe:VOLTage:DC:ZERO:AUTO` | OFF/ON/ONCE where documented |
| DC voltage input impedance | `SENSe:VOLTage:DC:IMPedance:AUTO` | Input-loading implications |
| AC RMS bandwidth | `SENSe:VOLTage:AC:BANDwidth`, `SENSe:CURRent:AC:BANDwidth` | 3/20/200 Hz only when documented |
| Frequency/period gate | `SENSe:FREQuency:APERture`, `SENSe:PERiod:APERture` | Effective gate timing |
| Resistance offset compensation | `SENSe:RESistance:OCOMpensated` and FRES variant | Mode-specific readback |
| Temperature | `SENSe:TEMPerature:TRANsducer:TYPE`, `UNIT:TEMPerature`, RTD/thermistor types | Unit/reference/wiring configuration |
| Per-function null | `SENSe:<function>:NULL:STATe`, `:NULL:VALue` | Non-destructive, readback-verified |

Deliver: typed range enums/values, numeric/boolean validation, mode-specific supported-setting map, no arbitrary SCPI concatenation, query round-trip tests and no hidden `MEASure?` config reset. Capture function/range/NPLC/aperture in result metadata.

### P1-04 — Analog/internal trigger, pretrigger and synchronized capture

Extend **existing** `AcquisitionController`, do not create parallel acquisition state.

- Internal trigger: `TRIGger:SOURce INTernal` (**34411A only**, and only AC/DC voltage/current and 2-/4-wire resistance modes, per User Guide). Implement `set_level_trigger(level, slope=POS/NEG)` after reference verification; configure `TRIGger:LEVel` and `TRIGger:SLOPe`, query and verify; reject incompatible functions.
- Pretrigger: `SAMPle:COUNt:PRETrigger`, count must be >= 0 and strictly less than total sample count; verify exact additional constraints for internal/external trigger and memory capacity.
- Configurable `TRIGger:COUNt`, `TRIGger:DELay`, `SAMPle:COUNt`, source and timer. Compute total expected samples and enforce combined memory limits, including any trigger-count multiplication.
- Introduce `AcquisitionState` with `IDLE/CONFIGURED/ARMED/COMPLETE/ABORTED/FAULTED/UNKNOWN` and document which states are local vs instrument-confirmed.
- `wait_complete` must be deadline-bound even for an untriggered EXT/BUS/INT acquisition; no deadlock on `*OPC?`. Add explicit cancel/stop and partial-reading metadata. No silent retry for `INIT` or `ABORt`.
- Verify `OUTPut:TRIGger:SLOPe` and external-trigger output behavior when practical; do not imply an electrically safe trigger-out without testing.
- Add HIL with a safe isolated external trigger source. Measure trigger latency and pre/post sample ordering, compare against source waveform, preserve existing NVM.

### P1-05 — 1,000,000-reading volatile memory, binary transfers and traceable export

Build on existing `FETCh?`, `DATA:REMove?`, `DATA:DATA? NVMEM` implementation. Existing 20,000-value ASCII ceiling is a deliberate safety bound, not full memory support.

- Read and verify `FORMat:DATA` (ASCII / REAL with documented 32- and 64-bit length), `FORMat:BORDer`; decode IEEE 488.2 definite-length binary blocks via **core** parsing; verify instrument encoding/terminator/endianness before claiming a format works.
- Separate **nondestructive full fetch** from **destructive chunked drain** APIs. Never silently turn a nondestructive read into removal. Do not call destructive `R?`/`DATA:REMove?` on retry after ambiguous timeout.
- Stream with bounded memory, configurable chunk size, count/sequence integrity, precise final counts, and robust handling of short replies, partial sockets, disconnects, progress and cancel.
- Support up to 1,000,000 volatile readings where the instrument supports it, and NVM up to 50,000; enforce different limits. No unrestricted 1M `list[float]` allocation by default.
- Host export: CSV/JSON metadata, optionally binary/NPY only after format analysis; atomic temporary-file/write-then-rename, SHA-256 digest, reading count, declared units, function, instrument serial/firmware, transport, driver/core versions, range, NPLC/aperture, nominal interval and time source.
- **Never invent individual sample timestamps.** Distinguish nominal sample offsets from actual instrument per-sample timestamps (if unavailable).
- Overload/sentinel representation, numerical precision, NaN policy and CSV round-trip preservation must be specified and tested.
- Handle NVM copy/overwrite/append behavior **only after** firmware-specific evidence; retain current protective refusal for nonempty NVM.
- Test 0,1,20k,50k,50,001,1M capacity and transfer boundaries; mid-payload timeout, corruption, wrong count, interrupted format restoration and partial export.
- Assess whether `scpi-driver-core` needs a narrowly scoped generic transport API update for streaming; any change belongs in its own versioned core PR with downstream regression.

### P1-06 — Driver status, error handling, service health and HIL diagnostics

- Structured `SYSTem:ERRor[:NEXT]?` retrieval, queue depth limit and preservation of raw errors.
- IEEE `*ESR?`, `*ESE`, `*SRE`, `*STB?`; instrument `STATus:OPERation`/`STATus:QUEStionable` condition and event registers, using core IEEE helpers where available.
- `*OPC?`, `*WAI` and `*TST?` are **not** routine startup actions; explicit only. Instrument self-test may disrupt bench operation.
- `ROUTe:TERMinals?` is read-only status; never claim software can move a physical front/rear terminal selector.
- Add `diagnostics_snapshot()` with no destructive actions: parsed IDN, active function, options, current transport/resource, relevant status registers, NVM and volatile point counts (when safe), firmware and core version.
- Expose read-only `health`/connectivity state separately from an instrument measurement complete state.
- HIL tests must record actual command/response traces and error queue without clearing pre-existing errors by default.

### P2-07 — DMM math, statistics, relative readings and limits

Implement focused math/statistics APIs, not another general-purpose scripting subsystem:

| Feature | Documented SCPI | Proposed API |
| --- | --- | --- |
| Statistics mode | `CALCulate:FUNCtion AVERage`, `CALCulate:STATe` | `enable_statistics()`, `disable_math()` |
| Mean/min/max/SD/count/peak-to-peak | `CALCulate:AVERage:{AVERage?,MIN?,MAX?,SDEViation?,COUNt?,PTPeak?}` | `read_statistics()` dataclass |
| dB / dBm math | `CALCulate:FUNCtion DB/DBM`, `:DB:REFerence`, `:DBM:REFerence` | `configure_db(...)`, `configure_dbm(...)` |
| Upper/lower limit comparison | `CALCulate:FUNCtion LIMit`, `:LIMit:LOWer/UPPer` | `configure_limits(low,high)`, `read_limit_state()` |
| Null/relative offsets | Per-function `SENSe:<function>:NULL` | `set_null(...)`, `read_null(...)` |

**Important:** most `CALCulate:FUNCtion` math modes are **mutually exclusive**; per-function null may coexist. Do not overwrite an existing math mode silently. Report statistics-clearing side effects when enabling statistics, changing function or explicit clear. Numeric units and thresholds must remain correct through dB/dBm conversions.

### P2-08 — State slots, display, local operations and interface diagnostics

- Named state save/recall using `*SAV`/`*RCL` and `MEMory:STATe` catalog/validity/selection queries; explicit confirmation before overwriting/deleting slots, and readback/metadata first.
- Display on/off, text clear/custom text and secondary display text feed via `DISPlay` subsystem. Avoid changing display automatically on connect.
- Read-only LAN/GPIB service status and model identification. No automatic LAN address reconfiguration; network write operations could sever access. If exposed, require explicit parameter validation, full rollback/HIL plan and operator authorization.
- `SYSTem:BEEPer` beeper is explicit/opt-in. Do not add arbitrary reset, security, calibration or system preset actions as convenience defaults.
- Do **not** expose `SYSTem:SECurity:IMMediate` or calibration writing in the ordinary driver API.

### P1-09 — Cross-interface and physical qualification

Prepare bench-selectable HIL suite for USB/VISA, LAN VXI-11 and raw SCPI socket 5025; optionally GPIB if available. All are currently **HIL unverified** even if offline tests are green.

Preflight:
- Record model, firmware, serial, calibration status, protocol, VISA backend, Python/core/driver versions and source uncertainty.
- Inspect DUT wiring and current terminal status before mode changes. No unattended current-mode or powered-capacitance/diode tests.
- Record existing NVM contents and protect them from writes/erasure. No `*RST`, `*CLS`, `DATA:DELete` or physical power-cycle without bench authorization.

Test groups:
1. Safe DCV known voltage at two ranges and three integration times; compare uncertainty and readback.
2. ACV true RMS with traceable sine wave and at least two frequencies/bandwidth settings.
3. Resistance 2-/4-wire using known standards; offset compensated vs uncompensated.
4. Current AC/DC after **separate fixture authorization**, fuse and bounded current reference verification.
5. Frequency and period using signal source and independent reference; verify gate-time trade-off.
6. Capacitance, diode and continuity using disconnected/passive fixture with documented threshold semantics.
7. Thermistor and 2-/4-wire RTD using standards or simulator with traceable probe models.
8. Triggering: IMM/BUS/EXT and internal threshold/slope (34411A); pretrigger ordering and event latency; reject unsupported combinations.
9. Volatile reading count/ordering, ASCII and binary transfers, chunked destructive drain with disposable data only.
10. NVM readback/persistence across an **operator-authorized** power cycle; deliberate deletion with backup only if approved.
11. Math/statistics and limits, including mode exclusivity and reset/clear side effects.
12. Disconnect/timeout/fault recovery on each available transport; no stale response, no double-execution, no unexpected data loss.

Report each case with command transcript, settings, expected and measured values, uncertainty, error/status queue, actual timeouts, raw data hashes, PASS/FAIL/NOT RUN and operator sign-off. Do not equate a parsable numeric reading with accuracy qualification.

### P1-10 — Release closure and command coverage

- Update `docs/SCPI_COMMAND_COVERAGE.md` command-by-command for each delivered package.
- Keep `docs/FEATURE_COVERAGE.md` current against the actual code; fix stale pre-merge PR #1 status/history text instead of presenting it as live state.
- Update README examples, API docs, CHANGELOG, release tag, pyproject version and `dmm34411a.__version__` **for each code-changing PR**.
- Add `ruff check`, `ruff format --check` and type check (as scoped), test/build/package smoke with Python 3.10/3.11/3.12/3.13. Extend CI with a minimum coverage threshold for the newly added modules.
- Only merge **independently reviewed**, fully passing software increments. HIL-dependent functions may merge behind explicit qualification markers only if enabled behavior is genuinely offline-safe and unverified physical claims are absent.
- For each merged PR record HEAD SHA, test output, number of documented implemented/partial/missing SCPI command groups and remaining HIL gates. Avoid duplicate task PRs.

## 5. Proposed public API, code and package structure

Keep `dmm34411a/` directly at repository root; no new `src/` tree. Candidate modules:

```text
dmm34411a/
  __init__.py
  driver.py               # backwards-compatible DMM_34411A and connection
  acquisition.py          # EXISTING; extend, do not replace
  models.py               # enums/config/results/data provenance
  measurement.py          # function-aware configure/read/measure
  metrology.py            # ranges, NPLC, aperture, autozero, bandwidth
  status.py               # read-only status and bounded error-queue operations
  math.py                 # statistics, dB/dBm, null, limit thresholds
  storage.py              # optional state-slot wrapper distinct from NVM readings
tests/
  test_measurement_modes.py
  test_metrology.py
  test_advanced_triggers.py
  test_streaming.py
  test_math.py
  test_status.py
  integration/
  hardware/               # opt-in only
docs/SCPI_COMMAND_COVERAGE.md
docs/HIL.md
task/DMM34411A_FULL_FUNCTION_COVERAGE_TASK.md
```

**Suggested API behavior:**

```python
from dmm34411a import DMM_34411A
from dmm34411a.models import MeasurementConfig, MeasurementFunction

with DMM_34411A.from_ethernet("192.168.0.55", protocol="socket") as dmm:
    dmm.measurement.configure(MeasurementConfig(
        function=MeasurementFunction.AC_VOLTAGE,
        range="AUTO",
        ac_bandwidth_hz=20,
    ))
    result = dmm.measurement.read()
    print(result.value, result.unit)  # e.g. a numeric value and "V"
    print(dmm.measurement.get_config())
```

This is **design-only** code: none of `measurement.configure`, `MeasurementConfig` or `MeasurementFunction` exists in v0.2.0. The implementation PR may adjust naming after review, but MUST preserve backward compatibility and typed results for the new API.

## 6. Offline acceptance and negative-test matrix

| Test class | Mandatory cases | Pass criteria |
| --- | --- | --- |
| Legacy regression | old DCV/DCI/2W/4W spelling and return text, USB/LAN constructors, source-checkout shim | byte-for-byte original SCPI command behavior preserved |
| Measurement mode | ACV/ACI/Hz/period/C/continuity/diode/temp variants, invalid mode and unsupported aliases | exact validated program messages and typed parse |
| Parameter bounds | MIN/MAX/DEF, 0, -1, NaN, Inf, bool, wrong unit, invalid resolution, unsupported range/temperature type | exception before instrument write |
| Metrology readback | set/query range, NPLC, aperture, autozero, bandwidth, null and compensation | round-trip or documented device rounding; no silent profile drift |
| Trigger | IMMediate/BUS/EXT/INT, positive/negative slope, pretrigger 0/1/count-1/count, timeout/abort | no missed/duplicate commands, no unlimited blocking |
| Memory | 0/1/20k/50k/50,001/999,999/1M, existing NVM, copy/erase confirmations | capacity and preserved-data contracts |
| Binary data | REAL32/REAL64, NORM/SWAP, definite/invalid/short blocks, end markers | decoded values/count/order, bounded allocation, faults on corruption |
| Failure handling | SCPI -113, -222, malformed response, partial TCP stream, VISA timeout, disconnect, response sentinel | deterministic typed failure; no stale data or unsafe retries |
| State transitions | open, close, reconnect, abort, partial completion, duplicate INIT, STOP during wait | bounded lifecycle, known/unknown state correctly reported |
| Math/status | active mode switch, stats clear, errors, event/status registers, limit comparison | no hidden clearing and correct units |
| Host files | 1/50k/1M data, interrupt during write, disk full, wrong hash, crash/restart | atomic success only, partials recorded as such |
| Packaging/CI | Python 3.10–3.13, wheel/sdist, `pip check`, Ruff, pytest and PyVISA-sim/localhost TCP | all release gates green without real instrument |

Use `scpi_driver_core.simulation.ScriptedScpiTransport`, existing PyVISA-sim fixtures, localhost TCP fixture, Hypothesis for bounds, and `pytest-timeout`. No physical instrument in default CI.

## 7. Explicit per-PR merge policy and release sequencing

| Increment | Work package | Gate before merge |
| --- | --- | --- |
| PR A, target >=v0.3.0 | P0-01 safety/model API + P1-02 measurement modes | all 13 base function families/variants have typed tests; no accidental current scan |
| PR B | P1-03 metrology settings | range/NPLC/aperture/AC bandwidth readbacks and limits verified in CI |
| PR C | P1-04 internal/pretrigger improvements | firmware ambiguity documented; HIL-dependent INT mode gated until qualified |
| PR D | P1-05 binary/streamed memory | large-data integrity tests and no destructive retry proven |
| PR E | P1-06 status & diagnostics | bounded error consumption and non-destructive snapshots |
| PR F | P2-07 math/stats/limits | correct exclusivity and result semantics |
| PR G | P2-08 state/display | explicit stored-state overwrite/delete confirmations |
| PR H | P1-09 + P1-10 HIL and release closure | evidence, matrix, tagged release gates |

Do work **sequentially**; inspect current `main`, reviews and CI after each increment. Do not fabricate a release or merge status. If HIL requires physical bench interaction, complete offline tasks and report the external HIL gate explicitly.

## 8. Definition of done for the master task

- Complete dedicated 34411A wrappers for documented common measurement modes, metrology settings, advanced trigger and sample control, finite/binary/streamed acquisition, math/statistics/limits, relevant status and safe storage/display.
- Preserved device data and existing APIs across USB, VXI-11, TCP sockets and optional GPIB. Current `scpi-driver-core` owns all transport I/O.
- Every implemented SCPI command has a traceable reference, parameter table, positive/negative test and HIL status. No invented syntax or unsupported instrument capability.
- Large buffer and NVM semantics independently reviewed for destructive behavior; no data loss on connection, recovery, timeout, abort or host export.
- All software increments versioned, pushed, reviewed, CI-green, merged when eligible, documented in changelog and coverage report.
- Physical HIL marked PASS only when a documented authorized actual 34411A execution has evidence; otherwise accurately marked NOT RUN or BLOCKED.

## 9. Source references

1. [Keysight/Agilent **34410A/11A Command Quick Reference**, publication 9018-61141](https://www.keysight.com/us/en/assets/9018-61141/programming-guides/9018-61141.pdf): specific MEASure, CONFigure, SENSe, CALCulate, DATA, trigger, status, memory-state and IEEE commands.
2. [Keysight **34410A/11A/L4411A User's Guide**, publication 9018-05586](https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf): actual operation, supported measurement modes, internal triggering, pretrigger conditions, math exclusivity, NVM and I/O examples.
3. [Keysight **34410A/34411A data sheet**, publication 5989-3738](https://www.keysight.com/us/en/assets/7018-01326/data-sheets/5989-3738.pdf): capability and model-specific throughput/memory limits.
4. [Keysight Programmer's Reference Help package](https://www.keysight.com/hk/en/assets/9018-83366/help-files/9018-83366.zip): definitive parameter/side-effect/return-format details — must be inspected during command audit.
5. [Existing v0.2.0 driver](https://github.com/ami3go/DMM34411A-USB-Python/blob/main/dmm34411a/driver.py) and [acquisition controller](https://github.com/ami3go/DMM34411A-USB-Python/blob/main/dmm34411a/acquisition.py).
6. [Existing functional coverage matrix](https://github.com/ami3go/DMM34411A-USB-Python/blob/main/docs/FEATURE_COVERAGE.md) and [previous NVM specification](https://github.com/ami3go/DMM34411A-USB-Python/blob/main/task/DMM34411A_NVM_CAPTURE_BUFFER_TASK.md).

The SCPI Quick Reference is an index, not complete proof of command applicability. Where the Quick Reference and User Guide differ, resolve using the actual Programmer's Reference and instrument firmware and explicitly report the discrepancy.

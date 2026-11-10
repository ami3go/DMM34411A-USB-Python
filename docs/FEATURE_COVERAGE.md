# Keysight 34411A — Driver Feature Coverage Matrix

**Audit date:** 2026-11-10  
**Audited implementation:** `main` commit `b955b09168b347853063444a635316f68bf3c589` (v0.1.2).  
**Document release:** v0.1.3 historical audit; see v0.2.0 update below.  
**Implementation location:** `dmm34411a/driver.py`.  
**Open feature PR:** [#1 — Internal memory logging](https://github.com/ami3go/DMM34411A-USB-Python/pull/1), unmerged and based on the legacy direct-PyVISA driver.  
**Related task:** [DMM34411A-NVM-BUFFER-001](../task/DMM34411A_NVM_CAPTURE_BUFFER_TASK.md).

> **Current planning note (2026-11-10):** PR #1 has been merged into
> `main` as v0.2.0. The original table below is a historical v0.1.2 audit,
> not a claim that PR #1 is still open. The remaining missing functions and
> updated execution order are specified in
> [DMM34411A-FULL-API-001](../task/DMM34411A_FULL_FUNCTION_COVERAGE_TASK.md).
> Documentation-only v0.2.1 does not introduce new instrument features.

## v0.3.0 measurement implementation update

The table below is historical (v0.1.2). As of v0.3.0 the driver provides
typed basic configuration and reading for AC/DC voltage/current,
2-/4-wire resistance, frequency, period, capacitance, continuity, diode
and temperature (RTD 2-/4-wire, thermistor 2-wire), implemented as
`dmm.measurement` plus explicit convenience methods. All are
**software-only / physical HIL NOT RUN**. Manual numeric ranges,
integration time, aperture, trigger/streaming, status and math remain
not implemented. See `docs/SCPI_COMMAND_COVERAGE.md`.

## v0.2.0 memory implementation update

This matrix was audited against **v0.1.2 main** and remains the historical
baseline. As of the v0.2.0 implementation of PR #1, the following entries
changed from **PR only** to **implemented in software (HIL NOT RUN)**:

- Configure/start/abort finite acquisition, immediate/BUS/external trigger
  selection, sample interval/trigger delay, progress/count for RDG_STORE.
- Configured data logging, completion monitoring, copy to initially empty
  NVM, NVM reading/counting and explicitly confirmed deletion.
- ASCII FETCh and explicit DATA:REMove bounded to <= 20,000 readings per
  call, with model-specific retention/destructive semantics requiring HIL.

Still missing: 1M streaming acquisition, qualified binary data transfer,
pretrigger, CSV with metadata/checksum, safe NVM replacement semantics,
physical end-to-end testing and robust interrupted-transfer reconciliation.
Read the current README for safety and control details.

## How coverage is scored

- **Implemented:** a dedicated method in the installable `dmm34411a` package on `main`. May be only offline-qualified; see HIL column.
- **Partial:** a subset of documented settings/behavior, or a generic transport path exists without a model-specific API.
- **PR only:** implementation exists in open PR #1 but **not** on `main`. It has not been migrated to scpi-driver-core or accepted as safe.
- **Missing:** the 34411A supports the function but no dedicated wrapper exists on `main`.
- **Raw SCPI is not a completed feature:** `cmd_write()` and `cmd_query()` are general escape hatches, not validated command coverage or typed APIs.
- **HIL:** no physical hardware qualification evidence is available in the repository for the current driver. `tests/hardware/` contains opt-in smoke tests, not logged bench results.
- This is a **functional coverage audit**, **not** an exhaustive line-by-line SCPI command census.

## A. Measurement functions

| 34411A function | On-main implementation | Coverage | HIL |
| --- | --- | --- | --- |
| DC voltage | `conf_voltage_dc()`, `measure_voltage()` | Implemented: basic autorange config and reading | Not run |
| DC current | `conf_current_dc()`, `measure_current_dc()` | Implemented: basic config and reading | Not run |
| 2-wire resistance | `conf_resistane_2wire()`, `measure_resistnce_2wire()` | Implemented: basic config and reading | Not run |
| 4-wire resistance | `conf_resistane_4wire()`, `measure_resistnce_4wire()` | Implemented: basic config and reading | Not run |
| True-RMS AC voltage | — | Missing | Not run |
| True-RMS AC current | — | Missing | Not run |
| Frequency | — | Missing | Not run |
| Period | — | Missing | Not run |
| Capacitance | — | Missing | Not run |
| Continuity | — | Missing | Not run |
| Diode test | — | Missing | Not run |
| Temperature — thermistor | — | Missing | Not run |
| Temperature — RTD (2-/4-wire) | — | Missing | Not run |

All 13 above are documented instrument functions. The four existing methods preserve historical spelling errors and **return text** rather than floats.

## B. Measurement configuration and metrology

| 34411A capability | On-main API | Coverage | Importance |
| --- | --- | --- | --- |
| Range — autorange / explicit manual range | Basic AUTO selection in existing methods; no set/query wrapper | Partial | P1 |
| Resolution / number of digits | No dedicated method | Missing | P1 |
| Integration time in NPLC | No dedicated method | Missing | P1 |
| Aperture-based integration | No dedicated method | Missing | P1 |
| Auto-zero | No dedicated method | Missing | P1 |
| DC input impedance | No dedicated method | Missing | P2 |
| AC voltage/current filter bandwidth | No dedicated method | Missing | P1 |
| Frequency / period gate time | No dedicated method | Missing | P1 |
| Offset-compensated ohms | No dedicated method | Missing | P2 |
| Null / relative measurement | No dedicated method | Missing | P2 |
| Measurement function / range / aperture readback | Only generic `cmd_query()` | Missing typed API | P1 |
| High-speed 4.5-digit operation (up to 50,000 readings/s) | No acquisition/performance configuration | Missing | P1 |

**Speed caution:** 50,000 readings/s is an instrument capability under specified function, resolution and measurement settings, **not** a throughput guarantee from current Python API.

## C. Triggering, digitizing and reading memory

| 34411A capability | On-main API | PR #1 | Coverage |
| --- | --- | --- | --- |
| Immediate single reading | `READ?`, `MEASure...` via wrappers | Existing | Implemented |
| Configure finite sample count | None | `configure_volatile_acquisition()` / `configure_data_log()` | PR only |
| Start acquisition with `INITiate` | None | `start_acquisition()` / `start_data_log()` | PR only |
| Stop acquisition with `ABORt` | None | `abort_acquisition()` | PR only |
| Trigger source immediate / BUS / external | None | Basic selector in acquisition config | PR only |
| Software bus trigger `*TRG` | Raw `cmd_write()` only | No dedicated method | Missing |
| Internal analog level and slope triggering (34411A) | None | None | Missing |
| Trigger delay | None | Basic optional delay | PR only |
| Trigger count / repeated triggers | None | Fixed `TRIG:COUN 1` | Missing general API |
| Sample timer / sample source | None | Basic sample interval and AUTO | PR only |
| Pre-/post-trigger samples (34411A) | None | None | Missing |
| Volatile `RDG_STORE` count (max 1,000,000) | None | `volatile_point_count()` | PR only |
| Volatile non-destructive fetch | None | `read_volatile_readings(erase=False)` | PR only, unqualified |
| Volatile destructive drain (chunked) | None | `R?`-based destructive read, not robust chunk flow | Partial in PR only |
| NVM count (max 50,000) | None | `nonvolatile_point_count()` | PR only |
| Copy volatile to nonvolatile | None | `save_data_log()` | PR only; unsafe overwrite/erase policy |
| Non-destructive NVM read | None | `read_data_log()` | PR only |
| Explicit, protected NVM delete | None | `delete_data_log()` (unguarded) | PR only; safety blocker |
| Bounded large ASCII transfer | Core default response limit 1 MiB | Fixed timeout + PyVISA direct read | Missing robust model API |
| Binary 32-/64-bit data transfer | Core provides binary support; not in DMM wrapper | None | Missing |
| Atomic CSV + metadata/checksum export | None | None | Missing |
| Peak-detect acquisition | None | None | Missing |
| Measurement progress / completion / timeout | None | Basic polling and timeout | PR only; needs integrity hardening |

**PR #1 safety blockers:** (a) clears the VISA instrument during constructor and close; (b) `start_data_log(clear_existing=True)` deletes pre-existing NVM by default; (c) uses direct PyVISA instead of the merged shared core; (d) needs uncertainty-aware recovery and large-transfer integrity tests. Do not merge it unchanged.

## D. Math, statistics and instrument features

| Instrument feature | On-main API | Coverage | Priority |
| --- | --- | --- | --- |
| Null/relative offsets | No specific wrapper | Missing | P2 |
| dB / dBm math | No specific wrapper | Missing | P2 |
| Statistics: mean, min, max, count, standard deviation, peak-to-peak | No specific wrapper | Missing | P2 |
| Limit comparison / high-low limits | No specific wrapper | Missing | P2 |
| Instrument state save/recall (named and IEEE common commands) | Generic SCPI only | Missing safe wrapper | P2 |
| Instrument display / secondary-display functionality | No wrapper | Missing | P3 |
| Front/rear terminals status query | Generic SCPI only | Missing wrapper; do not assume electronic switching | P3 |
| Self-test / error queue / status and SRQ | Generic SCPI or core IEEE helper; not model-specific wrapper | Partial | P1 |
| Identity `*IDN?` | On connect, `idn` field and `cmd_query()` | Implemented | Not HIL verified |
| Calibration/service commands | Deliberately not automated | Intentionally excluded | Safety restricted |

## E. Interfaces, software architecture and validation

| Capability | On-main implementation | Coverage | Qualification |
| --- | --- | --- | --- |
| USB-TMC / VISA | `VisaTransport(resource_name)` | Implemented | PyVISA-sim CI; HIL not run |
| Ethernet VXI-11 | `from_ethernet(host, protocol="vxi11")` | Implemented | VISA address construction tested; HIL not run |
| Ethernet raw SCPI TCP/5025 | `from_ethernet(host, protocol="socket")` | Implemented | Localhost integration tested; HIL not run |
| GPIB / VISA | Generic VISA resource address accepted by shared core | Partial (no 34411A GPIB-specific HIL test) | Not run |
| Injected transport / simulated driver | `transport=...` | Implemented | Automated |
| Session lifecycle, close / reopen | `open()`, `close()`, context manager | Implemented | Automated |
| Bounded I/O timeout / fault state | Core `ScpiClient` and transport | Implemented | Automated for selected scenarios |
| Automatic discovery of LAN/USB equipment | Not provided by 34411A wrapper | Missing | — |
| Safe reconnection after uncertain operation | Explicit reopen exists; no guarded high-level workflow | Partial | HIL not run |
| Raw SCPI commands | `cmd_write()`, `cmd_query()` | Implemented, not command-by-command coverage | Automated framing tests |
| Typed numeric reading | Core `client.query_float()` usable manually | Partial; public measurement wrappers return strings | Automated core path |
| Installable root-level Python module | `pyproject.toml` and `dmm34411a/` | Implemented | Packaging CI |
| CI Python 3.10–3.13 / package build | `.github/workflows/ci.yml` | Implemented | PR #4 passed |
| Hardware HIL smoke-test scripts | `tests/hardware/test_real_dmm.py`, `test_real_lan.py` | Implemented but opt-in | **No hardware evidence** |

## Recommended phased implementation

| Phase | Priority | Scope / acceptance gate |
| --- | --- | --- |
| **A — Complete basic meter modes** | P1 | ACV, ACI, frequency, period, capacitance, temperature, diode, continuity; typed validated wrappers and simulator tests |
| **B — Measurement metrology controls** | P1 | Manual/auto range, NPLC, aperture, digits, autozero, bandwidth, gate time, readback and parameter bounds; preserve old APIs |
| **C — Migrate PR #1 into core** | P0 safety / P1 feature | Use core transports/client; eliminate default NVM delete and implicit device clear; acquire/store/read/abort with explicit transactional checks; no automatic retries of destructive commands |
| **D — Advanced trigger + fast acquisition** | P1 | Internal level/slope, external/bus, pretrigger, sample timer, binary/large data, timeout/fault integrity, up to 1M volatile readings |
| **E — Data integrity** | P1 | Safe NVM capacity/overwrite controls (50k), bounded chunk transfer, host CSV + metadata + hashes, cross-interface consistency |
| **F — Math and instrument convenience** | P2/P3 | Statistics, dB/dBm, limits, state storage, display/status, carefully scoped self-test/error diagnostics |
| **G — Physical qualification** | Required before HIL claims | USB, VXI-11, socket, optional GPIB; accuracy and command evidence, safe current mode, NVM persistence across operator-authorized power cycle |

## References and audit basis

**Implementation evidence:**
- [Main driver source](https://github.com/ami3go/DMM34411A-USB-Python/blob/main/dmm34411a/driver.py)
- [CI and software tests](https://github.com/ami3go/DMM34411A-USB-Python/tree/main/tests)
- [Open memory logging PR #1](https://github.com/ami3go/DMM34411A-USB-Python/pull/1)
- [Physical HIL checklist](https://github.com/ami3go/DMM34411A-USB-Python/blob/main/docs/HIL.md)

**Keysight device capability sources:**
- [Keysight 34410A/34411A data sheet](https://www.keysight.com/us/en/assets/7018-01326/data-sheets/5989-3738.pdf)
- [Keysight 34410A/34411A/L4411A User's Guide](https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf)
- [Keysight 34410A/34411A SCPI comparison guide](https://www.keysight.com/us/en/assets/7018-02044/white-papers-archived/5990-3515.pdf)
- [Keysight programmer's reference](https://www.keysight.com/hk/en/assets/9018-83366/help-files/9018-83366.zip)

**Important:** Actual SCPI syntax, side effects, model options, and device-level limits must be verified against the 34411A programmer's reference and (where required) authorized HIL before claiming implementation or compatibility. Documentation-only increments do not create functional device support.

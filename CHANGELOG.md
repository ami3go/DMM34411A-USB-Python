# Changelog

## 0.7.0 — 2026-11-11 (P1-04 advanced acquisition control, offline-only)

- Extend existing AcquisitionController with 34411A-only internal trigger
  crossing level/slope, pretrigger count, finite repeated triggers and
  total volatile/NVM capacity checks.
- Introduce local AcquisitionState and typed AcquisitionProgress
  (local state, observed count, target, trigger settings, host UTC time).
- Add explicit read-only trigger settings queries and optional trigger
  output slope settings (fixture qualification required).
- Make acquisition waiting finite for never-triggered EXT/BUS/INT modes,
  mark uncertain timeout as UNKNOWN, and prevent unsafe reconfiguration
  until explicit ABORt. One explicit STOP can report partial count.
- Preserve all legacy acquisition method names, string-returning DMM
  measurements, USB/LAN and protected NVM storage; no auto reset,
  buffer erase or implicit hardware interaction on connect/close.
- Add offline scripted regression and opt-in HIL instructions.
- Physical trigger latency, pretrigger ordering and external electrical
  safety remain **NOT RUN**.


## 0.6.0 — 2026-11-11 (P1-06 status and diagnostics, offline-only)

- Add `dmm.status`, `get_error()`, bounded `drain_errors()`,
  non-consuming `diagnostics_snapshot()` with typed identity, IEEE status,
  operation/questionable condition and enable masks, terminal selection and
  optional reading-memory counts.
- Add explicit `*ESR?` / status event read-to-clear methods, ESE/SRE and
  status enable configuration, bounded `*OPC?` and opt-in self-test.
- Preserve existing raw response and error text; reject malformed, negative,
  out-of-bounds and SCPI-injection inputs before any writes.
- Never implicitly call `*CLS`, `*RST`, `*TST?`, `*ESR?`,
  `SYSTem:ERRor?` or status event registers from snapshot/open/close.
- Add scripted transport coverage for error drain limits, event semantics,
  bounded timeouts and no auto-clear, with operator-controlled HIL checklist.
- No physical instrument qualification claimed.


## 0.5.0 — 2026-11-10 (P2-08 state and display)

- Add safe persistent configuration state slots 1–4 with query/validation,
  save, recall, delete, rename, catalog and opt-in power-on restore controls.
- Restrict reserved power-down slot 0 to read-only queries. Refuse state
  overwrites/deletes and live recalls without explicit confirmation.
- Invalidate cached typed measurement/acquisition state after recall.
- Add primary/secondary display visibility/text/clear/getter operations,
  secondary feed query, and explicit beeper state/control.
- Validate slot, state name, display window/text and flags before I/O.
- Add deterministic scripted tests and operator-controlled HIL checklist.
- No automatic reset, instrument clear, state overwrite, NVM deletion
  or network reconfiguration. Physical HIL NOT RUN.


## 0.4.0 — 2026-11-10 (P2-07 instrument math and statistics)

- Add 34411A CALCulate statistics, dB/dBm, limits, enable/disable and
  read-only live math state/thresholds using shared scpi-driver-core.
- Guard destructive statistics clear with `confirm=True`, and refuse
  implicit replacement of a different active math mode.
- Add typed Statistics and Limits records; host limit comparison is not
  represented as a hardware PASS/FAIL register.
- Implement per-function SENSe:NULL offsets, avoiding deprecated CALC:NULL.
- Add positive/negative simulator tests and HIL documentation.
- No state-slot or display functionality in this release; reserved for P2-08.
- Physical 34411A HIL NOT RUN.


## 0.3.2 — 2026-11-10 (P1-03 metrology hardening, offline only)

- Extend the merged v0.3.1 controller with function-specific frequency/period
  AC voltage input-ranging and shared ACV filter control.
- Require explicit NPLC/aperture enable-mode switching under session lock,
  including FRESistance's instrument-specific APERture:ENABle spelling.
- Block temperature autozero on 4-wire RTD or unknown probe state;
  allow only explicitly configured 2-wire RTD/thermistor.
- Add typed pre-read `MetrologySnapshot` to `MeasurementResult.metrology`.
- Extend deterministic input/range, mode conflict, FREQ/PER snapshot and
  metadata tests while retaining all existing USB/LAN/NVM APIs.
- No physical 34411A HIL is claimed.


## 0.3.1 — 2026-11-10 (P1-03 metrology configuration)

- Add function-aware `MetrologyController` accessible as `dmm.metrology`.
- Implement bounded numeric/symbolic manual range, autorange, resolution,
  34411A NPLC and aperture/enable controls, autozero, AC filter bandwidth,
  frequency/period gate time, DC input impedance, resistance offset
  compensation and temperature units.
- Add immutable `MetrologySnapshot` live readback; none of these
  operations silently switches measurement functions, triggers a reading,
  clears instrument status or erases NVM.
- Reject invalid and unsupported mode/value combinations before SCPI writes;
  enforce safe fixed resistance range before enabling offset compensation.
- Add table-driven offline tests, command reference and HIL checklist.
- Preserve v0.3.0 measurement APIs and all USB/VXI-11/TCP/NVM behavior.
- Physical HIL qualification remains **NOT RUN**.


## 0.3.0 — 2026-11-10 (software-only P0-01/P1-02 increment)

- Add typed, model-specific measurement configuration and one-shot read API
  for DC/AC voltage/current, 2-/4-wire resistance, frequency, period,
  capacitance, continuity, diode, 2-/4-wire RTD and thermistor temperature.
- Use scpi-driver-core ScpiClient/ScpiSession for all commands; no new transport.
- Add config validation with no SCPI sent for invalid options, local state
  invalidation on raw commands/close, unit readback for temperature, and
  raw-response/UTC-host-time/overrange metadata.
- Preserve all legacy method signatures, legacy string responses, and USB/LAN
  support; do not implicitly reset, clear, measure or delete NVM data.
- Manual numeric ranges, NPLC/aperture, sensor coefficients and advanced
  triggering are separate follow-up work packages.
- Add deterministic command mapping and negative/failure tests.
- No physical hardware HIL evidence is claimed.


## 0.2.1 — 2026-11-10 (planning-only)

- Add `task/DMM34411A_FULL_FUNCTION_COVERAGE_TASK.md` with a detailed
  P0/P1/P2 execution plan for all remaining common 34411A measurement modes,
  metrology controls, triggers, binary/streamed acquisition, math and status.
- Link the master task from README and flag the v0.1.2 feature matrix as
  historical after the v0.2.0 memory-logging merge.
- **No new instrument commands or measurement functions** in this increment.


## 0.2.0 — 2026-11-10 (memory logging software-only)

- Port buffered measurement acquisition and NVM logging from historical
  PR #1 to the existing scpi-driver-core-backed instrument driver.
- Preserve USB/VXI-11/TCP socket connectivity and original single-reading
  method signatures/return types.
- Add finite acquisition, progress, abort, BUS trigger, volatile/NVM counts,
  guarded copy to initially empty NVM and non-destructive NVM readback.
- No implicit device clear or NVM erase. Deletion requires confirm=True;
  existing NVM blocks start and copy; overwrite remains HIL-gated.
- Add bounded ASCII readback and conservative 20k volatile fetch bound,
  with format restoration and no retry for destructive memory operations.
- Add hardware-free command/safety/failure tests and HIL checklist updates.
- Physical 34411A memory behavior is NOT qualified; full streaming, host
  export and advanced trigger behavior are still open.


## 0.1.3 — 2026-11-10 (audit documentation)

- Add `docs/FEATURE_COVERAGE.md` — hardware-supported vs driver-implemented
  coverage matrix, PR-only NVM features, testing/HIL status, safety blockers,
  and prioritized implementation roadmap.
- Clarify that NVM capture from open PR #1 is not available in the installable
  driver on main, and that hardware qualification remains pending.
- No new instrument commands or measurement features are implemented.


## 0.1.2 — 2026-11-10

- Add from_ethernet() for Keysight 34411A VISA LAN/VXI-11 and TCP socket/5025.
- Use scpi-driver-core VisaTransport/TcpTransport; preserve legacy USB behavior.
- Guard LAN host/protocol/port configuration and socket connect timeouts.
- Add offline loopback socket tests and optional LAN hardware identity smoke test.
- Physical Ethernet bench qualification remains pending.


## 0.1.1 — 2026-11-09 (planning-only)

- Add documented implementation task DMM34411A-NVM-BUFFER-001 for buffered
  measurement acquisition and guarded nonvolatile-memory storage and retrieval.
- No new capture/memory public API has been implemented in this release.


## 0.1.0 — 2026-11-09

Initial versioned package; migration of the original unversioned 2021
`DMM_34411A` driver to `scpi-driver-core` v0.1.0.dev12 (pinned commit).

- Preserve all legacy SCPI method names, commands, and string return types.
- Adopt core VisaTransport, ScpiClient, ScpiSession, finite timeouts, and
  explicit lifecycle; add a source-checkout compatibility shim.
- Remove implicit device clear on open/close; make it an explicit action.
- Add offline scripted, generated command-framing, and PyVISA-sim tests,
  CI workflow, documentation, and a separate physical HIL checklist.
- Historical `GLOBAL_TOUT` constant is retained but not used; new default
  communication timeout is 5 seconds.

Physical USB/VISA qualification is **not** claimed by this release.

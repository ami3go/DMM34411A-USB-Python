# Keysight / Agilent 34411A physical qualification checklist

**Status:** NOT RUN. No hardware evidence is asserted by the migration PR.
The default CI never accesses a physical instrument.

## Preconditions

1. Operator authorizes use of the bench DMM, checks calibration status,
   power and safe test setup, and identifies the exact USB VISA resource
   with Keysight Connection Expert or `pyvisa.ResourceManager().list_resources()`.
2. Confirm VISA backend, USB permissions, cables, and isolation. Never assume
   the historical sample serial belongs to the connected meter.
3. Disconnect sensitive DUTs before changing current/ohm modes. Never apply
   an external voltage source to the DMM current input.
4. Prepare traceable/reference voltage, resistance, and current sources and
   record their uncertainties. Do not infer accuracy from a simulator.
5. Record DMM model, serial, firmware, calibration date, VISA backend,
   USB resource, Python version, driver version and pinned core commit.

## Software gate (no connected hardware required)

```bash
python -m pip install -e ".[test]"
pytest -m "not hardware"
python -m build
```

## Safe initial USB smoke test

With voltage input safely connected and after explicit operator authorization:

```bash
export DMM34411A_VISA_ADDRESS='USB0::0x0957::0x0A07::YOUR_SERIAL::0::INSTR'
pytest -m hardware tests/hardware/test_real_dmm.py -v
```

The smoke test performs *IDN?, DC voltage configuration and a DC voltage
measurement only. Its numeric assertion checks parsability, **not** accuracy.
It does not clear or reset the instrument, calibrate it, or energize a DUT.

## Additional manual mode-by-mode acceptance

| Step | Method(s) | Record |
| --- | --- | --- |
| 1 | `cmd_query("*IDN?")`, `cmd_write("*CLS")` (only if approved) | Identity, command acceptance, error queue |
| 2 | `conf_voltage_dc()`, `cmd_read()`, `measure_voltage()` | Known DC voltage vs uncertainty and integration time |
| 3 | `conf_resistane_2wire()`, `measure_resistnce_2wire()` | Known resistance, leads compensation and stability |
| 4 | `conf_resistane_4wire()`, `measure_resistnce_4wire()` | Known resistance with correct Kelvin wiring |
| 5 | `conf_current_dc()`, `measure_current_dc()` | Rewired current loop, fused input, current reference, limits |
| 6 | Force a bounded query timeout on an isolated simulation first | Exception, faulted transport, explicit reopen, no stale data |
| 7 | `close()` and reopened session | Resource release, no hidden device clear |

Current-mode testing (step 5) is **manual only**, because it requires safe
reconfiguration of the DMM terminals and a bounded external source. Do not
script automatic transitions between voltage and current without a fixture.

## Pass criteria

- Every command accepted by the actual 34411A firmware, no SCPI error-queue
  failures; all readings match reference values within calculated uncertainty.
- No lost, repeated, or stale readings; mode transitions and response framing
  behave as expected for the deployed VISA backend.
- All timeouts are finite, close releases the resource, and the device remains
  in a documented safe state.
- Attach timestamped raw SCPI traces, reference uncertainties and operator
  sign-off before marking HIL as complete.

## Ethernet LAN qualification

**Status: NOT RUN.** These tests require bench authorization; CI only exercises
local TCP simulation and VXI-11 resource construction.

1. Enable LAN and VISA LAN (VXI-11) or SOCKETS on the DMM. Restart/power-cycle
   when instrument service settings require it. Record IP, serial, and firmware.
2. Restrict access to a trusted lab VLAN. Never expose socket port 5025 publicly.
3. Verify the intended instrument IP and expected model/serial independently.
4. With the hardware approved, run
   DMM34411A_LAN_HOST=192.168.0.55 DMM34411A_LAN_PROTOCOL=vxi11
   pytest -m hardware tests/hardware/test_real_lan.py -v
   using a VXI-11-capable VISA backend.
5. Change the protocol environment variable to socket and enable SOCKETS on
   the DMM to qualify the native TCP/5025 connection without VISA.
6. Compare a benign, operator-approved DC voltage reading over USB, LAN
   VXI-11, and LAN socket within stated reference measurement uncertainty.
7. Test a disconnect and reconnection only with bench authorization. Confirm
   no stale responses or implicit retries and explicit open/close behavior.
8. Record raw SCPI traces, driver/core versions, PC environment, operator,
   timeout/reconnect behavior, results, and sign-off.

## Memory acquisition and NVM HIL qualification (v0.2.0)

**Status: NOT RUN; operator authorization required.** The automated suite
uses a scripted device and is not evidence of hardware buffer semantics.

1. Identify 34411A model, serial, firmware and connection (USB/LAN).
   Verify a safely connected low-level DC voltage reference.
2. Query \`DATA:POINts? NVMEM\` and preserve existing log externally.
   Do not clear/erase any preexisting memory without explicit approval.
3. With empty NVM only, configure 3 readings with immediate trigger and a
   conservative timer, run \`start_data_log()\`, wait, copy and read back.
4. Compare the 3 NVM values to the reference and inspect SCPI error queue.
5. Test \`FETCh?\` with three known readings and verify volatile count
   does not decrease. Test \`DATA:REMove? 1\` only with disposable readings,
   record exact order and confirm count change (not tested in CI).
6. Test longer run (1000 samples), bus trigger, abort, capacity boundaries
   only if the bench fixture is qualified.
7. Test NVM persistence across an explicitly approved power cycle.
8. Test \`DATA:DELete NVMEM\` only after host backup and operator approval,
   via \`delete_data_log(confirm=True)\`.
9. Record raw commands and replies, timestamps, model serial/firmware,
   host driver/core versions and calibration uncertainty.
10. Do not mark HIL passed until tests and evidence are reviewed.

Do not silently overwrite existing NVM. \`DATA:COPY\` append/overwrite
semantics when NVM has data remain intentionally unsupported.

## v0.3.0 typed measurement modes — physical acceptance (NOT RUN)

This is an operator-controlled manual qualification matrix, **not an
instruction to automatically cycle modes**. DC/AC current tests require a
properly fused and verified current fixture; resistance, capacitance, diode
and thermistor/RTD tests require deenergized, appropriately wired standards.

1. Record DMM model/firmware/serial, calibration date, probe fixture, USB/LAN
   connection, uncertainty budget, driver version and core commit.
2. DC voltage: compare typed `measure_dc_voltage()` against the historical
   string method on a known safe reference; verify no implicit `*RST` or clear.
3. AC voltage: verify RMS at two traceable frequencies and instrument-selected
   bandwidth setting. Record `MEAS:VOLT:AC?` and numeric uncertainty.
4. Current AC/DC: only after independent current-input wiring authorization.
   Check fuse, range and burden-voltage limits; never switch automatically.
5. Frequency and period: use a known frequency reference, compare to
   source uncertainty and gate-time-dependent resolution.
6. 2-/4-wire resistance: use correctly wired resistance standards.
7. Capacitance, continuity and diode: safe unpowered fixture only; record
   source/excitation behavior and overload thresholds; no live circuits.
8. 2-/4-wire RTD and thermistor: use approved standards; query
   `UNIT:TEMPerature?`, verify probe setup, default coefficient and output units.
9. Test open/overload replies and malformed response detection. Verify the
   physical instrument's overload encoding (+/-9.9E37).
10. Record detailed SCPI traces, expected/actual values, calibration
    uncertainty, PASS/FAIL/NOT RUN and bench approval. Hardware results are
    not inferred from the offline simulator.

Do not qualify numeric range limits, NPLC, aperture or probe coefficient
options until the subsequent metrology implementation/bench work.

## v0.3.1 P1-03 metrology configuration qualification — NOT RUN

Only use an instrument under explicit bench authorization; observe current
terminal protection, correct 2W/4W wiring and reference limits. Use USB
or LAN; do not perform a destructive instrument reset. Record serial,
firmware, calibration status, transport/backend, software/core versions.

1. Verify `set_range` / `get_range` and `set_autorange` /
   `get_autorange` for a known low-voltage DC reference; record nominal
   requested range versus effective readback. Test the DCV high-input-Z
   setting only with a suitably high-impedance safe fixture.
2. Repeat for AC voltage and resistance 2-/4-wire after operator-approved
   fixture change. For current, **separate current input/fuse authorization**
   is mandatory; do not script transition from a powered voltage circuit.
3. Test `set_resolution` and query actual resolution for each eligible
   mode; allow legitimate instrument rounding but not silent mismatch.
4. Test 34411A DCV NPLC 0.001, 0.002, 1, 10, 100 and measure
   acquisition/settling time and repeatability. Do not claim all settings
   achieve rated accuracy at every speed.
5. Test 20 µs, 100 µs, 1 ms, 1 s aperture and query `APERture:ENABled?`;
   verify explicit aperture versus NPLC behavior and rejection on wrong model.
6. Verify `ZERO:AUTO OFF/ON/ONCE` semantics on DCV and 2W resistance,
   including speed versus offset. 4W resistance has autozero permanently on.
7. Verify ACV/ACI bandwidth 3/20/200 Hz with a low-frequency sine source;
   allow documented settling before taking readings.
8. Verify frequency/period gate 1/10/100/1000 ms on a traceable frequency
   reference; compare resolution and uncertainty.
9. Offset-compensated ohms ON/OFF only at fixed 100Ω/1kΩ/10kΩ; check
   disallowed high range/autorange cases and no write on rejection.
10. Verify temperature C/F/K readback with a safe RTD/thermistor standard.
11. Test invalid values, bool-as-number, NaN/Inf, readback anomalies,
   multi-controller interference and connection timeout on an isolated
   simulation before any fault-injection on real equipment.
12. Collect raw SCPI transcript, requested/effective values, uncertainty,
   fixture details, elapsed time, PASS/FAIL/NOT RUN and operator signoff.

No actual hardware has been tested by this PR. Only Python offline CI is
eligible for automated merging.

## v0.3.2 P1-03 hardening HIL checks (NOT RUN)

1. With an approved AC signal source, configure frequency and period
   separately and set the 10 V input range. Read back
   `SENSe:FREQuency:VOLTage:RANGe?`,
   `SENSe:PERiod:VOLTage:RANGe?` and the related `:AUTO?` registers.
   Confirm settings use V, not Hz/seconds, and do not change the
   measurement function by themselves.
2. Verify the frequency/period 3/20/200 Hz filter affects the shared
   AC voltage input filter as documented, with correct readback.
3. DC voltage, resistance 4-wire and RTD 2-wire: set a known NPLC and query
   `:APERture:ENABled?` or FRES `:APERture:ENABle?` to confirm OFF;
   then set aperture and verify it reports ON. Record measurement timing.
4. With a safely wired 4-wire RTD, validate that autozero is always enabled
   and that the driver refuses attempts to disable it. With authorized 2-wire
   RTD/thermistor fixture, qualify ON/OFF/ONCE separately.
5. Test `read_with_settings()`: capture actual pre-read SCPI settings,
   reading value and host timestamp, and ensure one `READ?` only. Do not
   claim device-atomic metadata or per-sample timestamps.
6. Record SCPI error queue without implicit clearing, command transcripts,
   serial, firmware, source accuracy and operator PASS/FAIL/NOT RUN.

## v0.4.0 P2-07 math and statistics HIL plan — NOT RUN

Operator-authorized safe DCV or ACV standard only; no auto-scanning current
input or changing live resistance/diode wiring.

1. Identify firmware/serial, calibration source, active measurement mode,
   current `CALCulate:FUNCtion?` and `:STATe?` before any mutation.
2. With DCV safely configured, enable stats, acquire 3 known readings, query
   average/min/max/SDEV/peak-to-peak/count, compare with offline computation.
3. Invoke enable_stats a second time: verify that same-mode idempotent
   API call does not clear counters. Then explicitly clear statistics with
   operator approval and `confirm=True`; verify counter returns to zero.
4. Attempt enabling a different math mode with no `replace=True`; verify
   it is rejected with **zero write operations**. Confirm `replace=True`
   changes mode and note accumulator loss.
5. dB and dBm: verify known voltage and valid resistor reference with expected
   logarithmic math. Confirm invalid and unapproved reference values rejected.
6. Limits: configure lower/upper and validate instrument annunciator and
   host-side comparison separately. Verify no fabricated SCPI hardware
   pass/fail query. Confirm limits clear on function change per manual.
7. Per-function null: verify `SENSe:VOLTage:DC:NULL:VALue/STATe` readbacks;
   confirm independent null remains compatible with active math function.
8. Capture actual SCPI transcript, source uncertainty, error queue,
   actual values and PASS/FAIL/NOT RUN. Never claim HIL from simulator.

## v0.5.0 P2-08 configuration states/display HIL checklist — NOT RUN

Physical authorization required; run only on a disconnected/safe DMM fixture
with any existing configuration states and NVM readings backed up.

1. Record the model, firmware, serial, connection, current measurement
   function, trigger configuration, state catalog, four slot names and
   power-on auto-recall state. Preserve existing data.
2. Pick an unused user slot 1–4. Save current known safe DCV state and
   validate `MEM:STAT:VALid?`, name, metadata and state catalog.
3. Test deliberate re-save refusal without overwrite and dual confirmation;
   never overwrite another operator's saved slot without a full backup.
4. Recall after making an explicitly approved benign configuration change;
   validate restored state and no blind restart of an acquisition. Do not
   connect a powered DUT or unprotected current loop.
5. Rename using an allowed <=12 ASCII name, query the name. Delete only
   the disposable slot with `confirm=True`, verify it becomes invalid.
6. Query power-on auto/selected slot. Changing persistent power-on behavior
   may be prohibited in shared lab environments; if not authorized, leave it
   NOT RUN, do not switch the meter off/on.
7. On primary/secondary display: query visibility, set temporary text and
   clear it. Check the front-panel readability and state readback.
8. Query secondary feed without changing it. Optionally exercise the
   beeper and beeper state only if audible operation is authorized.
9. Verify open/close sends only IDN, no *RST, *CLS, *SAV, *RCL, display,
   state deletion or NVM write. Document raw SCPI/errors and all results.

## v0.6.0 P1-06 status and diagnostics HIL checklist (NOT RUN)

1. Record operator authorization, model/serial/firmware, 34411A options,
   driver/core SHAs, transport backend, fixture, power and risk assessment.
2. Open and take `diagnostics_snapshot(include_memory=True)` on a safe
   idle bench. Capture STB, ESE, SRE, OPERATION/QUESTIONABLE condition+enable,
   SCPI version and `ROUTe:TERMinals?`; verify no *CLS/*ESR?/ERR? occurred.
3. Independently inspect any pre-existing error queue and event evidence
   before authorizing **consumptive** `get_error()` or `drain_errors()`.
4. Introduce one benign deliberate invalid command only with operator
   approval; check error code/message parsing, bounded drain and sentinel.
5. Verify status event registers and standard event register only in a
   disposable session where read-to-clear behavior is explicitly accepted.
6. Test enable-mask and SRQ behavior without active DUT or safety interlocks
   depending on the same status. Restore prior settings deliberately.
7. Run bounded `*OPC?` only with no long-running acquisition and check a
   simulated timeout first. Self-test `*TST?` is separately authorized:
   it may be slow/disruptive and may invalidate instrument configuration.
8. Verify no automatic reset, clear, reading-memory deletion or retry.
   Attach raw SCPI logs, PASS/FAIL/NOT RUN and calibrated bench evidence.


## v0.7.0 P1-04 internal trigger, pretrigger and STOP HIL (NOT RUN)

1. Verify actual instrument identity is 34411A (not 34410A), record
   firmware, calibration, driver SHA and exact source/transport wiring.
2. Use isolated low-voltage source with known waveform, common ground and
   bounded current. Select DCV only; test current/ohms triggers **only**
   with separate operator approval and correct fuse/fixture.
3. With rising then falling waveform crossing, configure
   `TRIGger:SOURce INTernal`, distinct levels and POS/NEG slopes.
   Check SCPI acceptance and query TRIGger:LEVel? and TRIGger:SLOPe?.
4. Run pretrigger counts 0, 1 and 100 for 1000 per-trigger readings;
   compare pre/post sample ordering to a simultaneous oscilloscope capture.
5. Run finite trigger count 2 and 3, confirm exact count = samples ×
   events, no stale buffer readings, and no NVM erasure.
6. Drive an EXT trigger with **no event**. Wait with a short deadline,
   verify timeout marks UNKNOWN and does not silently send ABORt or
   start another acquisition. Explicitly call stop_acquisition and
   confirm partial count and safe reconciliation.
7. Qualify trigger-output polarity electrically with a properly isolated,
   voltage-rated scope before using any connected DUT.
8. Verify transport fault during INIT/ABORt and forced disconnect in
   simulation first; any uncertain operation requires manual reconciliation.
9. Attach raw SCPI transcript, traceable latency and pretrigger ordering
   data, uncertainty budget, operator PASS/FAIL/NOT RUN and bench signoff.


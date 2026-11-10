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

## v0.4.0 — P1-03 metrology HIL qualification (NOT RUN)

**Precondition:** This is an operator-controlled, non-automated checklist.
Do not change meter functions or instrument terminals with a live DUT. Use
calibrated DC voltage, AC voltage, resistance, current and frequency sources
with recorded uncertainty, source limits and fixture authorization.

1. Record actual 34411A serial/firmware, reference standards, environmental
   conditions, calibration status, VISA/LAN interface and driver/core versions.
2. On safe DC voltage input: configure DCV explicitly and test manual
   0.1/1/10 V ranges and autorange, query each effective `SENSe:VOLT:DC:RANGe?`
   and `:AUTO?`; evaluate actual behavior vs reference, not requested value.
3. Set NPLC = 0.001, 0.02, 1, 10, 100 (where supported); verify readback,
   aperture mode disabled and effects on noise/speed/line-frequency rejection.
4. Set aperture = 20 µs, 100 µs, 1 ms, 0.1 s, 1 s; verify `:APER:ENAB?`,
   measured acquisition duration, noise and resolution.
5. Verify autozero ON/OFF/ONCE and DC input impedance automatic HI-Z behavior
   against a known source/load. Record reading differences and burden.
6. On authorized ACV source: compare 3/20/200 Hz filter settings using 10,
   100 and 1000 Hz signals; record measured settling time and accuracy.
7. Frequency/period: compare 1/10/100/1000 ms gate settings against a
   reference source; verify readback and uncertainty.
8. Ω 2W/4W: after connecting passive standards, test autorange/manual,
   resolution, NPLC/aperture; test offset compensation on 100 Ω, 1 kΩ,
   10 kΩ fixed ranges only, verify out-of-range refusals.
9. Temperature autozero: only with connected approved 2-wire RTD or thermistor;
   confirm 4-wire mode cannot be altered.
10. Current mode settings require **separate operator authorization**,
    a fused current input and safe rewiring. Do not automate transitions.
11. For each test, record SCPI transcript, requested and queried settings,
    source value, measured value, uncertainty, status/error queue and
    PASS/FAIL/NOT RUN. Repeat on available USB, VXI-11 and socket transports
    if the bench supports them.
12. Do not declare any hardware command qualified until actual results exist.

Relevant Keysight User Guide pp. 52–59: NPLC, aperture, impedance, AC filter,
frequency gate, autozero and ranging behavior. CI mock acceptance is not HIL.

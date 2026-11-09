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

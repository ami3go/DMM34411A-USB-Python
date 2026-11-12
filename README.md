# Keysight / Agilent 34411A Python Driver

A synchronous Python driver for the 34411A digital multimeter, migrated from
direct PyVISA calls to [scpi-driver-core](https://github.com/ami3go/scpi-driver-core).

**Version: 0.8.6** (the original 2021 code had no package version). The core
dependency is pinned to a reviewed commit of development version 0.1.0.dev12.

## v0.8.6 — Exclusive binary transfer ownership (P0)

`dmm.transfer` now owns the canonical reentrant core SCPI operation lock
from buffer count check through format selection, IEEE binary reads and
restoration. No other thread using the same `dmm.client` can interleave
raw commands or change `FORMat:DATA` during an active binary transaction.

**Destructive stream lifetime:** `iter_destructive_chunks()` holds this
lock **across yielded chunks**, not only during individual SCPI calls.
Always exhaust it or explicitly close it (prefer `contextlib.closing`).
A caller that leaves a generator suspended will block other instrument I/O
until the generator is closed. To cancel without sending any instrument
command, call `dmm.transfer.request_cancel()`; it will stop before the
next `DATA:REMove?` and mark partial acquisition state UNKNOWN.
An explicit `abort_acquisition()` also signals cancellation before
waiting to send the single operator-commanded `ABORt`.

Confirmed removed-reading counts are committed **before yielding**
each chunk. Abandoned streams mark the instrument's local acquisition
state UNKNOWN. After uncertain/cancelled draining, do not restart
the destructive read without independent instrument-state reconciliation.
This is offline-validated concurrency behavior; real USB/LAN HIL is NOT RUN.

## v0.8.5 — Thread-safe acquisition transitions (P0)

`AcquisitionController` now serializes **state validation + instrument
command + local state commit** through the shared core session operation
lock. Concurrent INIT, *TRG, ABORt, raw SCPI and NVM COPY cannot interleave
partway through a typed acquisition transition. A STOP request wakes an
in-progress `wait_complete()` between instrument polls; no automatic
ABORt is sent by a timeout or cancellation.

`wait_complete()` does **not** hold the lock across sleeping, preserving
STOP responsiveness. Individual SCPI transactions remain bounded by their
timeouts. A STOP requested during `*OPC?` prevents marking a run COMPLETE.
This is thread-level software qualification; actual instrument stop latency
and response semantics still require physical HIL.

## Transport support and project naming

This is a **transport-independent SCPI driver** for the Keysight / Agilent
34411A digital multimeter. The transport is selected by how the instrument is
connected; the same high-level Python API works across these interfaces.

| Connection | Supported transport | Python connection |
| --- | --- | --- |
| USB | USBTMC through VISA | `DMM_34411A(resource_name="USB0::...::INSTR")` |
| Ethernet | LAN VXI-11 through VISA | `DMM_34411A.from_ethernet("192.168.0.100", protocol="vxi11")` |
| Ethernet | Raw SCPI over TCP, default port 5025 | `DMM_34411A.from_ethernet("192.168.0.100", protocol="socket")` |

The transport abstraction is supplied by
[`scpi-driver-core`](https://github.com/ami3go/scpi-driver-core).
**Live instrument qualification is still outstanding** for USB and LAN; CI
uses simulated transport behavior.

**Repository and package naming:** The repository is currently
[`ami3go/DMM34411A-USB-Python`](https://github.com/ami3go/DMM34411A-USB-Python).
A transport-neutral repository name, **`DMM34411A-Python`**, is recommended
but is **not renamed yet**. After the repository owner renames it in GitHub
Settings, this repository link can be updated to the new canonical location.
The installed distribution name remains `dmm34411a-usb-python` for
backward compatibility, while the Python import name is **`dmm34411a`**.
Renaming a GitHub repository does not require changing either package name.

## v0.8.3 Opt-in HIL evidence runner (safe dry run by default)

The built-in HIL runner **does not connect to any instrument** without
an explicit double authorization, a resource address, operator/fixture
identification and an unused evidence destination.

```bash
# Safe planning only: prints 11 cases, each NOT_RUN. No hardware I/O.
python -m dmm34411a.hil

# Only after physical bench authorization, on your own PC:
export DMM34411A_HIL_APPROVED=YES
python -m dmm34411a.hil --authorize \
  --operator BENCH_OPERATOR --fixture APPROVED_DCV_FIXTURE \
  --resource 'USB0::0x0957::0x0A07::YOUR_SERIAL::0::INSTR' \
  --output hil-evidence/run001

# Optional safe 1.25V DC reference (separate fixture approval required):
python -m dmm34411a.hil --authorize --dcv-smoke \
  --safe-dcv-fixture --reference-volts 1.25 --tolerance-volts 0.01 \
  --operator BENCH_OPERATOR --fixture SAFE_1_25V_REFERENCE \
  --resource 'USB0::0x0957::0x0A07::YOUR_SERIAL::0::INSTR' \
  --output hil-evidence/run002
```

Create `hil-evidence/` locally beforehand; the chosen run directory must
**not** exist. The runner captures raw SCPI query/write commands and replies
in `transcript.jsonl`, plus `report.json` containing SHA-256, IDN,
status snapshot, operator/fixture, timestamps and explicit case statuses.
The passive run issues `*IDN?` and read-only status/memory count queries;
it never drains the error/event queues or clears NVM. The optional DCV
smoke selects **DC voltage only** and reports a provisional result against
your supplied tolerance; it is not accuracy calibration or full HIL
qualification. All other cases remain `NOT_RUN` until independently
qualified. See `docs/HIL.md` for the complete checklist.

## v0.8.2 Offline qualification and stress CI

The normal Python 3.10–3.13 matrix runs all hardware-free tests except
the dedicated stress category, emits coverage and enforces a baseline,
checks critical Ruff lint/syntax rules, and installs the built wheel
for import/version verification. A separate Python 3.12 job tests bounded
REAL32/64 blocks with 1, 50,000, 100,000 and **1,000,000** readings plus
CSV+SHA256 export of 50,000 readings.

```bash
pytest -m "not hardware and not stress" --cov=dmm34411a --cov-fail-under=70
pytest -m "stress and not hardware" -o timeout=180
ruff check --select E4,E7,E9,F821,F822,F823 dmm34411a tests
```

All stress results remain **simulated protocol verification**, not
physical throughput or timing evidence.

## v0.8.1 P0 safety and export recovery

The instrument must be ARMED by `start_acquisition()` before
`send_bus_trigger()` or `wait_complete()` can accept readings; this
prevents stale buffered samples being mistaken for a new run. Raw SCPI
commands invalidate the typed run's completion evidence. A completed
NVM copy is latched against a second `DATA:COPY`, even when completion
was uncertain; a new operator-reviewed acquisition is required.

If a destructive export fails **after confirmed rows were removed**, the
driver raises the original exception with `partial_directory` and
`confirmed_csv_rows` attributes and saves an INCOMPLETE CSV+JSON
bundle with SHA256 in a `<destination>.partial.<random>` directory.
The current interrupted chunk can be consumed despite an exception:
**do not automatically repeat it**. Reconcile instrument counts first.

## P1-05 — High-speed binary capture and host export (v0.8.0)

The new `dmm.transfer` extends the existing instrument acquisition
engine and uses the **pinned scpi-driver-core IEEE-488.2 definite-length
binary block parser**. No new transport or parallel acquisition engine.

```python
from dmm34411a import DMM_34411A

# Operator-approved low-voltage fixture; start/complete capture separately.
with DMM_34411A(resource_name="USB0::...::INSTR") as dmm:
    dmm.configure_dc_voltage()
    dmm.configure_volatile_acquisition(50000, trigger_source="IMMEDIATE")
    dmm.start_acquisition()
    dmm.acquisition.wait_complete(timeout_s=120)
    # Bounded full binary fetch (max 8 MB payload for 1M × REAL64):
    raw = dmm.fetch_volatile_binary(precision_bits=32)
    print(raw.samples, list(raw.readings())[:5])  # demo only; avoid 1M list
    receipt = dmm.export_volatile_bundle(
        "capture_001", destructive=False, precision_bits=32
    )
    print(receipt.readings_file, receipt.metadata_file, receipt.sha256)
```

| Capability | API | Memory / safety |
| --- | --- | --- |
| Full non-destructive binary fetch | `fetch_volatile_binary(precision_bits=32|64)` | Uses `FETCh?`, exact length, <=8MB payload max |
| Lazy IEEE-754 decode | `BinaryCapture.readings()` | Iterator; REAL32 and REAL64 with verified big-endian `NORM` |
| Explicit destructive chunked drain | `transfer.iter_destructive_chunks(max_points=n,chunk_size=10000)` | `DATA:REMove? n`, max 100k values per chunk, no retry |
| Atomic host export | `export_volatile_bundle("new_folder",destructive=False)` | New directory with CSV+JSON published with a single rename |
| Explicit destructive export | `export_volatile_bundle(...,destructive=True,max_points=n)` | Consumes requested readings; never implicit |
| Integrity/provenance | `ExportReceipt`, JSON metadata | SHA-256 of CSV, count, overrange, IDN, firmware, transport, core+driver version, function and nominal interval |

**Safety contracts**

- No source `R?` command is sent: its NVM/volatile retention implications
  require operator HIL verification. No NVM buffer overwrite/clear is added.
- Non-destructive `FETCh?` is one bounded binary block, not a giant Python
  `list[float]`. Destructive drains are distinct and explicit, with
  verified `DATA:POINts? RDG_STORE` decrement after each chunk.
- Binary framing uses the pinned core `query_binary_block()`. The module
  selects `FORMat:DATA REAL,32/64` and `FORMat:BORDer NORMal` (big-endian),
  verifies readback, and **restores previous settings** on connected exit.
  If the stream is faulted/disconnected restoration cannot be assured.
- No silent retry after uncertain destructive `DATA:REMove?`; the driver
  marks acquisition UNKNOWN and raises `TransferUncertainError` containing
  the number of *confirmed* removed readings. The unknown current chunk may
  have been consumed; reconcile physically before another drain.
- CSV fields are `index,reading,overrange`; real 9.9E37 overload sentinel
  becomes an empty reading with overrange=1. NaN/Inf payloads are rejected.
  Each bundle contains JSON metadata with SHA-256 and source identity.
- **No invented per-sample timestamps**. The JSON distinguishes nominal
  sample interval from actually captured per-sample timebase.
- Only a *new* export directory is accepted, and staging is published by
  one rename. Existing exports are never intentionally overwritten.
- The Python API implements the protocol and passes simulation tests; the
  physical instrument's binary block terminator, byte order, firmware
  limits, FETCh retention and high-speed throughput remain **HIL NOT RUN**.

## P1-04 — Advanced 34411A triggering (v0.7.0)

This extends the existing `AcquisitionController` and preserves
`start_acquisition()`, `wait_for_data_log()`, `abort_acquisition()` and
NVM retention behavior. It adds *software-only* support for instrument
internal crossing trigger, pretrigger and finite multiple-trigger bursts.

```python
from dmm34411a import DMM_34411A, AcquisitionState

# This command sequence requires operator-approved DC voltage input wiring.
with DMM_34411A(resource_name="USB0::...::INSTR") as dmm:
    dmm.configure_dc_voltage()
    dmm.configure_volatile_acquisition(
        points=1000, trigger_source="INTERNAL", trigger_level=1.5,
        trigger_slope="POS", trigger_count=2, pretrigger_count=100,
        sample_interval_seconds=0.0001,
    )
    print(dmm.acquisition.trigger_settings_raw())  # read-only
    dmm.start_acquisition()
    # Waiting is deadline-bound. Timeout leaves UNKNOWN; requires explicit
    # reconciliation/ABORt before any new configuration.
    count = dmm.acquisition.wait_complete(timeout_s=60.0)
    assert dmm.acquisition.state is AcquisitionState.COMPLETE
    print(count, dmm.acquisition_progress_snapshot())
```

**Contracts and restrictions:**

- Only an IDN-verified **34411A** may use internal/pretrigger mode.
  `INTERNAL` requires an explicitly configured **AC/DC voltage, AC/DC
  current, or 2-/4-wire resistance** function and finite trigger level.
  Diode, continuity, frequency, period, capacitance and temperature are
  explicitly rejected for internal triggering.
- `pretrigger_count` must be a nonnegative integer smaller than samples
  per trigger. A positive value requires an event trigger and known compatible
  mode. For immediate triggering, positive pretrigger is rejected.
- `trigger_count × points` must not exceed **1,000,000 volatile readings**
  or **50,000 NVM readings** (for logging). The return of
  `configure_volatile_acquisition()` remains the per-trigger point count,
  preserving backward compatibility. Progress target is the combined total.
- Local `AcquisitionState` values are IDLE, CONFIGURED, ARMED, COMPLETE,
  ABORTED, FAULTED and UNKNOWN. These are *host-local*, not a replacement
  for actual instrument status. A read/command timeout leaves UNKNOWN and
  no implicit `ABORt` or retry is issued. Use `stop_acquisition()` to
  request one explicit ABORt and query the remaining count.
- `set_level_trigger(level,slope)` adjusts a previously configured,
  non-armed acquisition. `set_trigger_output_slope(slope)` changes the
  electrical output polarity and requires fixture-specific hardware approval.
- `trigger_settings_raw()` queries TRIG:SOUR?, TRIG:COUN?, SAMP:COUN? and
  SAMP:COUN:PRETrigger?. Neither a software state nor an `*OPC?` reply
  establishes trigger latency or per-sample timebase; **real HIL required**.
- Default legacy calls retain their previous command sequence and behavior.
  After positive pretrigger is configured in the same session, a subsequent
  configuration explicitly resets it to zero to prevent stale pretrigger setup.

## P1-06 — SCPI status and diagnostics (v0.6.0)

The `dmm.status` controller uses the existing `scpi-driver-core` session.
Instrument error queues and IEEE event registers have **read-to-clear**
semantics; diagnostic snapshots do **not** consume them.

```python
from dmm34411a import DMM_34411A

with DMM_34411A(resource_name="USB0::...::INSTR") as dmm:
    snapshot = dmm.diagnostics_snapshot()  # no error queue drain
    print(snapshot.model, snapshot.firmware, snapshot.status_byte)
    print(snapshot.operation.condition, snapshot.questionable.condition)
    # Explicit consumptive operations (only when operator approves):
    errors = dmm.drain_errors(max_errors=16)
    print(errors.errors, errors.exhausted)
```

| Function | API | Side effect |
| --- | --- | --- |
| One SCPI error | `get_error()` | Dequeues exactly one queue entry |
| Bounded SCPI errors | `drain_errors(max_errors=32)` | Dequeues up to limit; `exhausted=True` means more may remain |
| IEEE status byte | `status.status_byte()` | Query only |
| IEEE event enable | `standard_event_enable()/set_standard_event_enable(mask)` | Explicit enable configuration |
| IEEE service request | `service_request_enable()/set_service_request_enable(mask)` | Explicit SRQ mask; reserved bit 6 rejected |
| IEEE event register | `status.standard_event_register()` | **Consumes** events |
| Operation/Questionable condition | `status.condition(bank)` | Non-consuming |
| Operation/Questionable event | `status.event(bank)` | **Consumes** events |
| Operation/Questionable enable | `status.enable(bank)/set_enable(bank,mask)` | Explicit configuration |
| Diagnostic snapshot | `diagnostics_snapshot(include_memory=False,include_system=True)` | IDN metadata, STB/ESE/SRE, operation/questionable condition+enable, version/terminals; optional volatile/NVM counts |
| Completion barrier | `status.operation_complete(timeout_s=30)` | Explicit bounded `*OPC?`, never startup |
| Self-test | `status.self_test(confirm=True,timeout_s=120)` | **Potentially disruptive**, invalidates local measurement/acquisition state |

Important: status snapshots are ordered host queries, **not** hardware-atomic
state records. `ROUTe:TERMinals?` reports terminal selector position but
cannot move the selector. All error/event consumption and self-test must be
operator controlled when historical evidence must be preserved.

## Installation

Requires Python 3.10+ and a working VISA backend capable of reaching the DMM
(e.g. Keysight IO Libraries or NI-VISA on Windows, or a supported USBTMC backend
on Linux). A simulator is sufficient for the default test suite.

```bash
python -m pip install -e .
python -m pip install -e ".[test]"     # optional offline test suite
```

The runtime dependency is installed from the pinned GitHub commit of
`ami3go/scpi-driver-core`; Git and network access are required for initial
installation. The driver does not vendor, fork, or duplicate core transport logic.

## Use

```python
from dmm34411a import DMM_34411A

address = "USB0::0x0957::0x0A07::YOUR_SERIAL::0::INSTR"
with DMM_34411A(resource_name=address, timeout_s=10.0) as dmm:
    print(dmm.idn)
    dmm.conf_voltage_dc()
    print(dmm.cmd_read())        # string as in original driver
    print(dmm.measure_voltage())
    reading = dmm.client.query_float("READ?")  # optional typed core API
```

For scripted simulation, pass `transport=ScriptedScpiTransport(...)`. Pass
`auto_open=False` to defer opening. The default address constant from the old
code is still available but contains the serial number of a particular device:
**always select the real bench address**.

The old source-checkout import
`from src.DMM34411A_class import DMM_34411A` continues to work when running
from the repository root. Installed clients should import `dmm34411a`.

## Ethernet / LAN connections

The Keysight 34411A supports VISA LAN/VXI-11 and raw SCPI sockets on TCP/5025.
Enable the corresponding LAN service using the instrument front panel
(UTILITY MENU > REMOTE I/O > LAN). If LAN services are changed, power-cycle
the instrument as described in its User's Guide.

VXI-11 uses a LAN-capable VISA backend (Keysight IO Libraries, NI-VISA, or
a supported pyvisa-py installation). It is the default Ethernet protocol:

    from dmm34411a import DMM_34411A

    with DMM_34411A.from_ethernet("192.168.0.55") as dmm:
        print(dmm.idn)
        print(dmm.measure_voltage())

Equivalently, pass the full VISA resource name directly:

    with DMM_34411A(resource_name="TCPIP0::192.168.0.55::inst0::INSTR") as dmm:
        print(dmm.idn)

A direct TCP socket needs no VISA backend:

    with DMM_34411A.from_ethernet(
        "192.168.0.55", protocol="socket", port=5025,
        connect_timeout_s=3.0, timeout_s=5.0,
    ) as dmm:
        dmm.conf_voltage_dc()
        print(dmm.cmd_read())

The direct socket protocol sends LF-terminated ASCII commands and requires
LF-terminated replies. Timeouts are finite; interrupted queries fault the
transport to avoid stale reads. Socket transport does not provide VISA device
clear (calling device_clear raises UnsupportedOperationError).
Opening only sends *IDN? and never resets, clears, or starts measurements.

Use auto_open=False to construct a transport without opening the connection.
Provide an IPv4 address or DNS hostname, not a URL or full VISA resource,
to from_ethernet. Keep the instrument on an isolated lab VLAN: SCPI socket
connections are unencrypted and must not be exposed to the public Internet.

Official manuals: [34410A/11A user guide](https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf)
and [LAN 34411A VXI-11/Socket examples](https://hpwiki.mcguirescientificservices.com/_media/application_notes%3Aan-1465-25.pdf).
LAN real-hardware qualification is pending; see docs/HIL.md.

## Supported and missing functions

See the [34411A driver feature coverage matrix](docs/FEATURE_COVERAGE.md) for
a source-audited comparison of the instrument's capabilities and this driver's
implemented, partial, missing and PR-only features. Version 0.1.3 adds
documentation, **not** new instrument functions.

## Preserved legacy methods

| Config / control | Read / measurement |
| --- | --- |
| `conf_voltage_dc()` | `cmd_read()` |
| `conf_resistane_4wire()` | `measure_voltage()` |
| `conf_resistane_2wire()` | `measure_resistnce_4wire()` |
| `conf_current_dc()` | `measure_resistnce_2wire()` |
| `cmd_write(text)` | `measure_current_dc()`, `cmd_query(text)` |

Historical misspellings are retained intentionally. All existing measurement
methods still return **strings**, not floats. Existing command spelling and
arguments were preserved exactly; actual instrument syntax must be checked
with HIL before claiming hardware coverage.

## Operational changes

- `VisaTransport` owns the PyVISA resource; `ScpiClient` handles SCPI framing
  and operations; `ScpiSession` owns lifecycle and connection health.
- Timeouts use **seconds**: `timeout_s=5.0` by default instead of the old
  hardcoded 10 ms. `GLOBAL_TOUT=10` remains importable only for compatibility.
- Opening still probes `*IDN?`, but no longer prints to stdout.
- Opening and closing **do not issue VISA device clear**. Use
  `dmm.device_clear()` explicitly, only when it is safe to abort acquisitions.
- The raw PyVISA `app` and `rm` objects are not part of the migrated interface.
  Advanced calls should use `dmm.client`, `dmm.session`, or `dmm.transport`.
- The shared transport faults on communication timeouts to prevent stale
  responses being used as subsequent readings; do not blindly retry
  `READ?` or `MEASure?` because they can trigger a measurement.

## Validation

```bash
python -m pip install -e ".[test]"
pytest -m "not hardware"
python -m build
```

Automated tests cover legacy commands, return types, connection lifecycle,
framing, fault handling, and the real core-to-PyVISA-to-PyVISA-sim path.
All are hardware-free. The real USB/VISA instrument remains a separate
qualification gate; see [the HIL checklist](docs/HIL.md).

The bundled `Docs/34410A_Quick_Reference.pdf` is retained for historical
reference; it is not a substitute for 34411A HIL verification.

## P1-03 — Metrology configuration (v0.3.1)

`DMM_34411A.metrology` exposes function-aware `SENSe` control on the
**existing selected instrument**. It does not change the measurement
function, initiate acquisition, reset, clear errors or modify NVM.

```python
from dmm34411a import DMM_34411A, MeasurementFunction as F

# Configure the meter using an operator-authorized benign voltage fixture.
with DMM_34411A.from_ethernet("192.168.0.55", protocol="socket") as dmm:
    dmm.configure_dc_voltage()
    dmm.metrology.set_range(F.DC_VOLTAGE, 10.0)  # volts; rounds to supported range
    dmm.metrology.set_autorange(F.DC_VOLTAGE, False)
    dmm.metrology.set_nplc(F.DC_VOLTAGE, 10)
    dmm.metrology.set_autozero(F.DC_VOLTAGE, True)
    actual = dmm.metrology.snapshot(F.DC_VOLTAGE)
    print(actual.range_value, actual.nplc, actual.autozero)
    result = dmm.measurement.read()  # READ?; typed result in volts
    print(result.value, result.unit)
```

Supported methods (all instrument readbacks come from live SCPI queries):

| Method | Modes | Valid inputs and semantics |
| --- | --- | --- |
| `set_range`, `get_range` | DC/AC V, DC/AC I, 2-/4-wire Ω, capacitance | SI numeric within model range or `MIN/MAX/AUTO`; instrument may select next available range |
| `set_autorange`, `get_autorange` | same | strict `bool` |
| `set_resolution`, `get_resolution` | DC/AC V, DC/AC I, 2-/4-wire Ω | positive SI numeric, `MIN/MAX/DEF`; readback reports actual resolution |
| `set_nplc`, `get_nplc` | DCV/DCI/Ω/temperature | `0.001/0.002` (34411A only), `0.006/0.02/0.06/0.2/1/2/10/100`, or `MIN/MAX/DEF` |
| `set_aperture`, `get_aperture` | DCV/DCI/Ω/temperature | 20 µs–1 s (20–100 µs requires verified 34411A ID), or `MIN/MAX/DEF` |
| `set_aperture_enabled`, `get_aperture_enabled` | DCV/DCI/Ω/temperature | strict `bool`, explicitly selects aperture mode; setting an NPLC or aperture value alone does not silently toggle it |
| `set_autozero`, `get_autozero` | DCV/DCI/2-wire Ω/temperature | `True/False/"ONCE"`; 4-wire Ω has fixed automatic autozero |
| `set_ac_bandwidth`, `get_ac_bandwidth` | ACV/ACI | 3, 20, 200 Hz or `MIN/MAX/DEF` |
| `set_gate_time`, `get_gate_time` | frequency/period | 0.001, 0.01, 0.1, 1 s or `MIN/MAX/DEF` |
| `set_input_impedance_auto`, `get_input_impedance_auto` | DCV only | HI-Z on lower DCV ranges; `bool` |
| `set_offset_compensation`, `get_offset_compensation` | 2-/4-wire Ω | ON only with fixed 100 Ω/1 kΩ/10 kΩ range verified by instrument queries |
| `set_temperature_unit`, `get_temperature_unit` | temperature | `C/F/K` |
| `snapshot(function)` | supported modes | immutable `MetrologySnapshot` of effective live settings; fields not valid for mode are `None` |

**Safety and metrology:** no front-panel/DUT terminal switching. Ohms,
capacitance and current modes require approved wiring and an appropriate
reference source. NPLC, aperture, resolution, filter selection, input
impedance and offset compensation affect settling time and measurement
uncertainty. `snapshot(function)` does not change the active function and
does not assert physical calibration. Its multiple SCPI queries are
serialized within the driver's session, but cannot exclude changes from
another instrument controller.

**Compatibility:** legacy API and `measurement.read()` remain available.
A `SENSe` metrology setting does not invalidate the active measurement
*function*; it adjusts that function's effective settings. If you use raw
`dmm.client` calls to change active mode, reconfigure before reading.

**Hardware HIL status:** not run. See the detailed
[HIL checklist](docs/HIL.md) and [SCPI matrix](docs/SCPI_COMMAND_COVERAGE.md).
Official source references are linked there.

## P2 instrument configuration slots and display (v0.5.0)

The driver exposes two new explicit controllers: `dmm.storage` for
nonvolatile **instrument configurations**, and `dmm.display` for the front
panel. Stored configuration slots are **not** the NVMEM reading/data logger.

```python
from dmm34411a import DMM_34411A

with DMM_34411A.from_ethernet("192.168.0.55", protocol="socket") as dmm:
    print(dmm.storage.list_states())  # 1–4, queries only
    dmm.storage.save_state(1)         # refuses to overwrite existing state
    dmm.storage.rename_state(1, "CAL_STD")
    # *RCL can change the measurement function/trigger configuration.
    dmm.storage.recall_state(1, confirm=True)
    dmm.display.set_text(2, "TEST READY")
    dmm.display.clear_text(2)
```

**State safeguards:** Slots 1–4 are writable; slot 0 is reserved for
power-down state and is available only for read-only status queries.
`save_state(slot,overwrite=True,confirm=True)` is required if an existing
slot is occupied. `delete_state(slot,confirm=True)` deletes a stored
configuration, not NVM measurement data. `recall_state(slot,confirm=True)`
can change live measurement mode and invalidates the local typed-measurement
and acquisition state caches. It never automatically retries after an
uncertain timeout.

Power-on configuration is persistent and can change subsequent startup
behavior. `get_power_on_state()` queries selection and enabled state.
`set_power_on_recall(True, slot, confirm=True)` only accepts a valid
nonempty user slot; `set_power_on_recall(False, confirm=True)` disables
automatic recall. **Disabling auto-recall may change the startup behavior
to factory defaults**. These operations are never called implicitly.

`dmm.display` provides `set_enabled/get_enabled(window)`,
`set_text/get_text(window)`, `clear_text(window)` for windows 1 and 2,
`get_secondary_feed()` (query only), and explicit beeper controls. The
text setter uses a conservative safe ASCII subset (1–12 chars) to prevent
SCPI injection; this is a driver restriction, not a claim about the physical
display capacity. Secondary-feed selection remains read-only until the
firmware-specific allowed feed tokens are qualified.

No display, state, power-on or beeper configuration is changed on connect
or close. All new functions are **offline-tested only**; physical HIL is
**NOT RUN**. See the [SCPI matrix](docs/SCPI_COMMAND_COVERAGE.md) and
[physical checklist](docs/HIL.md).

## P2 math and statistics (v0.4.0)

Use `dmm.math` for 34411A instrument-side CALCulate math and per-function
null. No math is enabled or cleared at construction/open/close; it is
**not safe** to assume enabling statistics preserves the previous accumulator.

```python
from dmm34411a import DMM_34411A

with DMM_34411A.from_ethernet("192.168.0.55", protocol="socket") as dmm:
    dmm.configure_dc_voltage()             # requires an approved DCV fixture
    dmm.math.enable_statistics()           # first activation clears old statistics
    # Take readings separately with dmm.measurement.read() or instrument acquisition
    stats = dmm.math.read_statistics()     # count, mean, min/max, stddev, p-p
    dmm.math.configure_limits(-1.0, 1.0, replace=True)
    print(dmm.math.get_limits())           # reads instrument thresholds
    print(dmm.math.evaluate_limits(0.5))  # host-side comparison, not DMM pass/fail
```

The 34411A supports one `CALCulate` math function at a time: statistics,
dB, dBm or limits. `enable_statistics()`, `configure_db()`,
`configure_dbm()`, and `configure_limits()` refuse to replace an active
different mode unless `replace=True`. Calling `enable_statistics()`
when statistics are **already active** does not send another activation
and therefore avoids clearing the count again. To deliberately clear the
accumulator, call `clear_statistics(confirm=True)`. `disable()` only
turns `CALCulate:STATe OFF`, without resetting the meter.

dB/dBm methods require explicit typed **voltage** configuration;
dBm reference must be a Keysight-documented resistance value in ohms.
Statistics and limits are unavailable for continuity/diode. `get_limits()`
reads the actual instrument thresholds; `evaluate_limits()` is
**host-side** numerical evaluation, not a claim of a hardware pass/fail
SCPI register. `set_null(function, offset)` and `get_null(function)`
use `SENSe:<function>:NULL` rather than deprecated `CALCulate:NULL`.

Read-only queries are not guaranteed to form an atomic snapshot while
other instrument controllers are running. Real firmware command acceptance
and math/accumulator behavior are **HIL NOT RUN**. See
[SCPI command coverage](docs/SCPI_COMMAND_COVERAGE.md) and
[hardware checklist](docs/HIL.md).

## P1-03 metrology hardening (v0.3.2)

This increment builds on merged P1-03 (v0.3.1), **not** an alternate
metrology controller. All existing methods and transports remain supported.

- Frequency and period voltage-input range is configured using
  `SENSe:FREQuency:VOLTage:RANGe` and
  `SENSe:PERiod:VOLTage:RANGe`. The numeric range is **volts**,
  never a frequency in hertz or period in seconds.
- Their AC input filters use the voltage AC bandwidth SCPI group.
- `set_nplc` explicitly disables aperture-enabled mode, while
  `set_aperture` explicitly enables aperture mode. This is an ordered pair
  of SCPI writes; a communication failure must not trigger blind retries.
- Temperature autozero is only selectable after explicit **2-wire** RTD
  or thermistor configuration. The driver blocks autozero changes for 4-wire
  RTD because the instrument leaves that function autozero-enabled.
- `metrology.snapshot(MeasurementFunction.FREQUENCY)` reports voltage-input
  range, autorange, gate time and input filter where applicable.
- `metrology.read_with_settings()` performs a live pre-reading settings
  snapshot followed by one typed `READ?`; the returned
  `MeasurementResult.metrology` is a `MetrologySnapshot`. This is a
  serial software operation, **not** hardware-atomic acquisition metadata.

```python
from dmm34411a import DMM_34411A, MeasurementFunction as F

# Run only with an operator-authorized and safely connected frequency source.
with DMM_34411A.from_ethernet("192.168.0.55", protocol="socket") as dmm:
    dmm.configure_frequency()
    dmm.metrology.set_range(F.FREQUENCY, 10.0)  # 10 V AC input range
    dmm.metrology.set_ac_bandwidth(F.FREQUENCY, 20)
    print(dmm.metrology.snapshot(F.FREQUENCY))
    result = dmm.metrology.read_with_settings()
    print(result.value, result.metrology)
```

Software CI tests command paths and safety guards only. The real 34411A
firmware and input-range behavior still require operator-authorized HIL.

## Typed measurement modes (v0.3.0)

The new `dmm.measurement` API provides explicit configuration and single
readings for **DC/AC voltage, DC/AC current, 2-/4-wire resistance,
frequency, period, capacitance, continuity, diode and RTD/thermistor temperature**.
This is a *software-only*, bench-unqualified increment of
[DMM34411A-FULL-API-001](task/DMM34411A_FULL_FUNCTION_COVERAGE_TASK.md).
The original `measure_voltage()`, `conf_resistane_4wire()` and other
legacy methods are untouched and still return raw strings.

```python
from dmm34411a import (
    DMM_34411A, MeasurementConfig, MeasurementFunction, TemperatureProbe
)

# AC voltage fixture should be connected by the operator first.
with DMM_34411A(resource_name="USB0::...::INSTR", timeout_s=10.0) as dmm:
    dmm.configure_ac_voltage()             # config only, does not start a reading
    measurement = dmm.measurement.read()   # READ? and typed result
    print(measurement.value, measurement.unit, measurement.is_overrange)
    print(dmm.measure_frequency())         # one-shot MEASure:FREQuency?
    # dmm.configure_temperature(TemperatureProbe.RTD_4W)  # requires RTD wiring
```

The typed `MeasurementResult` retains the raw instrument response and a
**host receipt timestamp (UTC)**, never a fabricated instrument sample time.
The remote overload code `+/-9.9E37` is returned as
`value=None, is_overrange=True`; invalid/multiple replies raise.
Temperature reads query `UNIT:TEMPerature?` so output units are not assumed.

Advanced callers can use `dmm.measurement.configure(MeasurementConfig(...))`.
Only explicit symbolic `range_spec` (AUTO/MIN/MAX/DEF) and
`resolution` (MIN/MAX/DEF) are accepted in this increment, and only on
functions that support them. Manual numeric range, NPLC, aperture, digits,
and probe coefficients are reserved for the next metrology PR.
Continuity and diode use fixed instrument ranges. Thermistor support in this
API is **2-wire**; RTD supports 2-wire and 4-wire. Never automatically switch
a connected fixture to current/ohms/diode/capacitance mode.

Calling raw `dmm.cmd_write()` or `dmm.cmd_query()` invalidates the local
typed measurement configuration cache. Direct `dmm.client` access does
not automatically invalidate it; reconfigure explicitly after any external
configuration changes. `get_configuration_raw()` queries the live
`CONFigure?` setting.

Sources: [34410A/34411A Command Quick Reference](https://www.keysight.com/us/en/assets/9018-61141/programming-guides/9018-61141.pdf),
[34410A/34411A User's Guide](https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf).

## Planned full SCPI function coverage

The [DMM34411A-FULL-API-001 master implementation task](task/DMM34411A_FULL_FUNCTION_COVERAGE_TASK.md)
tracks missing AC voltage/current, frequency/period, capacitance, temperature,
diode/continuity, metrology controls, advanced triggers, high-speed binary
capture, statistics and instrument status. **v0.2.1 adds the task document
only**; no new measurement API is implemented in this version.

## Reading memory and data logging (v0.2.0)

This release ports the useful volatile and NVM logging functions from PR #1
to the shared `scpi-driver-core` transport, so the same API works over USB,
LAN/VXI-11, and LAN SCPI sockets. The 34411A has **1,000,000 volatile**
and **50,000 nonvolatile** reading capacity.

```python
with DMM_34411A.from_ethernet("192.168.0.55", protocol="socket") as dmm:
    dmm.conf_voltage_dc()
    # Never deletes the instrument's existing nonvolatile readings.
    dmm.configure_data_log(points=3, sample_interval_seconds=0.1)
    dmm.start_data_log()              # raises FileExistsError if NVM is not empty
    dmm.wait_for_data_log(timeout_seconds=10, save=True)
    readings = dmm.read_data_log()    # e.g. [1.0, 1.0, 1.0]
```

New APIs: `configure_volatile_acquisition`, `start_acquisition`,
`volatile_point_count`, `volatile_acquisition_progress`,
`read_volatile_readings`, `configure_data_log`, `start_data_log`,
`data_log_progress`, `wait_for_data_log`, `save_data_log`,
`nonvolatile_point_count`, `read_data_log`, `delete_data_log`,
`abort_acquisition`, `send_bus_trigger`.
All are available through `dmm.acquisition` as well.

**NVM preservation:** no `DATA:DELete` on connect, close, start, or
error recovery. Explicit deletion requires
`dmm.delete_data_log(confirm=True)`. NVM overwrite when data already exists
is blocked even with `overwrite=True`, pending instrument firmware/HIL
qualification. Save to empty NVM is allowed after finite acquisition completes.
A COPY/REMOVE/DELETE transaction is never retried after uncertain I/O.

**Volatile reads:** `read_volatile_readings()` uses `FETCh?`, limited
to 20,000 readings per text response. For explicit destructive removal,
`read_volatile_readings(erase=True, max_points=100)` uses
`DATA:REMove? 100`. Both FETCh retention and destructive REMOVE
semantics need actual 34411A HIL confirmation. New batch-reading methods
return Python float lists; the original `measure_*` methods still return
strings. This is not a fully qualified 1M-sample streaming API.

For tests, follow `docs/HIL.md`; no physical 34411A has been tested.

## Prior design and remaining work

The [buffered capture/NVM implementation task](task/DMM34411A_NVM_CAPTURE_BUFFER_TASK.md)
tracks extended qualification and future hardening. Basic memory logging
is implemented in v0.2.0, but full streaming/export and physical HIL remain.
The
instrument supports a 1,000,000-reading volatile buffer and separate 50,000-
reading nonvolatile storage; existing data must not be erased automatically.

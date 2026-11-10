# Keysight / Agilent 34411A USB and Ethernet Python Driver

A synchronous Python driver for the 34411A digital multimeter, migrated from
direct PyVISA calls to [scpi-driver-core](https://github.com/ami3go/scpi-driver-core).

**Version: 0.2.0** (the original 2021 code had no package version). The core
dependency is pinned to a reviewed commit of development version 0.1.0.dev12.

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

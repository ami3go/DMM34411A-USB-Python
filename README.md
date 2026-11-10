# Keysight / Agilent 34411A USB and Ethernet Python Driver

A synchronous Python driver for the 34411A digital multimeter, migrated from
direct PyVISA calls to [scpi-driver-core](https://github.com/ami3go/scpi-driver-core).

**Version: 0.1.2** (the original 2021 code had no package version). The core
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

## Planned measurement capture and NVM workflow

The [buffered capture/NVM implementation task](task/DMM34411A_NVM_CAPTURE_BUFFER_TASK.md)
tracks the future v0.2.0 feature. It is **not implemented** in v0.1.1. The
instrument supports a 1,000,000-reading volatile buffer and separate 50,000-
reading nonvolatile storage; existing data must not be erased automatically.

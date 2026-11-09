# Migration plan: `scpi-driver-core`

## Goal

Migrate this 34411A driver from direct PyVISA ownership to
[`ami3go/scpi-driver-core`](https://github.com/ami3go/scpi-driver-core) while preserving the
public measurement and internal-memory workflows. The migrated driver must remain usable from
plain Python and must keep all normal tests independent of physical hardware.

This plan targets `scpi-driver-core >= 0.1.0.dev12`. The package currently requires Python
3.10 or newer.

## Current baseline

The driver currently:

- creates and owns a PyVISA resource directly;
- sends model-specific SCPI strings from `DMM_34411A`;
- supports immediate voltage, current, and resistance measurements;
- supports a 1,000,000-reading volatile `RDG_STORE` acquisition;
- supports acquisition, progress monitoring, copying, counting, reading, and deletion for the
  50,000-reading non-volatile `NVMEM` data-log store;
- uses injected fake VISA objects for hardware-free tests.

The model-specific SCPI commands and the two Keysight memory limits must remain in this
repository. They do not belong in the generic core.

## Target architecture

```text
DMM_34411A
  -> ScpiSession
    -> ScpiClient
      -> VisaTransport
        -> PyVISA / VISA backend
```

`DMM_34411A` will accept an already constructed `ScpiSession`. A convenience factory will
construct a VISA-backed session from a resource name:

```python
transport = VisaTransport(resource_name, timeout_s=10.0)
client = ScpiClient(
    transport,
    codec=ScpiTextCodec(response_terminator=None),
)
session = ScpiSession("dmm34411a", client)
dmm = DMM_34411A(session)
dmm.open()
```

The response terminator is `None` because USBTMC/VISA `::INSTR` resources use the backend END
message boundary. Raw `TCPIP::SOCKET` and serial VISA resources are outside the first migration
slice and require explicit framing tests before being advertised.

## API mapping

| Existing responsibility | `scpi-driver-core` replacement |
| --- | --- |
| `pyvisa.ResourceManager().open_resource(...)` | `VisaTransport(resource_name, timeout_s=...)` |
| connection and identity lifecycle | `ScpiSession.open(probe=True, validate_identity=...)` |
| `app.write(command)` | `session.client.write(command)` |
| `app.query(command)` | `session.client.query(command)` |
| integer point-count parsing | `session.client.query_int(command)` |
| comma-separated reading parsing | `session.client.query_csv_floats(command, timeout_s=...)` |
| temporary millisecond VISA timeouts | per-operation `timeout_s` arguments |
| `*OPC?` completion waits | `session.ieee488.wait_operation_complete(timeout_s)` |
| custom `time.monotonic()` polling loop | `poll_until(...)` with a finite deadline |
| `app.clear()` at connect/close | no implicit clear; use explicit `transport.device_clear()` only when required |
| injected fake VISA resource | `ScriptedScpiTransport` for protocol tests |

## Migration phases

### 1. Package and project structure

- Add a `pyproject.toml` and use a conventional importable package, for example
  `src/dmm34411a/`.
- Add runtime dependency `scpi-driver-core>=0.1.0.dev12`; install its `visa` extra only for
  users who need VISA.
- Set `requires-python = ">=3.10"` to match the core.
- Preserve a compatibility import for `src.DMM34411A_class` for one deprecation cycle if
  existing users depend on it.
- Move the hard-coded USB resource name out of library defaults and into examples or user
  configuration.

### 2. Session ownership and lifecycle

- Change `DMM_34411A` to receive a `ScpiSession`; do not expose a raw PyVISA object.
- Add `from_visa(...)` as a convenience constructor using `VisaTransport`, `ScpiClient`, and
  the VISA message-boundary codec.
- Add explicit `open()`, `close()`, and context-manager behavior.
- Validate `*IDN?` manufacturer/model during `open()`. Accept Agilent or Keysight branding,
  but require model `34411A`; add an explicit compatibility option before accepting `34410A`
  or `L4411A` because their volatile-memory capabilities differ.
- Remove unconditional Device Clear on open and close. It can abort an acquisition and is not
  equivalent to flushing local buffers.

### 3. Command and timeout migration

- Replace direct writes and queries with `ScpiClient` calls.
- Use typed `query_int` and `query_csv_floats` instead of driver-local response parsing.
- Express all public timeouts in seconds and pass them per operation. Keep a short normal I/O
  timeout, a bounded acquisition deadline, and a longer bulk-read timeout.
- Use `ScpiSession.operation_lock()` around the completion/copy/verification sequence so
  another caller cannot interleave commands between `*OPC?`, `DATA:COPY`, and the NVMEM count.
- Use `poll_until` for progress waits and translate its `OperationTimeoutError` into a
  device-specific error containing acquired and target counts.
- Keep all model limits and trigger/sample validation in the concrete driver.

### 4. Internal-memory behavior

- Preserve separate public paths for volatile acquisition and persistent data logging.
- Retain these enforced limits:
  - `RDG_STORE`: 1 to 1,000,000 readings on a verified 34411A;
  - `NVMEM`: 1 to 50,000 readings.
- Keep the persistent sequence explicit:
  1. configure sample and trigger counts;
  2. optionally delete the previous NVMEM log;
  3. `INITiate` into `RDG_STORE`;
  4. monitor `DATA:POINts? RDG_STORE`;
  5. confirm completion;
  6. `DATA:COPY NVMEM, RDG_STORE`;
  7. confirm the copy and verify `DATA:POINts? NVMEM`;
  8. retrieve with `DATA:DATA? NVMEM`.
- Keep `FETCh?` as a non-destructive volatile read and `R? [count]` as a destructive volatile
  read. Do not retry destructive queries automatically.
- Preserve `FORMat:DATA ASCii` for predictable CSV parsing. A later binary-read optimization
  must be a separate change with framing and HIL coverage.

### 5. Layered hardware-free tests

- Convert deterministic command tests to pytest and `ScriptedScpiTransport`; assert exact SCPI
  traffic for measurement, timer, trigger, progress, copy, read, delete, and abort paths.
- Add malformed point-count and malformed CSV response tests through the public driver API.
- Add timeout, disconnect, faulted-session, and explicit recovery scenarios. Never retry
  `INITiate`, `DATA:COPY`, `DATA:DELete`, or `R?` after an uncertain result.
- Add Hypothesis tests for point bounds, finite timeout/interval bounds, trigger-source aliases,
  and numeric formatting.
- Add PyVISA-sim coverage for the real
  `DMM_34411A -> ScpiSession -> ScpiClient -> VisaTransport -> PyVISA` path where simulator
  behavior is sufficient.
- Add `pytest-timeout` repository-wide bounds and a finite session timeout.
- Mark physical-instrument tests `hardware` and exclude them from normal CI.

### 6. Hardware validation and rollout

- On a real 34411A over USBTMC, verify identity, Device Clear policy, 1/50,000/50,001 persistent
  point boundaries, 1/1,000,000 volatile point boundaries, timer acquisition, external trigger,
  abort, power-cycle persistence, and 50,000-point ASCII readback.
- Record firmware version, VISA implementation, resource name, elapsed times, and observed SCPI
  errors for the HIL run.
- Run the old and migrated APIs against the same small acquisitions and compare commands and
  returned values.
- Deprecate the direct-PyVISA constructor after compatibility tests pass; remove it only in a
  documented breaking release.

## Repository layout after migration

```text
src/dmm34411a/
  __init__.py
  driver.py
  errors.py
tests/
  unit/
  property/
  integration/
    fixtures/pyvisa_sim.yaml
  hardware/
Examples/
Docs/
pyproject.toml
```

## CI acceptance gate

The migration is complete only when all of the following are true:

- formatting, lint, and strict type checks pass;
- `pytest -m "not hardware"` passes without a connected instrument;
- the complete suite and every polling test have finite timeout protection;
- public APIs are covered through scripted transport and the representative VISA-sim path;
- both memory limits and all boundary failures are covered;
- no runtime module imports pytest, Hypothesis, pytest-timeout, or PyVISA-sim;
- the driver contains no direct PyVISA resource operations outside the VISA factory boundary;
- normal command, acquisition, NVMEM copy, and readback pass on real 34411A hardware;
- examples and user documentation use the session-based API.

## Known risks and decisions

- `scpi-driver-core` is still a development release. Pin the tested development version until
  its first stable release, then widen the constraint deliberately.
- The core faults a transport after uncertain I/O timeouts. The driver must expose explicit
  recovery instead of silently continuing with a potentially late response.
- Full 50,000-reading ASCII responses must fit the core codec maximum response size. Measure a
  worst-case response before migration; configure an explicit bounded maximum if the default is
  insufficient.
- Device Clear can abort active measurements. It remains an explicit operator action, not a
  connection cleanup step.
- Physical persistence, END behavior, and real acquisition timing cannot be proved by mocks or
  PyVISA-sim and remain HIL acceptance items.

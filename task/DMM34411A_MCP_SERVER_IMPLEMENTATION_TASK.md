# DMM34411A-MCP-001 — Optional Model Context Protocol Server for the Keysight/Agilent 34411A

**Status:** IMPLEMENTATION TASK / SPECIFICATION ONLY — MCP server NOT IMPLEMENTED and HIL NOT RUN  
**Priority:** P1 for local read-only and supervised measurement access; P0 for safety boundaries, permissions and instrument exclusivity  
**Repository:** https://github.com/ami3go/DMM34411A-USB-Python  
**Shared SCPI core:** https://github.com/ami3go/scpi-driver-core  
**Baseline:** Driver v0.8.7 on main (2026-11-12), with P0 acquisition serialization (v0.8.5), exclusive binary-transfer ownership (v0.8.6), and guarded uncertain-state recovery (v0.8.7) already implemented  
**Target:** First MCP feature release v0.9.0, split into independently reviewable increments as needed  
**Scope:** Local MCP server using stdio first. Remote Streamable HTTP is a separately gated extension.

## 1. Mission

Build a safe, optional MCP server that makes the existing, installable dmm34411a Python driver available to authorized AI clients such as Claude Code, OpenCode and compatible MCP hosts. Expose typed instrument capabilities, not arbitrary SCPI command execution.

The MCP service must delegate all SCPI I/O to the EXISTING DMM_34411A, AcquisitionController, MeasurementController, ReadingTransferController, RecoveryController, StatusController and scpi-driver-core session. No parallel SCPI stack, new VISA/socket implementation, independent instrument state machine, or duplicated drivers.

Deliver actual implementation code, offline tests, documentation, CI, versioned commits, PRs and eligible software-only merges when implementing this task. Writing this specification alone does NOT constitute MCP implementation.

## 2. Current baseline / dependencies

Already delivered by the driver:

- Importable root package dmm34411a/; distribution name dmm34411a-usb-python (preserve for compatibility).
- USBTMC over VISA; Ethernet VXI-11 over VISA; raw Ethernet TCP/5025.
- Typed DC/AC voltage/current, 2W/4W resistance, frequency, period, capacitance, continuity, diode and temperature measurements.
- Finite acquisition, BUS/EXT/INT triggering, bounded wait, explicit STOP, sample progress.
- REAL32/REAL64 IEEE binary FETCh? and separately guarded destructive DATA:REMove?; CSV/JSON export with SHA-256.
- v0.8.5 canonical acquisition/session operation locks; v0.8.6 instrument-wide transfer lease, cooperative cancellation; v0.8.7 sticky uncertain-state quarantine, inspect_recovery() and acknowledge_recovery().
- Simulator tests and CI on Python 3.10–3.13. Actual physical 34411A HIL qualification remains NOT RUN.

**Important:** Do not duplicate these P0 improvements. Before coding, reread current main HEAD and test the existing locking/recovery API on the exact version being extended. The MCP adapter is responsible for enforcing its OWN client authorization and resource ownership in addition to the driver's safety interlocks.

## 3. MCP protocol / SDK / compatibility

- Use the **official Python MCP SDK v2** with an explicitly reviewed compatible version range (for example mcp>=2,<3), checking actual published APIs at implementation time.
- MCP protocol revision 2026-07-28 is stateless; the SDK v2 can interoperate with supported earlier clients. Do NOT hand-roll MCP initialization, JSON-RPC framing, header negotiation or transport.
- The v2 high-level server entry point is MCPServer (formerly FastMCP in v1); verify actual imports against the pinned SDK. Favor mcp.server.MCPServer and its official run patterns.
- Python MCP SDK v2 requires **Python >=3.11**. The core dmm34411a distribution currently supports Python >=3.10. MCP must remain OPTIONAL: normal installation and import on 3.10 must keep working, with a clear error/instructions for MCP on unsupported Python.
- Decide and document whether to use an optional mcp extra with a Python version marker or a separate MCP adapter distribution. Do not accidentally make the normal driver require Python 3.11+ or hide a missing dependency behind a silently empty extra.
- Local stdio is the mandatory first transport. Streamable HTTP is optional P1 follow-up, never public-facing by default. Do not add new legacy HTTP+SSE transport.
- No MCP SDK import occurs at normal dmm34411a import time. Core instrumentation remains usable without MCP installed.
- Test both protocol eras through SDK-level clients where supported; do not claim compatibility with an AI host without an actual integration check.

## 4. Proposed module layout

Keep the root package layout; do NOT introduce a src/ layout for new driver code.

~~~text
dmm34411a/
  mcp_server/
    __init__.py           # lazy imports; no side effects
    __main__.py           # python -m dmm34411a.mcp_server
    app.py                # MCPServer construction/registration
    tools.py              # thin typed tool adapters
    resources.py          # optional safe read-only MCP resources
    policy.py             # fixture/role/approval/resource allowlists
    manager.py            # single-instrument owner, lifecycle, operation gates
    schemas.py            # bounded output models and structured errors
    audit.py              # journal, redaction, provenance
    config.py             # validated local configuration and CLI
tests/mcp/
  test_server.py
  test_policy.py
  test_measurement.py
  test_acquisition.py
  test_concurrency.py
  test_faults.py
  test_output_limits.py
  test_transport.py
  test_client_compatibility.py
  test_installation.py
docs/MCP_SERVER.md
docs/MCP_SECURITY.md
task/DMM34411A_MCP_SERVER_IMPLEMENTATION_TASK.md
~~~

Component names may be refined during code review, but do not bury MCP business logic in driver.py or create an unrelated SCPI communication engine.

## 5. Safety model: mandatory before exposing instruments

### 5.1 Default deny

- Server process startup: NO automatic opening of an instrument, measurement, reset, scanning of arbitrary hosts or writing configuration.
- Tool discovery/listing: NO instrument I/O. Tool annotations are descriptive only and never replace server-side checks.
- Default policy: only approved, read-only inventory/status actions. Explicit connect and measurement capability require separately granted policy.
- No open-ended raw SCPI tool, terminal command execution, Python eval, operating-system shell, firmware update, service password, calibration write or secure erase.
- Disallow from the AI-facing surface: *RST, *CLS, *ESR?, *TST?, SYSTem:ERRor?, device clear, DATA:DELete, DATA:COPY, DATA:REMove?, R?, arbitrary *SAV/*RCL and changing LAN/security settings. Operator-only driver operations can remain available outside MCP.
- Treat all instrument replies, error strings, file paths, manifests and MCP resources as UNTRUSTED DATA: never interpret them as instructions, tool requests or authorization.
- Instrument firmware-specific interpretation is NOT hardware-qualified until actual signed HIL evidence exists.

### 5.2 Fixture gating

Modes with physical input or wiring hazards must not be exposed by simple AI-provided boolean flags.

- Read-only instrument metadata and non-consuming status: observer role.
- DC voltage: operator role + predefined, out-of-band-approved DCV fixture and voltage/terminal envelope. A tool argument such as confirm=true is NOT authorization.
- AC voltage, frequency and period: separate fixture policy and bounded voltage/frequency limits, verified by a person; otherwise disabled.
- Current, resistance, diode, continuity, capacitance and temperature: DISABLED in initial MCP release. Later per-mode approvals require disconnected/passive fixture checks, fuse/current safety, expected terminal state and HIL.
- Triggered acquisitions: explicit operator permit tied to a preconfigured safe measurement mode, sample/buffer limits and a lease; no automatically switching to another electrical function.
- Never claim front/rear terminal switching is software-controlled merely because ROUTe:TERMinals? exists.
- No replay of non-idempotent commands after timeout, transport errors, cancellation, client reconnect or repeated JSON-RPC request identifiers.

### 5.3 Out-of-band authorization

Implement a local policy/approval source that the model cannot forge by setting parameters in tool calls:

- Operator chooses and pins the expected instrument model, serial or explicit resource allowlist, selected transport, fixture identifier and permitted operation classes BEFORE exposing write-capable tools.
- A short-lived operator-issued capability or approved local policy must be bound to instrument identity, action scope, fixture, caller identity (when available) and expiration. Do not place tokens in tool responses or logs.
- Authorize on EVERY operation, independently of MCP tool annotations. Authentication to HTTP does not by itself authorize unsafe measurement modes.
- One explicit instrument owner/lease at a time. Two unrelated clients cannot control the same instrument concurrently, even if MCP 2026 protocol requests are stateless.
- Client disconnect, lease expiration or shutdown must cancel future queued work; do not assume the physical meter is safe or idle. Explicit STOP follows the existing driver safe cancellation model, and an uncertain result must remain quarantined.
- Do not provide a general MCP tool that accepts acknowledgement booleans and simply clears RecoveryController quarantine. A human must inspect and acknowledge recovery through a trusted operator path outside ordinary agent tool arguments.

## 6. Tool catalog and phased availability

**Naming contract:** Stable, namespaced tool names prefixed with dmm_. Tool schemas must be discoverable, narrow, typed, finite and documented. No arbitrary SCPI command strings or unrestricted filesystem paths.

| Tool | Behavior / existing delegation | Initial phase | Authorization | Important restrictions |
| --- | --- | --- | --- | --- |
| dmm_list_resources | Enumerate configured allowlisted VISA resources / known profiles | A | Observer | No unbounded LAN scan; mark unavailable backends |
| dmm_list_instruments | Return configured candidate profiles and their last known status | A | Observer | No physical I/O just to list |
| dmm_connect | Open exactly one configured resource; verify *IDN? and model | A | Operator or configured connection role | No reset, clear or implicit acquisition |
| dmm_disconnect | Close owned session and revoke lease | A | Owner | Do not claim it stops an active physical run |
| dmm_identify | Return identity/firmware/transport of connected instrument | A | Observer | Redact serial in remote logs as configured |
| dmm_get_status | diagnostics_snapshot(include_memory=False) | A | Observer | No destructive status/error/event reads |
| dmm_get_memory_counts | volatile_point_count / nonvolatile_point_count | A | Observer | Count queries only, never consume data |
| dmm_get_configuration | MeasurementController.get_configuration_raw | A | Observer | Treat raw config as data |
| dmm_get_recovery_status | Expose quarantine flag/reason and last safe snapshot | A | Observer | No acknowledge/unquarantine tool |
| dmm_configure_dcv | configure_dc_voltage | B | Approved DCV fixture/operator | Configuration side effects explicit |
| dmm_read_configured | MeasurementController.read | B | Approved fixture/operator | May trigger measurement; NOT read-only |
| dmm_measure_dcv | measure_dc_voltage | B | Approved DCV fixture/operator | Single explicit measurement, bounded timeout |
| dmm_measure_acv | measure_ac_voltage | C | Approved AC fixture/operator | Disabled until fixture/HIL policy |
| dmm_measure_frequency | measure_frequency | C | Approved source/operator | Disabled until fixture/HIL policy |
| dmm_measure_period | measure_period | C | Approved source/operator | Disabled until fixture/HIL policy |
| dmm_configure_capture | configure_volatile_acquisition | C | Approved operator/capture | Validate count, trigger and current mode |
| dmm_start_capture | start_acquisition | C | Approved operator/capture | Exactly-once intent; never retry INIT |
| dmm_capture_progress | acquisition_progress_snapshot | C | Observer | Bounded polling; report UNKNOWN/STOP |
| dmm_wait_capture | acquisition.wait_complete | C | Owner/capture | Finite timeout; nonblocking STOP pathway |
| dmm_stop_capture | stop_acquisition / explicit STOP | C | Owner/safety | Safety-priority path, no ABORt retry |
| dmm_export_readings | export_volatile_bundle(destructive=False) | D | Approved operator/export | New sandbox-relative destination; hashes |
| dmm_get_export_manifest | Read approved export metadata | D | Observer authorized for artifact | No arbitrary file read |
| dmm_get_export_slice | Bounded page from approved capture CSV | D | Observer authorized for artifact | Never 1M samples in one reply |
| dmm_inspect_recovery | inspect_recovery() read-only inspection | D | Operator/observer | Reconnect only according to explicit policy; no automatic acknowledge |

All tool availability is controlled by policy. Phase C/D MUST NOT be enabled by default and cannot bypass pending HIL gates. Optional power/current/ohm/etc tools require a distinct later task and engineering approval.

### 6.1 Distinguish read-only from non-destructive

Non-destructive FETCh? does not remove samples, but it performs physical I/O and can change temporary format settings. MEASure? / READ? can initiate a measurement or reconfigure the meter. Therefore do not advertise those as pure read-only or idempotent solely because they do not delete memory.

### 6.2 Tool schemas

Every public tool must have:

- A human-readable description including physical side effects, wiring/fixture requirements, approval level and model limitations.
- Strict JSON input validation; no booleans accepted as integers, no NaN/Inf, no unlimited strings, no unbounded host/port/path inputs.
- Structured JSON success/error output with machine-readable code, timestamp, units, observed instrument state, recovery_required flag, and capture ID when relevant.
- Accurate MCP tool annotations such as readOnlyHint / destructiveHint / idempotentHint where supported; hints do not grant authority.
- No raw traceback, credential, network token or unbounded SCPI payload in client-visible errors.
- A declared timeout/cancellation behavior and an explicit result for UNCERTAIN operations.

## 7. MCP resources, prompts and result handling

Suggested resources (read-only views, not SCPI command execution endpoints):

| URI template | Content | Data source / bounds |
| --- | --- | --- |
| dmm://server/capabilities | Tool/policy capability summary and supported driver versions | Static / no instrument I/O |
| dmm://instrument/current/identity | Authorized current instrument identity | Cached IDN, minimal metadata |
| dmm://instrument/current/status | Last non-consuming status snapshot | Cache with explicit time and staleness |
| dmm://capture/{capture_id}/manifest | Capture metadata, CRC/SHA, file sizes, sample count | Server-owned manifest allowlist |
| dmm://capture/{capture_id}/readings?page=... | Optional bounded page of readings | Verified export, strict page/byte cap |

A first release may implement tools only; resources/prompts are optional if needed for client ergonomics. Do not let a resource fetch secretly execute a destructive SCPI operation.

For one-shot measurements return fields such as:

~~~json
{
  "ok": true,
  "instrument": {"model": "34411A", "transport": "USB_VISA"},
  "measurement": {
    "function": "dc_voltage",
    "value": 1.234,
    "unit": "V",
    "overrange": false,
    "host_received_at_utc": "2026-11-12T10:00:00Z"
  },
  "hardware_qualified": false
}
~~~

This is a **schema illustration, not real hardware evidence**. Use the existing MeasurementResult dataclass and preserve overload status. Never call a host reception timestamp a per-sample instrument timestamp.

### 7.1 Capture size and artifact rules

- Default maximum inline readings: 128 (hard cap 256); default maximum serialized tool response: 64 KiB or lower; configurable downward by policy.
- Full captured data belongs in a controlled, new host export bundle with CSV/JSON and SHA256. Return a manifest/capture ID; paginate or stream through explicit bounded resource reads.
- Permit only new filenames below a configured absolute export root; reject path traversal, symlinks, absolute paths from tool arguments, overwrites and file-injection characters.
- Keep export artifacts and audit records private to server owner or authenticated principal; protect serial numbers, data and lab configuration.
- Record sample count, units, precision, function, transport, IDN/model/serial/firmware (access controlled), driver/core/MCP versions, host timestamps, nominal vs measured timing, buffer counts and transfer certainty.
- If export was incomplete, preserve its INCOMPLETE manifest with confirmed rows; never mislabel it as a successful or fully verified capture.

## 8. Session and concurrency design

Use one server-scoped InstrumentManager and existing scpi-driver-core session:

1. A connection profile pins a single approved resource to the current server process. Opening is explicit, identity verified, ownership obtained before tool execution.
2. Concurrent MCP tool calls are serialized against the same canonical session.operation_lock() and the v0.8.6 exclusive transfer lease. Do not introduce a second unrelated lock hierarchy.
3. Do not hold a lock while awaiting external approval or sleeping in a polling loop. Preserve the driver's interruptible STOP/cancel path. Waiting must use finite deadlines.
4. Destructive iterators remain PRIVATE implementation details and are not exposed to the model. If used in an operator-only extension, always exhaust or close them under contextlib.closing().
5. Track in-flight request ID, instrument generation, lease generation, ownership, and whether the command may have reached the device. A duplicate/retried non-idempotent tool call MUST NOT replay SCPI.
6. A timeout while write may have taken effect sets UNKNOWN/quarantine. Keep RecoveryController pending across process lifecycle as far as durable journal evidence permits; after server restart treat any interrupted active operation as uncertain until operator review.
7. A client disconnect never authorizes automatic reconnection, capture replay, *RST, *CLS, device clear, NVM copy or erase. Read-only reconnection inspection must be explicit.
8. Repeated STOP is not silently retried. If STOP I/O is uncertain, set recovery_required; do not falsely claim instrument idle.
9. A second process using the same meter cannot be physically prevented by a Python lock. Document advisory OS-level lock/lease and external-controller hazard; implement local process lock if possible.
10. Prevent confused-deputy behavior: a caller cannot select a different resource, change a fixture policy, or read another principal's artifact through a tool call.

## 9. Authentication and transport hardening

### 9.1 stdio — default

- Start as a local subprocess with python -m dmm34411a.mcp_server --transport stdio --config <path>.
- Stdout must contain ONLY MCP protocol messages, no startup banners, logger messages or instrument debug output. Logs go to stderr or configured restricted file.
- Local OS account/stdio process access is not sufficient for dangerous actions; honor fixture approvals and scoped capabilities.
- Never put API keys, shared tokens or secrets inside README example arguments or committed config.
- On EOF/shutdown, cancel future queued calls, release owner lease, close resources; do not automatically reset or erase the instrument.

Example client configuration (shape must be validated for each target client):

~~~json
{
  "mcpServers": {
    "keysight-34411a": {
      "command": "python",
      "args": ["-m", "dmm34411a.mcp_server", "--transport", "stdio", "--config", "/path/to/lab-mcp.toml"]
    }
  }
}
~~~

The target app's actual schema and setup steps must be verified; no claim this JSON works unchanged in every MCP host. Connection remains disabled in read-only policy unless operator approved the configured instrument.

### 9.2 Streamable HTTP — separate optional step

- Never bind to 0.0.0.0 by default. Start only on 127.0.0.1/::1; network binding requires separate explicit configuration and reviewed threat model.
- No unauthenticated HTTP access to SCPI functions. Require HTTPS/TLS or a trusted authenticated reverse proxy, Bearer/OAuth verification, least-privilege scopes, audience and issuer validation, expiration, replay protection where appropriate, per-instrument authorization and rate limits.
- Validate Origin and Host, block DNS rebinding, enforce CORS restrictions; protect against CSRF, SSRF, path traversal and cross-client data disclosure.
- Verify MCP 2026-07-28 protocol request header consistency and version handling via official SDK, not a home-grown parser.
- Bind authorization to each HTTP request in stateless protocol mode. Protocol-level sessions are NOT equipment leases.
- Apply timeouts, request/payload caps, connection limits, auditing and TLS configuration checks before listening on a remote interface.
- Support proper rejection of unauthorized / expired / forged / cross-origin requests; never expose lab instruments through anonymous Tailscale/public proxies without a separate hardening review.

## 10. Error and recovery contract

| Situation | MCP-visible error | Instrument policy |
| --- | --- | --- |
| No instrument connected | NOT_CONNECTED | No automatic connect |
| Resource not allowlisted | RESOURCE_DENIED | No transport creation |
| Invalid model / serial mismatch | IDENTITY_MISMATCH | Close/release, no command retry |
| Fixture or role not approved | APPROVAL_REQUIRED | Zero instrument writes |
| Current instrument lease occupied | INSTRUMENT_BUSY | No concurrent SCPI |
| Capture incomplete | CAPTURE_INCOMPLETE | Preserve partial counts and state |
| Timeout before confirmed outcome | IO_UNCERTAIN | Quarantine/reconcile |
| Connection lost during command | IO_UNCERTAIN | No replay of a possible write |
| RecoveryController pending | RECOVERY_REQUIRED | Only permitted read-only inspection |
| Cancellation during destructive action | TRANSFER_UNCERTAIN | Preserve confirmed progress; no retry |
| Invalid input or path | INVALID_ARGUMENT | Zero instrument writes and no filesystem escape |
| Too many requested readings | RESULT_TOO_LARGE | Return bounded manifest guidance |
| Firmware feature not HIL qualified | NOT_QUALIFIED | Fail closed for gated feature |

Do not surface internal OS exception text or arbitrary instrument strings as executable suggestions. Include request correlation ID and safe audit reference.

## 11. Configuration contract

Configuration file, validated before server startup, should define:

~~~toml
[server]
transport = "stdio"
policy = "read_only"
max_inline_samples = 128
max_result_bytes = 65536
max_concurrent_requests = 8

[instrument]
profile = "bench_dmm"
resource = "USB0::...::INSTR"
expected_model = "34411A"
auto_connect = false

[output]
root = "/home/operator/dmm-captures"
allow_overwrite = false

[authorization]
require_out_of_band_approval = true
allow_raw_scpi = false
allow_destructive_memory = false
allow_calibration_writes = false
~~~

This example is nonfunctional without an actual operator-created profile and resource. Reject unknown keys, unsafe paths, unrestricted host patterns and contradictory settings. Do not put any real instrument serials or passwords into committed fixtures.

## 12. Implementation phases / independently reviewable PRs

### Phase A — MCP skeleton, packaging and read-only tools (P1)

- Add optional MCP dependency, proper pyproject entrypoint, --help, --doctor and pure no-I/O server startup.
- Implement InstrumentManager with resource allowlist and identity check; register dmm_list_resources, dmm_list_instruments, dmm_connect, dmm_disconnect and read-only identity/status/count tools.
- Add SDK v2 tool schemas with deliberate side-effect annotations; no arbitrary SCPI tool.
- Add stdio protocol integration tests with the official MCP Client. Confirm no garbage on stdout and lazy import on Python 3.10.
- Add docs/MCP_SERVER.md, config example, README quickstart, change log and a version bump.

### Phase B — Authorized low-risk DCV measurement (P1)

- Integrate fixture-capability policy with out-of-band operator approval; identity/resource pinning; signed or non-forgeable local approval state.
- Enable configure/read/measure DCV only under approved fixture; preserve MeasurementResult/overload semantics.
- Negative tests: a crafted model prompt supplying confirm=true without an approval must cause ZERO SCPI writes.
- Confirm no auto-current/ohms/diode switch, no instrument reset and no driver-side recovery bypass.

### Phase C — Finite capture and STOP (P0 safety / P1 feature)

- Expose approved configure/start/progress/wait/stop tools only, using existing v0.8.5 acquisition locks and v0.8.6 transfer guard.
- Add idempotency fencing, bounded deadlines, cooperative cancellation and generation-checked ownership.
- Test concurrent clients, STOP while waiting, duplicate start, timeout after INIT, disconnect during STOP and no deadlocks.
- Any uncertain run must remain quarantined via v0.8.7 RecoveryController until manual acknowledgement.

### Phase D — Bounded non-destructive export and resources (P1)

- Export non-destructively to a new restricted artifact directory and return manifest/sha instead of 1M inline floats.
- Add export catalog/slice read access with strict page/byte limits and per-caller authorization.
- Test 0/1/50k/1M simulated readings, malformed binary, overrange, cancellation, disk full, symlinks, traversal, digest mismatch and incomplete recovery.
- Explicit destructive FIFO and NVM writes remain unavailable to MCP.

### Phase E — Optional authenticated Streamable HTTP and integration (P1)

- Enable only after stdio stable, approval policy tested and dedicated security review.
- Integrate with representative Claude Code/OpenCode MCP clients using valid tested client-specific config.
- Add authentication, identity/scopes, origin/host validation, local TLS/proxy requirements and audit.
- Run protocol compatibility and security regression tests for modern and supported legacy MCP clients.

### Phase F — HIL qualification and release (HIL-required)

- Execute approved physical bench steps per docs/HIL.md, record USB, VXI-11 and socket results separately.
- Qualify command side effects, actual trigger/STOP response, meter identity, fixture behavior, transfer framing, error handling and disconnect/reconnect.
- Release only the subset actually qualified, with explicit software-only/physical-HIL status on every tool and public documentation.
- No automatic HIL tests in general CI and no unsupported claim of metrological accuracy.

## 13. Automated acceptance matrix

| Test group | Required test / failure injection | Exit criterion |
| --- | --- | --- |
| SDK and packaging | pip normal driver Python 3.10; MCP Python 3.11–3.13; mcp not installed core import | No regression / explicit unsupported-runtime handling |
| MCP protocol | Official SDK client tool discovery, schema parse, requests, errors, cancellation, stdio framing | Protocol-valid; stdout contains only MCP |
| Read-only startup | Construct MCPServer/list tools and load config in dry-run | ZERO instrument commands |
| Authorization | Missing, expired, wrong-resource, wrong-fixture, wrong-tool approval | Deny before SCPI writes |
| Unsafe input | Invalid counts, NaN, bool-as-int, unsupported function, path injection | Structured error; ZERO writes |
| Port/profile | USB/VXI-11/raw TCP selectable only via approved profiles | No unrestricted LAN scanning or host injection |
| Safety exclusions | Prompt-injected request for raw SCPI, *RST, *CLS, NVM DELETE/COPY, calibration | No such tool; requests rejected |
| Measurement | DCV normal/overrange/invalid reply, unit/timestamp provenance | Exact MeasurementResult fields |
| State machine | INIT/trigger/STOP sequencing, concurrent calls, double INIT, STOP during wait | No replay, deadlock or stale state |
| Transfer | Lock exclusivity, 1M simulate, non-destructive FETCh, interrupted export | One owner; bounded memory; preserved evidence |
| Cancellation | Client dies, request times out, stream closes, lost write reply | UNKNOWN/quarantine, no retry |
| Recovery | Reconnect with pending quarantine, changed IDN/counts, stale snapshot | Operator-only reconciliation |
| Multi-client | Two clients same meter / same capture / different fixture scopes | Serialize or reject; never cross-share |
| Filesystem | Symlink/traversal, directory exists, disk full, partial publication | No escape/overwrite, truthful manifest |
| Network security | Unauthenticated HTTP, invalid TLS policy, Host/Origin spoof, forged token | Denied, cannot reach SCPI |
| Tool output limits | >256 samples, giant IDN, bogus huge response, binary bytes | <= configured reply cap |
| Regression | Existing offline pytest/CI, core compatibility and wheel installation | All existing checks green |

Minimum test count and coverage threshold must be set after initial implementation, but the test suite must cover every safety-critical branch. Add OS-specific stdio integration coverage (Linux and Windows where available). Run physical tests only after explicit bench authorization.

## 14. HIL qualification matrix — NOT RUN

| Case | Fixture / method | Acceptance evidence | State |
| --- | --- | --- | --- |
| MCP-HIL-01 | USB/VISA identity/status | Model, serial, firmware, exact transcript | NOT RUN |
| MCP-HIL-02 | Ethernet VXI-11 identity/status | Connection and safe status snapshot | NOT RUN |
| MCP-HIL-03 | TCP socket/5025 identity/status | Connection, timeout and reply framing | NOT RUN |
| MCP-HIL-04 | DCV safe known low-voltage source | Actual/reference V, uncertainty, range, time | NOT RUN |
| MCP-HIL-05 | Bounded finite capture | Count and sequence/terminal conditions | NOT RUN |
| MCP-HIL-06 | BUS/EXT/INT trigger & STOP | Response, timing evidence, partial count | NOT RUN |
| MCP-HIL-07 | REAL32/REAL64 capture | Payload framing, byte order, SHA256 | NOT RUN |
| MCP-HIL-08 | Disconnect/fault quarantine | Lost-ack evidence; no command replay | NOT RUN |
| MCP-HIL-09 | Two-client lease contention | No simultaneous instrument access | NOT RUN |
| MCP-HIL-10 | Authorization denial with real session | No SCPI writes for prohibited tool | NOT RUN |

Physical bench operator must independently check wiring and approve fixture, range and test window. Record raw SCPI logs, transport resource, instrument calibration details, driver/core/MCP SDK versions, timestamps, expected/actual results, uncertainty, PASS/FAIL/NOT RUN and sign-off. The runner may automate evidence gathering, but must never invent a PASS.

## 15. Definition of done

Implementation is complete ONLY when:

1. Optional MCP server installs and starts using official SDK on supported Python without breaking core Python 3.10.
2. stdio clients can list tools, connect to explicitly approved model/resource, read safe diagnostics and (when authorized) obtain a typed DCV measurement.
3. All tool operations pass through existing DMM_34411A/scpi-driver-core; no independent SCPI transport/client/state machine exists.
4. Authorization policy and fixture restrictions are verified offline, and no AI-provided confirmation string can substitute for operator permission.
5. Acquisition, transfer, cancellation and recovery preserve v0.8.5–v0.8.7 safety contracts with regression tests.
6. Data transfer and export results remain bounded, auditable, correctly hashed, and never claim unmeasured sample timestamps.
7. Safety exclusions explicitly prevent unapproved raw commands, NVM mutation, device clear/reset, current/ohms mode changes and calibration writes.
8. CI, static checks, protocol compatibility, wheel installation and package version synchronization pass; every code-changing PR bumps version.
9. User-facing docs include verified startup commands, transport limitations, client configuration, a permission table, safety warnings and troubleshooting.
10. All HIL-dependent behaviors are visibly NOT RUN until evidenced. Release cannot claim full hardware qualification without approved physical tests.
11. PRs are independently reviewed; only green, conflict-free, software-only safe increments are eligible for autonomous merges.
12. Final report lists each PR/commit, source changes, CI/test counts, MCP tools/resources status and outstanding HIL evidence.

## 16. Out of scope for first release

- Autonomous recalibration, instrument self-test, current-terminal switching or unattended current/diode/ohms/capacitance tests.
- Arbitrary raw SCPI, scripting, instrument firmware upload, service/security resets, NVM copy/erase or destructive buffer drain.
- Public anonymous MCP service, public Internet exposure or unaudited remote multi-tenant control.
- Distributed instrument scheduler, large waveform visualization or general lab orchestration.
- Guarantee of 50,000 readings/s through MCP or any physical metrology accuracy claim without HIL.

## 17. References and implementation review sources

- MCP specification (2026-07-28): https://modelcontextprotocol.io/specification/2026-07-28
- MCP 2026 protocol release notes: https://blog.modelcontextprotocol.io/posts/2026-07-28/
- Official Python SDK and current installation requirements: https://github.com/modelcontextprotocol/python-sdk
- Python SDK v2 docs (server, transports, migration): https://py.sdk.modelcontextprotocol.io/
- SDK v2 breaking changes (FastMCP renamed MCPServer): https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md
- Model-specific driver baseline and README: https://github.com/ami3go/DMM34411A-USB-Python
- Existing full-feature backlog: https://github.com/ami3go/DMM34411A-USB-Python/blob/main/task/DMM34411A_FULL_FUNCTION_COVERAGE_TASK.md
- Existing safe hardware qualification procedure: https://github.com/ami3go/DMM34411A-USB-Python/blob/main/docs/HIL.md
- Shared SCPI core: https://github.com/ami3go/scpi-driver-core

**Implementation instruction for coding agents:** First synchronize with the latest main, audit v0.8.5–v0.8.7 concurrency/transfer/recovery mechanisms and latest SDK v2 API, then execute phases A–F sequentially with tests, commits, PRs and version increments. Do not stop at a plan or claim HIL evidence not obtained.
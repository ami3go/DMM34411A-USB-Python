# Changelog

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

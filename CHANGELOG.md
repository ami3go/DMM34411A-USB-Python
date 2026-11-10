# Changelog

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

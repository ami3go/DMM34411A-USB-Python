# Keysight/Agilent 34411A — SCPI measurement and metrology command coverage (v0.3.2)

**Baseline:** v0.3.2; measurement implementation v0.3.0, metrology v0.3.1 + v0.3.2 safety hardening.
**Qualification:** Command strings verified against official Keysight 34410A/11A
Quick Reference, not yet verified on a connected physical 34411A.
**Legacy coverage:** Existing v0.2.0 acquisition/NVM functions remain in place.
**Readback:** Every row supports an explicit `CONFigure:...` and a
`MEASure:...? ` single reading; `measurement.read()` uses `READ?`.
**Important:** A raw SCPI command alone is not considered a tested wrapper.

| Function | Configure command | One-shot command | API `MeasurementFunction` | Return unit | Offline test | HIL |
| --- | --- | --- | --- | --- | --- | --- |
| DC voltage | `CONFigure:VOLTage:DC` | `MEASure:VOLTage:DC?` | `DC_VOLTAGE` | V | Automated | NOT RUN |
| AC voltage | `CONFigure:VOLTage:AC` | `MEASure:VOLTage:AC?` | `AC_VOLTAGE` | V RMS | Automated | NOT RUN |
| DC current | `CONFigure:CURRent:DC` | `MEASure:CURRent:DC?` | `DC_CURRENT` | A | Automated | NOT RUN |
| AC current | `CONFigure:CURRent:AC` | `MEASure:CURRent:AC?` | `AC_CURRENT` | A RMS | Automated | NOT RUN |
| 2-wire resistance | `CONFigure:RESistance` | `MEASure:RESistance?` | `RESISTANCE_2W` | ohm | Automated | NOT RUN |
| 4-wire resistance | `CONFigure:FRESistance` | `MEASure:FRESistance?` | `RESISTANCE_4W` | ohm | Automated | NOT RUN |
| Frequency | `CONFigure:FREQuency` | `MEASure:FREQuency?` | `FREQUENCY` | Hz | Automated | NOT RUN |
| Period | `CONFigure:PERiod` | `MEASure:PERiod?` | `PERIOD` | s | Automated | NOT RUN |
| Capacitance | `CONFigure:CAPacitance` | `MEASure:CAPacitance?` | `CAPACITANCE` | F | Automated | NOT RUN |
| Continuity | `CONFigure:CONTinuity` | `MEASure:CONTinuity?` | `CONTINUITY` | ohm | Automated | NOT RUN |
| Diode | `CONFigure:DIODe` | `MEASure:DIODe?` | `DIODE` | V | Automated | NOT RUN |
| Temperature RTD 2W | `CONFigure:TEMPerature RTD,DEF` | `MEASure:TEMPerature? RTD,DEF` | `TEMPERATURE + RTD_2W` | UNIT:TEMP? | Automated | NOT RUN |
| Temperature RTD 4W | `CONFigure:TEMPerature FRTD,DEF` | `MEASure:TEMPerature? FRTD,DEF` | `TEMPERATURE + RTD_4W` | UNIT:TEMP? | Automated | NOT RUN |
| Temperature thermistor 2W | `CONFigure:TEMPerature THERmistor,DEF` | `MEASure:TEMPerature? THERmistor,DEF` | `TEMPERATURE + THERMISTOR_2W` | UNIT:TEMP? | Automated | NOT RUN |

Notes: command syntax/optional arguments, defaults and external wiring must
be rechecked with the Programmer's Reference and device firmware before
HIL. Continuity and diode use fixed instrument ranges. Symbolic
`range_spec` and `resolution` are limited to values in the Quick
Reference; numeric manual range and aperture/NPLC controls belong to P1-03.

**Sources**
- https://www.keysight.com/us/en/assets/9018-61141/programming-guides/9018-61141.pdf
- https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf
- https://www.keysight.com/us/en/assets/7018-01326/data-sheets/5989-3738.pdf

## P1-03 Metrology commands (v0.3.1)

| Setting | SCPI set / query | Modes | Model limits/validation | Offline | Physical HIL |
| --- | --- | --- | --- | --- | --- |
| Manual range | `SENSe:<fn>:RANGe <range>` / `...? ` | DCV/ACV, DCI/ACI, RES/FRES, CAP | positive SI numeric bounded to documented 34411A range or MIN/MAX/AUTO; device selects achievable range | Tested | NOT RUN |
| Autorange | `SENSe:<fn>:RANGe:AUTO ON/OFF` / `...?` | same | bool | Tested | NOT RUN |
| Resolution | `SENSe:<fn>:RESolution <value>` / `...?` | DCV/ACV, DCI/ACI, RES/FRES | SI numeric positive or MIN/MAX/DEF; readback may round | Tested | NOT RUN |
| NPLC integration | `SENSe:<fn>:NPLC <PLCs>` / `...?` | DCV, DCI, RES/FRES, TEMP | 0.001/0.002 limited to 34411A; 0.006/0.02/0.06/0.2/1/2/10/100 | Tested | NOT RUN |
| DC aperture | `SENSe:<fn>:APERture <seconds>` / `...?` | DCV, DCI, RES/FRES, TEMP | 20µs–1s (34411A), set enable separately | Tested | NOT RUN |
| Aperture enable | `SENSe:<fn>:APERture:ENABled ON/OFF` / `...?` | DCV, DCI, RES, TEMP | bool; FRES uses documented `ENABle` suffix | Tested | NOT RUN |
| Autozero | `SENSe:<fn>:ZERO:AUTO ON/OFF/ONCE` / `...?` | DCV, DCI, RES, TEMP | 4-wire Ω autozero is not user-selectable | Tested | NOT RUN |
| AC RMS filter | `SENSe:VOLTage:AC:BANDwidth` or `CURRent:AC:BANDwidth` / `...?` | ACV/ACI | 3, 20, 200 Hz, MIN/MAX/DEF | Tested | NOT RUN |
| Frequency/period gate | `SENSe:FREQuency:APERture` or `PERiod:APERture` / `...?` | FREQ/PER | 0.001/0.01/0.1/1s or MIN/MAX/DEF | Tested | NOT RUN |
| DC input impedance | `SENSe:VOLTage:DC:IMPedance:AUTO ON/OFF` / `...?` | DCV | HI-Z for low voltage ranges only | Tested | NOT RUN |
| Ohms offset compensation | `SENSe:RESistance:OCOMpensated`, `FRESistance:OCOMpensated` / `...?` | RES/FRES | only fixed 100Ω/1kΩ/10kΩ; pre-query range/autorange | Tested | NOT RUN |
| Temperature units | `UNIT:TEMPerature C/F/K` / `...?` | TEMP | strict enum | Tested | NOT RUN |

**Source of truth:** 
- [34410A/11A User's Guide](https://www.keysight.com/qa/en/assets/9018-05586/user-manuals/9018-05586.pdf), pp. 17–23, 51–58.
- [34410A/34411A SCPI comparison](https://www.keysight.com/us/en/assets/7018-02044/white-papers-archived/5990-3515.pdf), SENSE subsystem pp. 8–12.

**Important:** Each setter targets the named SENSe function but does not
select the active function. The command family is documented, while the
actual connected firmware's behavior, limits, rounding and long-term
metrology performance are not hardware-verified. Do not assert HIL passed.

## v0.3.2 P1-03 metrology corrections

| Capability | SCPI set command | SCPI query | Python method | Qualification |
| --- | --- | --- | --- | --- |
| Frequency input voltage range | `SENSe:FREQuency:VOLTage:RANGe <V>` | `SENSe:FREQuency:VOLTage:RANGe?` | `metrology.set_range/get_range(F.FREQUENCY)` | Offline tested; HIL NOT RUN |
| Period input voltage range | `SENSe:PERiod:VOLTage:RANGe <V>` | `SENSe:PERiod:VOLTage:RANGe?` | `metrology.set_range/get_range(F.PERIOD)` | Offline tested; HIL NOT RUN |
| Frequency/period ACV filter | `SENSe:VOLTage:AC:BANDwidth 3/20/200` | `SENSe:VOLTage:AC:BANDwidth?` | `metrology.set_ac_bandwidth/get_ac_bandwidth` | Offline tested; HIL NOT RUN |
| NPLC mode selection | `SENSe:<DC/ohms/temp>:NPLC x`, `...:APERture:ENABled OFF` | `...:NPLC?`, `...:APERture:ENABled?` | `metrology.set_nplc()` | Offline tested; verify actual mode HIL |
| Aperture mode selection | `SENSe:<DC/ohms/temp>:APERture x`, `...:APERture:ENABled ON` | `...:APERture?`, `...:APERture:ENABled?` | `metrology.set_aperture()` | Offline tested; verify actual mode HIL |
| 4-wire resistance enable suffix | `SENSe:FRESistance:APERture:ENABle ON/OFF` | `SENSe:FRESistance:APERture:ENABle?` | Same NPLC/aperture setters | Offline tested; verify firmware spelling HIL |
| Temperature autozero | `SENSe:TEMPerature:ZERO:AUTO ON/OFF/ONCE` | `SENSe:TEMPerature:ZERO:AUTO?` | `metrology.set_autozero/get_autozero` | Only after configured 2-wire RTD/thermistor; 4-wire blocked |
| Pre-reading settings | SENSe queries + `READ?` | Metrology + reading | `metrology.read_with_settings()` | Software-sequenced, not atomic |

**Limits:** these command spellings are documented for the 34410A/34411A
family; real instrument acceptance, firmware behavior and settings/accuracy
must still be checked in hardware. This table is a command mapping, not an HIL report.

## v0.4.0 P2-07 math and per-function null command mapping

| Capability | SCPI set / action | SCPI readback | Driver method | Qualification |
| --- | --- | --- | --- | --- |
| Exclusive math mode | `CALCulate:FUNCtion AVERage/DB/DBM/LIMit`, `:STATe ON` | `CALCulate:FUNCtion?`, `:STATe?` | `math.enable_statistics/configure_*/selected_mode/enabled` | Offline; HIL NOT RUN |
| Statistics snapshot | No write | `CALCulate:AVERage:{AVERage,MINimum,MAXimum,SDEViation,PTPeak,COUNt}?` | `math.read_statistics()` | Count=0 produces no fabricated values |
| Explicit statistics clear | `CALCulate:AVERage:CLEar` | — | `math.clear_statistics(confirm=True)` | Destructive; opt-in only |
| dB reference | `CALCulate:DB:REFerence <value>` | `CALCulate:DB:REFerence?` | `math.configure_db/get_db_reference` | Voltage mode only |
| dBm reference | `CALCulate:DBM:REFerence <ohms>` | `CALCulate:DBM:REFerence?` | `math.configure_dbm/get_dbm_reference` | Documented resistances only |
| Limit thresholds | `CALCulate:LIMit:LOWer/UPPer <value>` | `:LOWer?`, `:UPPer?` | `math.configure_limits/get_limits/evaluate_limits` | Host-side comparison |
| Per-function null | `SENSe:<function>:NULL:VALue <value>`, `:STATe ON/OFF` | `:VALue?`, `:STATe?` | `math.set_null/get_null` | No deprecated CALC:NULL |
| Stop math | `CALCulate:STATe OFF` | `:STATe?` | `math.disable()` | No reset |

**User Guide warning:** enabling statistics, setting CALCulate:FUNCtion while
active, or changing measurement function clears accumulated statistics.
This implementation refuses silent math mode replacement but cannot
guarantee preservation when another controller changes the instrument.

## v0.5.0 P2-08 instrument states and display (software tested only)

| Feature | SCPI set/write | SCPI query | Python | HIL |
| --- | --- | --- | --- | --- |
| State status/metadata | None | `MEMory:STATe:VALid? <slot>`, `MEMory:STATe:NAME? <slot>` | `storage.get_state/list_states` | NOT RUN |
| Catalog | None | `MEMory:STATe:CATalog?` | `storage.catalog_raw` | NOT RUN |
| Save current config | `*SAV <1..4>` | `:VALid?` before/after | `storage.save_state` | NOT RUN |
| Recall config | `*RCL <1..4>` | `:VALid?` before | `storage.recall_state(confirm=True)` | NOT RUN |
| Delete config | `MEMory:STATe:DELete <1..4>` | `:VALid?` | `storage.delete_state(confirm=True)` | NOT RUN |
| Rename config | `MEMory:STATe:NAME <slot>,<NAME>` | `:NAME?` | `storage.rename_state` | NOT RUN |
| Power-on restore | `MEMory:STATe:RECall:SELect <slot>`, `:AUTO ON/OFF` | `:SELect?`, `:AUTO?` | `storage.get_power_on_state/set_power_on_recall` | NOT RUN |
| Window state | `DISPlay:WINDow1/2:STATe ON/OFF` | `:STATe?` | `display.set_enabled/get_enabled` | NOT RUN |
| Window text | `DISPlay:WINDow1/2:TEXT "<text>"`, `:TEXT:CLEar` | `:TEXT?` | `display.set_text/get_text/clear_text` | NOT RUN |
| Secondary feed | None | `DISPlay:WINDow2:TEXT:FEED?` | `display.get_secondary_feed` | NOT RUN |
| Beeper | `SYSTem:BEEPer:IMMediate`, `:STATe ON/OFF` | `:STATe?` | `display.beep/get_beeper_enabled/set_beeper_enabled` | NOT RUN |

**Distinction:** MEMory:STATe controls saved instrument configurations;
NVMEM/RDG_STORE hold logged measurements. State 0 is power-down reserved.
No implicit state overwrite, recall, restore change or display mutation.

## v0.6.0 P1-06 IEEE status and diagnostics

| Capability | Instrument command | API | Side effect | Offline / HIL |
| --- | --- | --- | --- | --- |
| Error queue | `SYSTem:ERRor?` | `status.get_error()`, `status.drain_errors(max_errors)` | Dequeues one error/query; max 256 bounded | Unit tests / NOT RUN |
| Status byte | `*STB?` | `status.status_byte()` | Non-consuming query | Unit tests / NOT RUN |
| Standard event register | `*ESR?` | `status.standard_event_register()` | **Read clears events** | Unit tests / NOT RUN |
| Standard event enable | `*ESE? / *ESE n` | `standard_event_enable/set_standard_event_enable` | Sets mask when explicit | Unit tests / NOT RUN |
| Service request enable | `*SRE? / *SRE n` | `service_request_enable/set_service_request_enable` | Sets mask when explicit | Unit tests / NOT RUN |
| Operation status | `STATus:OPERation:CONDition?/ENABle?/EVENt?` | `condition/enable/event("operation")` | Event read clears events | Unit tests / NOT RUN |
| Questionable status | `STATus:QUEStionable:CONDition?/ENABle?/EVENt?` | `condition/enable/event("questionable")` | Event read clears events | Unit tests / NOT RUN |
| Status enable | `STATus:OPERation:ENABle n`, `STATus:QUEStionable:ENABle n` | `set_enable(bank,n)` | Sets mask | Unit tests / NOT RUN |
| Instrument version | `SYSTem:VERSion?` | `snapshot(include_system=True)` | Query only | Unit tests / NOT RUN |
| Terminal selector | `ROUTe:TERMinals?` | `snapshot(include_system=True)` | Query only, cannot move switch | Unit tests / NOT RUN |
| Operation completion | `*OPC?` | `status.operation_complete(timeout_s)` | Blocks, bounded | Unit tests / NOT RUN |
| Explicit self test | `*TST?` | `status.self_test(confirm=True)` | **Potentially disruptive** | Unit tests / NOT RUN |

Keysight reference: [34410A/34411A SCPI comparison 5990-3515](https://www.keysight.com/us/en/assets/7018-02044/white-papers-archived/5990-3515.pdf),
pp. 3 and 13–14. The documentation confirms command families but is
not evidence that a particular instrument's firmware accepted the commands.

## v0.7.0 P1-04 acquisition triggers (offline tested, HIL NOT RUN)

| Function | Command | API | Constraints |
| --- | --- | --- | --- |
| Internal analog trigger | `TRIGger:SOURce INTernal` | `configure_volatile_acquisition(trigger_source="INTERNAL",trigger_level=...)` | 34411A-only; voltage/current/2-/4-wire Ω |
| Level crossing | `TRIGger:LEVel x`, `TRIGger:LEVel?` | configure or `set_level_trigger()` | finite numeric and bounded by selected function |
| Crossing slope | `TRIGger:SLOPe POS/NEG`, `TRIGger:SLOPe?` | configure or `set_level_trigger()` | POS/NEG |
| Pretrigger samples | `SAMPle:COUNt:PRETrigger n` | `pretrigger_count=n` | 34411A; 0 <= n < samples/trigger |
| Multiple trigger events | `TRIGger:COUNt n` | `trigger_count=n` | total count <= 1M volatile or <=50k NVM |
| Trigger source/readback | `TRIGger:SOURce?` | `trigger_settings_raw()` | non-consuming readback |
| Trigger output slope | `OUTPut:TRIGger:SLOPe POS/NEG` | `set_trigger_output_slope()` | electrical output not yet HIL-qualified |
| Explicit abort | `ABORt` | `stop_acquisition()` | state unknown on timeout; no auto retry |
| Completion | `DATA:POINts? RDG_STORE`, `*OPC?` | `wait_complete(timeout_s)` | deadline-bound, marks complete only on ack |

Official sources: Keysight [34410A/11A User Guide](https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf), triggering pages 68–74; [SCPI Command Comparison](https://www.keysight.com/us/en/assets/7018-02044/white-papers-archived/5990-3515.pdf), SAMPLE/TRIGGER sections.

## v0.8.0 P1-05 binary transfer / integrity coverage

| Feature | SCPI | API | Semantics | Verification |
| --- | --- | --- | --- | --- |
| Binary REAL32/REAL64 | `FORMat:DATA REAL,32/REAL,64` | `fetch_volatile_binary(precision_bits=32/64)` | Persistent setting restored if connected | Offline tested; HIL NOT RUN |
| Big-endian order | `FORMat:BORDer NORMal`, `FORMat:BORDer?` | Core IEEE block + IEEE754 decoder | Restore previous border on healthy exit | Offline tested; HIL NOT RUN |
| Non-destructive full fetch | `FETCh?` | `fetch_volatile_binary()` | One bounded full block up to 8MB, exact sample count | Offline tested; HIL NOT RUN |
| Destructive chunked drain | `DATA:REMove? n` | `transfer.iter_destructive_chunks(max_points=n)` | Explicit; count decrements verified; no uncertain replay | Offline tested; HIL NOT RUN |
| Reading count | `DATA:POINts? RDG_STORE` | Transfer and reconciliation | Must agree with requested transfer | Offline tested; HIL NOT RUN |
| Host export | File-system CSV + JSON + SHA256 | `export_volatile_bundle()` | Atomic sibling directory rename; no old files overwritten | Offline tested |
| Destructive R? read | `R?` | **Deliberately not provided** | Requires firmware retention HIL evidence | NOT RUN |

Core source: [scpi-driver-core pinned IEEE definite-length block reader](https://github.com/ami3go/scpi-driver-core/blob/1e03b6837f96f200dc28233490639f2f080e1791/src/scpi_driver_core/scpi/binary_block.py).
34411A command support: [Keysight command comparison](https://www.keysight.com/us/en/assets/7018-02044/white-papers-archived/5990-3515.pdf), FORMAT/DATA sections, and
[Keysight User Guide](https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf), Accessing Reading Memory.

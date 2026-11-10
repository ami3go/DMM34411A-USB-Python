# Keysight/Agilent 34411A — SCPI measurement command coverage (v0.3.0)

**Baseline:** v0.4.0 metrology increment (measurement coverage originally v0.3.0), of DMM34411A-FULL-API-001.
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

## v0.4.0 metrology SENSe command coverage (offline tested; HIL NOT RUN)

| Function group | SCPI set command | SCPI readback | Python API | Notes / constraints |
| --- | --- | --- | --- | --- |
| Range, DC/AC V/I, Ω, C | `SENSe:<mode>:RANGe <value>` | `SENSe:<mode>:RANGe?` | `set_range/get_range` | numeric or MIN/MAX/DEF; no auto for temp/diode/continuity |
| Frequency/period input amplitude | `SENSe:FREQuency:VOLTage:RANGe <value>`, `SENSe:PERiod:VOLTage:RANGe <value>` | corresponding `RANGe?` | `set_range/get_range` | range in volts, not Hz or seconds |
| Autorange | `SENSe:<mode>:RANGe:AUTO ON/OFF` | `RANGe:AUTO?` | `set_autorange/get_autorange` | 0/1 readback |
| Resolution (V/I/Ω) | `SENSe:<mode>:RESolution <value>` | `RESolution?` | `set_resolution/get_resolution` | base SI unit |
| NPLC (DC/temp) | `SENSe:<mode>:NPLC <value>` | `NPLC?` | `set_nplc/get_nplc` | 34411A enumerated integration choices |
| Aperture (DC/temp) | `SENSe:<mode>:APERture <seconds>` | `APERture?` | `set_aperture/get_aperture` | 20 µs to 1 s |
| Aperture mode | `SENSe:<mode>:APERture:ENABled ON/OFF` | `:ENABled?` | `set_aperture_enabled/get_aperture_enabled` | 0/1 readback |
| Autozero (DCV,DCI,2WΩ,2W temp) | `SENSe:<mode>:ZERO:AUTO ON/OFF/ONCE` | `:ZERO:AUTO?` | `set_autozero/get_autozero` | 4W always-on |
| AC bandwidth | `SENSe:VOLTage:AC:BANDwidth 3/20/200`, current equivalent | `:BANDwidth?` | `set_ac_bandwidth/get_ac_bandwidth` | FREQ/PER share AC voltage filter |
| Frequency/period gate | `SENSe:FREQuency:APERture <seconds>`, period equivalent | `:APERture?` | `set_gate_time/get_gate_time` | 1/10/100/1000 ms |
| DCV impedance | `SENSe:VOLTage:DC:IMPedance:AUTO ON/OFF` | `:AUTO?` | `set_input_impedance_auto/get_input_impedance_auto` | HI-Z only on lower ranges |
| Resistance offset compensation | `SENSe:RESistance:OCOMpensated ON/OFF`, FRES equivalent | `:OCOMpensated?` | `set_offset_compensated/get_offset_compensated` | guard fixed 100 Ω/1 kΩ/10 kΩ |
| Live snapshot | No write | Applicable SENSe queries | `get_settings(function)` | no cached defaults; not physically atomic |

Status: **documented + offline simulated only**. Physical command acceptance and
meter-side rounding/side effects are unqualified; compare raw logs against the
34411A firmware during operator-authorized HIL.

Notes: command syntax/optional arguments, defaults and external wiring must
be rechecked with the Programmer's Reference and device firmware before
HIL. Continuity and diode use fixed instrument ranges. Symbolic
`range_spec` and `resolution` are limited to values in the Quick
Reference; numeric manual range and aperture/NPLC controls belong to P1-03.

**Sources**
- https://www.keysight.com/us/en/assets/9018-61141/programming-guides/9018-61141.pdf
- https://www.keysight.com/us/en/assets/9018-05586/user-manuals/9018-05586.pdf
- https://www.keysight.com/us/en/assets/7018-01326/data-sheets/5989-3738.pdf

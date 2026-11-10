# Keysight/Agilent 34411A — SCPI measurement command coverage (v0.3.0)

**Baseline:** v0.3.0 implementation increment of DMM34411A-FULL-API-001.
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

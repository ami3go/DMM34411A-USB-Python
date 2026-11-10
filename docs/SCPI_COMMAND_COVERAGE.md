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

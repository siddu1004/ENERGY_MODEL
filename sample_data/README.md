# Sample data (SYNTHETIC)

These files are **made up**. They stand in for the client's real files until those arrive. They are not measurements.

| File | Stands in for | Contents |
|---|---|---|
| `sample_building.usdz` | A RoomPlan / LiDAR scan | One office floor, 30 × 20 m (600 m²), 2.7 m high, 9 rooms, windows, doors, a few furniture boxes. Metres, Y-up. Geometry only. |
| `sample_building_plan.png` | — | Top-down preview of the USDZ |
| `sample_building_ground_truth.json` | — | Expected areas and volumes, to test a USDZ parser against |
| `sample_chiller_calculations.xlsx` | The client's Excel calculation sheets | 250 TR chiller, 6 → 12 °C, 0.75 kW/TR, 12 h/day. Live formulas, with a source tag on every input. |

## Building model: key numbers
- Floor area 600 m², volume 1,620 m³
- Exterior wall area 270 m² (gross), window area 56.2 m², window-to-wall ratio about 21%

**Not in the model** (same as a real scan): materials, U-values, SHGC, true north, number of floors, occupancy and HVAC zoning.

## Excel workbook: key results (baseline, full load)
| Quantity | Value |
|---|---|
| Cooling capacity | 879.2 kW |
| CHW flow | 35.0 kg/s = 126.0 m³/h = 555 gpm |
| Chiller power / COP | 187.5 kW / 4.69 |
| CHW pump | 15.2 kW |
| CW pump + tower fans | 18.5 + 15.0 kW |
| AHU fans | 59.6 kW |
| **Total system** | **295.8 kW (1.18 kW/TR all-in)** |
| Energy | 3,549 kWh/day, about 106,500 kWh/month, about 1.28 GWh/yr |
| Cost (at an assumed ₹8/kWh) | about ₹8.5 lakh/month |

### Deliberate inconsistency (to test proactive questions)
A 250 TR chiller is far too big for a 600 m² floor: that works out to 2.4 m²/TR, against a typical 18–30 m²/TR for offices. The likely explanation is that the chiller serves the whole building, but the scan covers only one floor. The number of floors served is left **UNKNOWN** on purpose, and the `Building_Load_Check` sheet flags it. The system should ask the engineer for it rather than guess.

## Regenerate
```bash
pip install usd-core openpyxl matplotlib numpy
python3 scripts/generate_sample_building.py
python3 scripts/generate_sample_excel.py
```
Open the workbook in Excel and it recalculates. To store cached values without Excel, run it through LibreOffice: `soffice --headless --convert-to xlsx`.

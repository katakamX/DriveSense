"""Parses the OBD2 CSV export format: `sample_obd.csv`'s real header, not a
guessed GPS/accelerometer shape.

`Driver_Aggression_pct` and `Total_Vehicle_Stress_pct` are in the source file
but deliberately not represented here. Per STEP4_FINDINGS.md they are a
different, disagreeing signal from this app's own risk bands (one tracks
pedal behaviour, the other tracks drivetrain/mechanical load, and they peak
at different moments in the same recording) — this module does not parse,
store, or expose them, so there is no path for them to leak into a risk
assessment or a UI panel built for this app's own vocabulary.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO

REQUIRED_COLUMNS = (
    "Time_s",
    "Speed_kmh",
    "RPM",
    "Gear",
    "Throttle_pct",
    "Brake_pct",
    "Boost_bar",
    "Req_Fuel_pct",
    "Inj_Fuel_pct",
    "Torque_Nm",
    "Power_HP",
    "Engine_Stress_pct",
    "Drivetrain_Stress_pct",
    "Clutch_Stress_pct",
)


@dataclass(frozen=True, slots=True)
class ObdRow:
    """One CSV row, at the file's native ~0.03s sample interval."""

    time_s: float
    speed_kmh: float
    rpm: float
    gear: int
    throttle_pct: float
    brake_pct: float
    boost_bar: float
    req_fuel_pct: float
    inj_fuel_pct: float
    torque_nm: float
    power_hp: float
    engine_stress_pct: float
    drivetrain_stress_pct: float
    clutch_stress_pct: float


class ObdCsvError(ValueError):
    """The upload is not this format — a 400, not a 500, at the API boundary."""


def parse_obd_csv(text: str) -> list[ObdRow]:
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames is None:
        raise ObdCsvError("empty file")
    missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
    if missing:
        raise ObdCsvError(f"missing required column(s): {', '.join(missing)}")

    rows: list[ObdRow] = []
    for line_number, raw in enumerate(reader, start=2):  # header is line 1
        try:
            rows.append(
                ObdRow(
                    time_s=float(raw["Time_s"]),
                    speed_kmh=float(raw["Speed_kmh"]),
                    rpm=float(raw["RPM"]),
                    gear=int(float(raw["Gear"])),
                    throttle_pct=float(raw["Throttle_pct"]),
                    brake_pct=float(raw["Brake_pct"]),
                    boost_bar=float(raw["Boost_bar"]),
                    req_fuel_pct=float(raw["Req_Fuel_pct"]),
                    inj_fuel_pct=float(raw["Inj_Fuel_pct"]),
                    torque_nm=float(raw["Torque_Nm"]),
                    power_hp=float(raw["Power_HP"]),
                    engine_stress_pct=float(raw["Engine_Stress_pct"]),
                    drivetrain_stress_pct=float(raw["Drivetrain_Stress_pct"]),
                    clutch_stress_pct=float(raw["Clutch_Stress_pct"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ObdCsvError(f"line {line_number}: {exc}") from exc

    if not rows:
        raise ObdCsvError("no data rows")
    return rows

from pathlib import Path

import pytest

from app.core.obd.parse import ObdCsvError, parse_obd_csv

FIXTURE = Path(__file__).parent / "fixtures" / "sample_obd.csv"


def test_parses_real_fixture() -> None:
    rows = parse_obd_csv(FIXTURE.read_text())
    assert len(rows) == 1780
    first = rows[0]
    assert first.time_s == 0.03
    assert first.speed_kmh == 0.0
    assert first.rpm == 749
    assert first.gear == 0


def test_rows_are_time_ordered_as_given() -> None:
    rows = parse_obd_csv(FIXTURE.read_text())
    times = [r.time_s for r in rows]
    assert times == sorted(times)


def test_missing_required_column_is_rejected() -> None:
    with pytest.raises(ObdCsvError, match="missing required column"):
        parse_obd_csv("Time_s,Speed_kmh\n0.03,0.0\n")


def test_empty_file_is_rejected() -> None:
    with pytest.raises(ObdCsvError, match="empty file"):
        parse_obd_csv("")


def test_no_data_rows_is_rejected() -> None:
    header = ",".join(
        [
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
        ]
    )
    with pytest.raises(ObdCsvError, match="no data rows"):
        parse_obd_csv(header + "\n")


def test_malformed_row_names_its_line_number() -> None:
    header = ",".join(
        [
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
        ]
    )
    bad_row = "0.03,not-a-number,749,0,0,0,0.0,15.0,15.0,-1,0,4,0,0"
    with pytest.raises(ObdCsvError, match="line 2"):
        parse_obd_csv(header + "\n" + bad_row + "\n")


def test_precomputed_stress_columns_are_not_parsed() -> None:
    """Decision: ignore Driver_Aggression_pct / Total_Vehicle_Stress_pct
    entirely (STEP4_FINDINGS.md) — `ObdRow` must not carry them."""
    rows = parse_obd_csv(FIXTURE.read_text())
    field_names = {f for f in rows[0].__dataclass_fields__}
    assert "driver_aggression_pct" not in field_names
    assert "total_vehicle_stress_pct" not in field_names

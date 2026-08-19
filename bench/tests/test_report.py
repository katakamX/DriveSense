from __future__ import annotations

from drivesense_bench.load_gen import LevelResult
from drivesense_bench.report import format_report


def make_level(concurrency: int, latencies_ms: list[float]) -> LevelResult:
    return LevelResult(
        concurrency=concurrency,
        wall_duration_s=1.0,
        frames_sent=len(latencies_ms),
        frames_failed=0,
        frames_dropped=0,
        latencies_ms=latencies_ms,
    )


def test_reports_no_crossover_when_every_level_stays_under_target() -> None:
    report = format_report([make_level(1, [10.0, 20.0])], target_ms=150.0)
    assert "stayed under 150" in report
    assert "crossed" not in report


def test_reports_the_first_level_that_crosses_the_target() -> None:
    levels = [
        make_level(1, [50.0] * 10),
        make_level(10, [200.0] * 10),
    ]
    report = format_report(levels, target_ms=150.0)
    assert "crossed 150 ms at 10 concurrent trips" in report


def test_empty_level_list_says_so_rather_than_crashing() -> None:
    assert format_report([]) == "No levels ran."

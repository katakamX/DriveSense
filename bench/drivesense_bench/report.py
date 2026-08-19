"""Plain-text table for a `load_gen.ramp()` result. No file I/O here --
`__main__.py` prints it, and step 6's report document quotes it."""

from __future__ import annotations

from drivesense_bench.load_gen import LATENCY_TARGET_MS, LevelResult


def format_report(levels: list[LevelResult], target_ms: float = LATENCY_TARGET_MS) -> str:
    if not levels:
        return "No levels ran."

    header = (
        f"{'concurrency':>11} {'sent':>7} {'failed':>7} {'dropped':>8} "
        f"{'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'fps':>8}"
    )
    rows = [header]
    crossover: int | None = None
    for level in levels:
        p95 = level.percentile(0.95)
        rows.append(
            f"{level.concurrency:>11} {level.frames_sent:>7} {level.frames_failed:>7} "
            f"{level.frames_dropped:>8} "
            f"{_fmt(level.percentile(0.50)):>8} {_fmt(p95):>8} {_fmt(level.percentile(0.99)):>8} "
            f"{level.throughput_fps:>8.1f}"
        )
        if crossover is None and p95 is not None and p95 > target_ms:
            crossover = level.concurrency

    if crossover is not None:
        verdict = f"p95 crossed {target_ms:.0f} ms at {crossover} concurrent trips."
    else:
        verdict = (
            f"p95 stayed under {target_ms:.0f} ms through "
            f"{levels[-1].concurrency} concurrent trips."
        )

    return "\n".join([*rows, "", verdict])


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"

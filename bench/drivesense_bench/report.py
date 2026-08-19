"""Plain-text table for a `load_gen.ramp()` result. No file I/O here --
`__main__.py` prints it, and step 6's report document quotes it."""

from __future__ import annotations

from drivesense_bench.load_gen import LATENCY_TARGET_MS, LevelResult


def format_report(levels: list[LevelResult], target_ms: float = LATENCY_TARGET_MS) -> str:
    if not levels:
        return "No levels ran."

    header = (
        f"{'concurrency':>11} {'sent':>7} {'failed':>7} {'dropped':>8} {'ws_fail':>7} "
        f"{'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'fps':>8}"
    )
    rows = [header]
    collapsed: int | None = None
    crossover: int | None = None
    for level in levels:
        p95 = level.percentile(0.95)
        rows.append(
            f"{level.concurrency:>11} {level.frames_sent:>7} {level.frames_failed:>7} "
            f"{level.frames_dropped:>8} {level.listener_connect_failures:>7} "
            f"{_fmt(level.percentile(0.50)):>8} {_fmt(p95):>8} {_fmt(level.percentile(0.99)):>8} "
            f"{level.throughput_fps:>8.1f}"
        )
        if collapsed is None and crossover is None:
            if level.collapsed:
                collapsed = level.concurrency
            elif p95 is not None and p95 > target_ms:
                crossover = level.concurrency

    if collapsed is not None:
        verdict = (
            f"No frame completed a round trip at {collapsed} concurrent trips "
            f"(every send failed, or every listener socket failed to connect) -- "
            f"a capacity collapse, not a graceful crossing of the {target_ms:.0f} ms target."
        )
    elif crossover is not None:
        verdict = f"p95 crossed {target_ms:.0f} ms at {crossover} concurrent trips."
    else:
        verdict = (
            f"p95 stayed under {target_ms:.0f} ms through "
            f"{levels[-1].concurrency} concurrent trips."
        )

    total_ws_failures = sum(level.listener_connect_failures for level in levels)
    if total_ws_failures:
        verdict += (
            f" ({total_ws_failures} trip listener socket(s) never connected across the run -- "
            "their frames count as dropped, not as a latency sample.)"
        )

    return "\n".join([*rows, "", verdict])


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"

"""Shared stats utilities for benchmark scripts."""

import statistics
from dataclasses import dataclass


@dataclass
class LatencyStats:
    mean: float
    p50: float
    p95: float
    p99: float
    max: float
    count: int


def compute_stats(values: list[float]) -> LatencyStats:
    if not values:
        return LatencyStats(0.0, 0.0, 0.0, 0.0, 0.0, 0)
    s = sorted(values)
    n = len(s)

    def pct(p: float) -> float:
        k = max(0, min(n - 1, int(round(p / 100 * (n - 1)))))
        return round(s[k], 2)

    return LatencyStats(
        mean=round(statistics.mean(s), 2),
        p50=pct(50),
        p95=pct(95),
        p99=pct(99),
        max=round(s[-1], 2),
        count=n,
    )

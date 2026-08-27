"""Interval estimates for binomial rates.

Wilson rather than normal-approximation intervals, because the rates here sit near 0
and 1 where the normal approximation gives nonsense (and, at 0/33, gives a
zero-width interval).
"""

from __future__ import annotations

import math

Z95 = 1.959963984540054


def wilson(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. Returns (lo, hi)."""
    if n == 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def diff_ci(k1: int, n1: int, k2: int, n2: int, z: float = Z95) -> tuple[float, float]:
    """Newcombe interval for the difference of two proportions (p1 - p2)."""
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    p1 = k1 / n1 if n1 else 0.0
    p2 = k2 / n2 if n2 else 0.0
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return (max(-1.0, lo), min(1.0, hi))

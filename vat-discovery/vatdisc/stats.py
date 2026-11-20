from __future__ import annotations

import math


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - h) / d), min(1.0, (c + h) / d))


def rule_of_three(n: int) -> float:
    """Upper 95% bound on a rate when 0 events were seen in n trials."""
    return 3.0 / n if n else 1.0


def cluster_total(counts: list[int], population_clusters: int, z: float = 1.96) -> tuple[float, float, float]:
    """Estimate a population total from a simple random sample of clusters.

    counts             : the quantity observed in each sampled cluster (index block)
    population_clusters: how many clusters exist in total
    Returns (estimate, low, high).  Uses the between-cluster variance, with the
    finite-population correction.
    """
    b = len(counts)
    if b < 2:
        return (float("nan"),) * 3
    mean = sum(counts) / b
    var = sum((c - mean) ** 2 for c in counts) / (b - 1)
    fpc = 1 - b / population_clusters
    est = population_clusters * mean
    se = population_clusters * math.sqrt(var / b * fpc)
    return est, max(0.0, est - z * se), est + z * se

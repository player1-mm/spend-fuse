"""
Threshold + rate-of-change evaluation engine.

A "rule" can guard against two distinct kinds of danger, and either one
alone is enough to trip the fuse:

  * an absolute ceiling  -- total spend has crossed a static dollar amount.
  * a rate ceiling       -- spend is *accelerating* faster than
                             `max_rate_usd_per_minute` over a trailing
                             `window_minutes` window, computed as the slope
                             of a least-squares linear regression over the
                             (timestamp, total_usd) samples in that window.

A naive "delta between the last two polls" rate estimate is noisy and easy
to fool with a single quiet poll; a regression slope over the whole window
smooths that out while still reacting within one window's length.

Rules are edge-triggered: a rule only fires the moment its condition
transitions from not-breached to breached, not on every poll while it
stays breached. This keeps actions like `kill_process` or a webhook call
from firing repeatedly every poll interval for as long as the breach
persists.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

MIN_POLL_INTERVAL_SECONDS = 1
MAX_POLL_INTERVAL_SECONDS = 3600
DEFAULT_POLL_INTERVAL_SECONDS = 5

MIN_MAX_HISTORY_SAMPLES = 10
MAX_MAX_HISTORY_SAMPLES = 100_000
DEFAULT_MAX_HISTORY_SAMPLES = 500


def clamp_poll_interval(seconds: float) -> float:
    return max(MIN_POLL_INTERVAL_SECONDS, min(MAX_POLL_INTERVAL_SECONDS, seconds))


def clamp_max_history(n: int) -> int:
    return max(MIN_MAX_HISTORY_SAMPLES, min(MAX_MAX_HISTORY_SAMPLES, n))


@dataclass(frozen=True)
class Sample:
    timestamp: float
    total_usd: float


@dataclass(frozen=True)
class Rule:
    name: str
    actions: List[str] = field(default_factory=list)
    max_total_usd: Optional[float] = None
    max_rate_usd_per_minute: Optional[float] = None
    window_minutes: Optional[float] = None

    def __post_init__(self):
        has_absolute = self.max_total_usd is not None
        has_rate = self.max_rate_usd_per_minute is not None and self.window_minutes is not None
        if not has_absolute and not has_rate:
            raise ValueError(
                f"rule '{self.name}' must set max_total_usd and/or "
                f"(max_rate_usd_per_minute + window_minutes)"
            )
        if self.window_minutes is not None and self.window_minutes <= 0:
            raise ValueError(f"rule '{self.name}': window_minutes must be > 0")
        if not self.actions:
            raise ValueError(f"rule '{self.name}' has no actions configured")


@dataclass(frozen=True)
class Trigger:
    rule: Rule
    reason: str
    total_usd: float
    rate_usd_per_minute: Optional[float]
    timestamp: float


def _linear_regression_slope(points: List[Sample]) -> Optional[float]:
    """Least-squares slope (usd/second) of total_usd over timestamp."""
    n = len(points)
    if n < 2:
        return None
    mean_t = sum(p.timestamp for p in points) / n
    mean_y = sum(p.total_usd for p in points) / n
    numerator = sum((p.timestamp - mean_t) * (p.total_usd - mean_y) for p in points)
    denominator = sum((p.timestamp - mean_t) ** 2 for p in points)
    if denominator == 0:
        return None
    return numerator / denominator


class SpendEngine:
    """Tracks a bounded history of cost samples and evaluates rules against it."""

    def __init__(self, rules: List[Rule], max_history: int = DEFAULT_MAX_HISTORY_SAMPLES):
        if not rules:
            raise ValueError("at least one rule is required")
        names = [r.name for r in rules]
        if len(names) != len(set(names)):
            raise ValueError("rule names must be unique")
        self.rules = rules
        self.history: Deque[Sample] = deque(maxlen=clamp_max_history(max_history))
        self._rule_breached: Dict[str, bool] = {r.name: False for r in rules}

    def add_sample(self, sample: Sample) -> None:
        self.history.append(sample)

    def samples_in_window(self, window_minutes: float, now: Optional[float] = None) -> List[Sample]:
        if not self.history:
            return []
        now = self.history[-1].timestamp if now is None else now
        window_seconds = window_minutes * 60
        return [s for s in self.history if now - s.timestamp <= window_seconds]

    def compute_rate_usd_per_minute(self, window_minutes: float, now: Optional[float] = None) -> Optional[float]:
        points = self.samples_in_window(window_minutes, now=now)
        slope_per_sec = _linear_regression_slope(points)
        if slope_per_sec is None:
            return None
        return slope_per_sec * 60.0

    def evaluate(self) -> List[Trigger]:
        """Check all rules against current history; return newly-fired triggers."""
        if not self.history:
            return []
        latest = self.history[-1]
        triggers: List[Trigger] = []

        for rule in self.rules:
            reasons: List[str] = []
            rate: Optional[float] = None

            if rule.max_rate_usd_per_minute is not None and rule.window_minutes is not None:
                rate = self.compute_rate_usd_per_minute(rule.window_minutes, now=latest.timestamp)
                if rate is not None and rate >= rule.max_rate_usd_per_minute:
                    reasons.append(
                        f"spend accelerating: ${rate:.2f}/min >= "
                        f"${rule.max_rate_usd_per_minute:.2f}/min over "
                        f"{rule.window_minutes:g} min window"
                    )

            if rule.max_total_usd is not None and latest.total_usd >= rule.max_total_usd:
                reasons.append(
                    f"absolute ceiling exceeded: ${latest.total_usd:.2f} >= ${rule.max_total_usd:.2f}"
                )

            is_breached = bool(reasons)
            was_breached = self._rule_breached[rule.name]
            if is_breached and not was_breached:
                triggers.append(
                    Trigger(
                        rule=rule,
                        reason="; ".join(reasons),
                        total_usd=latest.total_usd,
                        rate_usd_per_minute=rate,
                        timestamp=latest.timestamp,
                    )
                )
            self._rule_breached[rule.name] = is_breached

        return triggers

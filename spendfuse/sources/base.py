from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class CostSample:
    timestamp: float
    total_usd: float


class CostSource(ABC):
    """A pluggable source of "how much have we spent so far" readings.

    Implementations must be safe to poll repeatedly and cheaply -- `watch`
    calls `get_current_spend()` once per poll interval.
    """

    @abstractmethod
    def get_current_spend(self) -> CostSample:
        """Return the current point-in-time total spend reading."""
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup hook (closing network clients, etc). No-op by default."""
        return None

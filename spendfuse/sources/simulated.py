"""Zero-dependency cost source for demos and tests.

Backs a running total with a tiny JSON state file on disk. This is
deliberately the two things the scoping note asked for at once: it's a
"local file" cost source (state persists as JSON) and a "simple counter
that increments" (each call bumps the total by `increment_usd`).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .base import CostSample, CostSource


class SimulatedCostSource(CostSource):
    def __init__(self, state_file, initial_usd: float = 0.0, increment_usd: float = 0.0):
        self.state_file = Path(state_file)
        self.initial_usd = initial_usd
        self.increment_usd = increment_usd
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.state_file.exists():
            self._write_total(self.initial_usd)

    def _read_total(self) -> float:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return float(data.get("total_usd", self.initial_usd))
        except (json.JSONDecodeError, FileNotFoundError, ValueError):
            return self.initial_usd

    def _write_total(self, total_usd: float) -> None:
        self.state_file.write_text(json.dumps({"total_usd": total_usd}), encoding="utf-8")

    def get_current_spend(self) -> CostSample:
        total = self._read_total() + self.increment_usd
        self._write_total(total)
        return CostSample(timestamp=time.time(), total_usd=total)

    def reset(self, total_usd: float = 0.0) -> None:
        """Reset the persisted counter -- handy between demo runs."""
        self._write_total(total_usd)

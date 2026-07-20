"""Pluggable cost-source interface and factory.

Adding a new provider (GCP, Azure, ...) means writing one class that
implements `CostSource.get_current_spend()` and registering it in
`build_cost_source()` below -- nothing in `engine.py` or the CLI needs to
change.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from .base import CostSample, CostSource
from .simulated import SimulatedCostSource

__all__ = ["CostSample", "CostSource", "build_cost_source"]


def build_cost_source(cost_source_type: str, params: Dict, base_dir: Path) -> CostSource:
    if cost_source_type == "simulated":
        state_file = params.get("state_file", ".spendfuse/simulated_state.json")
        state_path = Path(state_file)
        if not state_path.is_absolute():
            state_path = base_dir / state_path
        return SimulatedCostSource(
            state_file=state_path,
            initial_usd=float(params.get("initial_usd", 0.0)),
            increment_usd=float(params.get("increment_usd", 0.0)),
        )

    if cost_source_type == "aws":
        from .aws_cost_explorer import AWSCostExplorerSource

        return AWSCostExplorerSource(
            profile=params.get("profile"),
            granularity=params.get("granularity", "DAILY"),
            lookback_days=int(params.get("lookback_days", 7)),
        )

    raise ValueError(f"unknown cost_source type: '{cost_source_type}' (expected 'simulated' or 'aws')")

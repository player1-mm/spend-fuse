"""Canned demo scenarios for `spendfuse simulate`.

Each scenario is a scripted sequence of (elapsed_seconds, total_usd)
readings fed straight into a fresh SpendEngine using synthetic timestamps.
Synthetic timestamps let a scenario compress several simulated minutes of
spend history into a few real seconds of demo runtime, while keeping the
rate-of-change math (which depends on real elapsed *simulated* time)
meaningful -- a short `time.sleep` between steps is purely visual pacing,
not part of the simulated clock.

Actions configured in the rule actually fire, exactly as they would during
a real `watch` run, so this is a genuine end-to-end proof the fuse works,
not a canned printout.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

from .actions import build_actions
from .config import Config
from .engine import Sample, SpendEngine
from .eventlog import EventLog

STEP_PACING_SECONDS = 0.15


def _build_steps_runaway_loop() -> List[Tuple[float, float]]:
    """Ramps spend up with accelerating increments -- a misbehaving loop
    whose cost per call keeps growing, e.g. retries that themselves spawn
    more retries. Crosses both the rate and absolute ceilings of the
    default config well within the 6 simulated minutes below."""
    steps = []
    total = 0.0
    elapsed = 0.0
    increment = 2.0
    for _ in range(24):
        elapsed += 15
        increment *= 1.35
        total += increment
        steps.append((elapsed, round(total, 2)))
    return steps


def _build_steps_normal() -> List[Tuple[float, float]]:
    """Slow, steady spend that stays comfortably under both ceilings."""
    steps = []
    total = 0.0
    elapsed = 0.0
    for _ in range(24):
        elapsed += 15
        total += 0.8
        steps.append((elapsed, round(total, 2)))
    return steps


SCENARIOS = {
    "runaway_loop": _build_steps_runaway_loop,
    "normal": _build_steps_normal,
}


def run_scenario(name: str, config: Config, eventlog: EventLog) -> Dict[str, Any]:
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario '{name}' (expected one of: {', '.join(SCENARIOS)})")

    steps = SCENARIOS[name]()
    engine = SpendEngine(config.rules, max_history=config.max_history_samples)
    actions = build_actions(config.actions)

    start_time = time.time()
    fired: List[Dict[str, Any]] = []

    print(f"--- spendfuse simulate --scenario {name} ---")
    for elapsed, total in steps:
        ts = start_time + elapsed
        engine.add_sample(Sample(timestamp=ts, total_usd=total))
        rate = None
        for rule in engine.rules:
            if rule.window_minutes is not None:
                rate = engine.compute_rate_usd_per_minute(rule.window_minutes, now=ts)
                break

        rate_str = f"{rate:6.2f}/min" if rate is not None else "   n/a  "
        print(f"[t=+{elapsed:>5.0f}s] spend=${total:8.2f}  rate={rate_str}")
        eventlog.append(
            {
                "type": "check",
                "scenario": name,
                "elapsed_seconds": elapsed,
                "total_usd": total,
                "rate_usd_per_minute": rate,
            }
        )

        triggers = engine.evaluate()
        for trig in triggers:
            print(f"  !! FUSE TRIPPED: rule '{trig.rule.name}' -- {trig.reason}")
            context = {
                "rule_name": trig.rule.name,
                "reason": trig.reason,
                "total_usd": trig.total_usd,
                "rate_usd_per_minute": trig.rate_usd_per_minute,
                "timestamp": trig.timestamp,
            }
            action_results = []
            for action_name in trig.rule.actions:
                action = actions[action_name]
                result = action.execute(context)
                status = "OK" if result.success else "FAILED"
                print(f"       -> action '{action_name}' ({result.action_type}): {status} - {result.detail}")
                action_results.append(
                    {
                        "action_name": result.action_name,
                        "action_type": result.action_type,
                        "success": result.success,
                        "detail": result.detail,
                    }
                )
            eventlog.append(
                {
                    "type": "trigger",
                    "scenario": name,
                    "rule_name": trig.rule.name,
                    "reason": trig.reason,
                    "total_usd": trig.total_usd,
                    "rate_usd_per_minute": trig.rate_usd_per_minute,
                    "actions": action_results,
                }
            )
            fired.append({"rule_name": trig.rule.name, "reason": trig.reason})

        time.sleep(STEP_PACING_SECONDS)

    print(f"--- scenario '{name}' complete: {len(fired)} trigger(s) fired ---")
    return {"scenario": name, "triggers": fired}

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Optional

from .actions import build_actions
from .config import Config, ConfigError, default_config_path, load_config, write_default_config
from .engine import Sample, SpendEngine
from .eventlog import EventLog
from .scenarios import SCENARIOS, run_scenario
from .sources import build_cost_source


def _resolve_config_path(arg: Optional[str]) -> Path:
    return Path(arg) if arg else default_config_path()


def cmd_init(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    try:
        write_default_config(path, force=args.force)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Created {path}")
    print("Edit it to add/adjust rules and actions, then run:")
    print("  spendfuse simulate --scenario runaway_loop")
    print("  spendfuse watch")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    try:
        config: Config = load_config(path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    eventlog = EventLog(config.log_file)
    source = build_cost_source(config.cost_source_type, config.cost_source_params, config.base_dir)
    engine = SpendEngine(config.rules, max_history=config.max_history_samples)
    actions = build_actions(config.actions)

    print(f"spendfuse watch: source={config.cost_source_type} interval={config.poll_interval_seconds}s")
    print("Press Ctrl+C to stop.")

    iterations = 0
    try:
        while args.max_iterations is None or iterations < args.max_iterations:
            try:
                reading = source.get_current_spend()
                engine.add_sample(Sample(timestamp=reading.timestamp, total_usd=reading.total_usd))
                triggers = engine.evaluate()

                print(f"[poll] spend=${reading.total_usd:.2f}")
                eventlog.append({"type": "check", "total_usd": reading.total_usd})

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
                        result = actions[action_name].execute(context)
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
                            "rule_name": trig.rule.name,
                            "reason": trig.reason,
                            "total_usd": trig.total_usd,
                            "rate_usd_per_minute": trig.rate_usd_per_minute,
                            "actions": action_results,
                        }
                    )
            except Exception as exc:  # keep the loop alive across a transient poll failure
                print(f"  poll failed: {exc}", file=sys.stderr)
                eventlog.append({"type": "poll_error", "error": str(exc)})

            iterations += 1
            if args.max_iterations is None or iterations < args.max_iterations:
                time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        print("\nstopping (Ctrl+C)")
    finally:
        source.close()

    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    try:
        config: Config = load_config(path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    eventlog = EventLog(config.log_file)
    run_scenario(args.scenario, config, eventlog)
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    path = _resolve_config_path(args.config)
    try:
        config: Config = load_config(path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    eventlog = EventLog(config.log_file)
    events = eventlog.read_recent(args.limit)
    if not events:
        print(f"(no events in {config.log_file})")
        return 0

    for event in events:
        ts = event.get("ts_iso", "?")
        etype = event.get("type", "?")
        if etype == "check":
            print(f"{ts}  check   spend=${event.get('total_usd', 0):.2f}")
        elif etype == "trigger":
            print(f"{ts}  TRIGGER rule={event.get('rule_name')} reason={event.get('reason')}")
            for a in event.get("actions", []):
                status = "OK" if a.get("success") else "FAILED"
                print(f"           action={a.get('action_name')} ({a.get('action_type')}): {status} - {a.get('detail')}")
        elif etype == "poll_error":
            print(f"{ts}  ERROR   {event.get('error')}")
        else:
            print(f"{ts}  {etype}  {event}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spendfuse",
        description="Real-time circuit breaker for cloud spend: watch a cost signal, trip the fuse the instant a threshold is crossed.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_p = subparsers.add_parser("init", help="Create .spendfuse/config.yaml")
    init_p.add_argument("--config", help="path to config file (default: .spendfuse/config.yaml)")
    init_p.add_argument("--force", action="store_true", help="overwrite an existing config file")
    init_p.set_defaults(func=cmd_init)

    watch_p = subparsers.add_parser("watch", help="Start the monitoring loop")
    watch_p.add_argument("--config", help="path to config file (default: .spendfuse/config.yaml)")
    watch_p.add_argument(
        "--max-iterations", type=int, default=None,
        help="stop after N polls (mainly for scripted testing; default: run forever)",
    )
    watch_p.set_defaults(func=cmd_watch)

    sim_p = subparsers.add_parser("simulate", help="Run a canned scenario against the simulated cost source")
    sim_p.add_argument("--scenario", required=True, choices=sorted(SCENARIOS), help="which scenario to run")
    sim_p.add_argument("--config", help="path to config file (default: .spendfuse/config.yaml)")
    sim_p.set_defaults(func=cmd_simulate)

    log_p = subparsers.add_parser("log", help="Show the history of checks and triggers")
    log_p.add_argument("--config", help="path to config file (default: .spendfuse/config.yaml)")
    log_p.add_argument("-n", "--limit", type=int, default=20, help="show the last N events (default: 20)")
    log_p.set_defaults(func=cmd_log)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

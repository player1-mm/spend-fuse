"""Loads and validates `.spendfuse/config.yaml`."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .engine import (
    DEFAULT_MAX_HISTORY_SAMPLES,
    DEFAULT_POLL_INTERVAL_SECONDS,
    Rule,
    clamp_max_history,
    clamp_poll_interval,
)

CONFIG_DIR_NAME = ".spendfuse"
CONFIG_FILE_NAME = "config.yaml"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    base_dir: Path
    cost_source_type: str
    cost_source_params: Dict[str, Any]
    poll_interval_seconds: float
    max_history_samples: int
    rules: List[Rule]
    actions: Dict[str, Dict[str, Any]]
    log_file: Path


def default_config_path(start_dir: Path = None) -> Path:
    start_dir = start_dir or Path.cwd()
    return start_dir / CONFIG_DIR_NAME / CONFIG_FILE_NAME


def _default_log_alert_command() -> str:
    # Environment-variable expansion syntax differs between shells ($VAR on
    # POSIX, %VAR% on cmd.exe), and worse: reason strings contain '>=',
    # which cmd.exe's %VAR% text substitution happily re-parses as an
    # output-redirection operator, silently swallowing the echo. Doing the
    # formatting inside a short Python one-liner (run with this same
    # interpreter) sidesteps both problems -- the reason text is read via
    # os.environ inside the child process and never handed to a shell
    # parser at all.
    script = "import os; print('[SpendFuse] FUSE TRIPPED:', os.environ.get('SPENDFUSE_REASON', ''))"
    return f'"{sys.executable}" -c "{script}"'


DEFAULT_CONFIG_TEMPLATE_TEMPLATE = """\
# Spend Fuse configuration.
# Full docs: see README.md in the project root.

# Where spend readings come from. "simulated" needs zero external
# dependencies or credentials and is the default so `spendfuse simulate`
# and `spendfuse watch` work out of the box. Switch to "aws" once you have
# AWS credentials configured (see README).
cost_source:
  type: simulated
  state_file: .spendfuse/simulated_state.json
  initial_usd: 0.0
  increment_usd: 0.0   # each simulated poll adds this many dollars; 0 = static until a scenario drives it
  # type: aws
  # profile: default          # optional named AWS profile
  # granularity: DAILY        # DAILY | HOURLY | MONTHLY
  # lookback_days: 7

# How often `spendfuse watch` polls the cost source, in seconds.
# Clamped to [1, 3600] regardless of what's set here, so the watch loop
# itself can never become a runaway process.
poll_interval_seconds: 5

# Bounds the in-memory sample history so a long-running `watch` can't leak
# memory. Old samples are dropped once this many are held.
max_history_samples: 500

# Threshold rules. Each rule fires the moment EITHER of its two conditions
# (absolute ceiling and/or rate ceiling) is first crossed, and re-arms once
# spend drops back below the threshold. At least one of the two conditions
# must be set; both may be set at once.
rules:
  - name: runaway_spend
    max_total_usd: 100.0               # absolute ceiling
    max_rate_usd_per_minute: 20.0      # rate ceiling ...
    window_minutes: 5                  # ... measured over this trailing window
    actions:
      - log_alert

# Action definitions. A rule's `actions:` list references keys here.
actions:
  log_alert:
    type: shell
    command: >-
      {log_alert_command}

  # Uncomment and point at a real endpoint to also notify a webhook:
  # notify_webhook:
  #   type: webhook
  #   url: "https://example.com/spendfuse-alert"
  #   method: POST

  # Uncomment to actually kill a runaway process by name when the fuse trips.
  # Use with care -- this really does terminate/kill whatever matches.
  # kill_offender:
  #   type: kill_process
  #   process_name: "runaway_script.py"
  #   match_cmdline: true   # match the name as a substring of the full command line too
"""


def default_config_text() -> str:
    return DEFAULT_CONFIG_TEMPLATE_TEMPLATE.format(log_alert_command=_default_log_alert_command())


def write_default_config(path: Path, force: bool = False) -> None:
    if path.exists() and not force:
        raise ConfigError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_text(), encoding="utf-8")


def _require(d: Dict, key: str, ctx: str) -> Any:
    if key not in d or d[key] is None:
        raise ConfigError(f"{ctx}: missing required field '{key}'")
    return d[key]


def _parse_rule(raw: Dict[str, Any]) -> Rule:
    name = _require(raw, "name", "rule")
    try:
        return Rule(
            name=name,
            actions=list(raw.get("actions") or []),
            max_total_usd=raw.get("max_total_usd"),
            max_rate_usd_per_minute=raw.get("max_rate_usd_per_minute"),
            window_minutes=raw.get("window_minutes"),
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def load_config(path) -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path} (run `spendfuse init` first)")

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top-level config must be a mapping")

    base_dir = path.parent

    cost_source = _require(raw, "cost_source", "config")
    if not isinstance(cost_source, dict):
        raise ConfigError("config.cost_source must be a mapping")
    cost_source_type = _require(cost_source, "type", "config.cost_source")
    cost_source_params = {k: v for k, v in cost_source.items() if k != "type"}

    poll_interval_raw = raw.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
    try:
        poll_interval_seconds = clamp_poll_interval(float(poll_interval_raw))
    except (TypeError, ValueError) as exc:
        raise ConfigError("config.poll_interval_seconds must be a number") from exc

    max_history_raw = raw.get("max_history_samples", DEFAULT_MAX_HISTORY_SAMPLES)
    try:
        max_history_samples = clamp_max_history(int(max_history_raw))
    except (TypeError, ValueError) as exc:
        raise ConfigError("config.max_history_samples must be an integer") from exc

    raw_rules = raw.get("rules") or []
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ConfigError("config.rules must be a non-empty list")
    rules = [_parse_rule(r) for r in raw_rules]

    names = [r.name for r in rules]
    if len(names) != len(set(names)):
        raise ConfigError("config.rules: rule names must be unique")

    raw_actions = raw.get("actions") or {}
    if not isinstance(raw_actions, dict) or not raw_actions:
        raise ConfigError("config.actions must be a non-empty mapping")
    for name, spec in raw_actions.items():
        if not isinstance(spec, dict) or "type" not in spec:
            raise ConfigError(f"config.actions.{name} must be a mapping with a 'type' field")

    for rule in rules:
        for action_name in rule.actions:
            if action_name not in raw_actions:
                raise ConfigError(
                    f"rule '{rule.name}' references undefined action '{action_name}'"
                )

    log_file = base_dir / "events.jsonl"

    return Config(
        base_dir=base_dir,
        cost_source_type=cost_source_type,
        cost_source_params=cost_source_params,
        poll_interval_seconds=poll_interval_seconds,
        max_history_samples=max_history_samples,
        rules=rules,
        actions=raw_actions,
        log_file=log_file,
    )

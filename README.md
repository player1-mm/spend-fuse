# Spend Fuse

A real-time circuit breaker for cloud spend. It watches a cost/usage signal
continuously and takes an actual protective action -- run a shell command,
call a webhook, kill a process -- the instant a threshold is crossed. Not
after the fact.

## The problem

Cloud billing disasters happen fast and silently. One team got a $34,000
bill in 8 days from a misconfigured Cloudflare Durable Objects loop, with no
real-time safeguard catching it before the damage was done. Budget alerts
from cloud providers are typically delayed (hours) and passive (just an
email) -- they don't actually stop anything.

Spend Fuse is different: it polls a cost source on an interval, tracks both
the absolute spend and the *rate* spend is changing (a runaway loop shows up
as an accelerating slope, not just a big number), and when a rule's
condition is crossed it fires real, configured actions immediately and logs
exactly what happened, when, and why.

## What works out of the box vs. what needs real cloud credentials

| Component | Needs credentials? | Notes |
|---|---|---|
| Core engine (threshold + rate-of-change logic) | No | Pure Python, provider-agnostic |
| **Simulated cost source** (`cost_source.type: simulated`) | No | Backs a running total with a local JSON file; the default, and what `spendfuse simulate` and the quickstart below use |
| **AWS Cost Explorer source** (`cost_source.type: aws`) | **Yes** -- AWS credentials + Cost Explorer enabled | Real, working `boto3` adapter (see `spendfuse/sources/aws_cost_explorer.py`) -- not a stub -- but you need a real AWS account to actually run it. `boto3` is an optional dependency (`pip install -e ".[aws]"`); the rest of the tool works without it installed at all. Note Cost Explorer data itself lags by hours, so pair it with a faster proxy signal if you need true real-time coverage. |
| `run shell command` action | No | Runs from your local config |
| `call a webhook` action | No (until you point it at a real URL) | Uses `requests` |
| `kill a process` action | No | Uses `psutil`, scoped to PID / exact process name you configure |

Everything in the quickstart below runs with zero external accounts,
credentials, or network access.

## Install

```bash
pip install -e .
# or, to also pull in the optional AWS adapter's dependency:
pip install -e ".[aws]"
```

This installs the `spendfuse` command (see `pyproject.toml` /
`[project.scripts]`).

## Quickstart

```bash
# 1. Create .spendfuse/config.yaml with a default simulated cost source,
#    a rule, and a shell action.
spendfuse init

# 2. Run the "runaway loop" demo scenario -- spend ramps up with
#    accelerating increments, like a misbehaving retry loop -- and watch
#    the fuse actually trip.
spendfuse simulate --scenario runaway_loop

# 3. Run the "normal" scenario -- steady, modest spend -- and confirm
#    nothing trips.
spendfuse simulate --scenario normal

# 4. See the history of every check and every trigger.
spendfuse log
```

Sample `runaway_loop` output (abridged):

```
--- spendfuse simulate --scenario runaway_loop ---
[t=+   15s] spend=$    2.70  rate=   n/a
[t=+   30s] spend=$    6.35  rate= 14.60/min
[t=+   45s] spend=$   11.27  rate= 17.14/min
[t=+   60s] spend=$   17.91  rate= 20.22/min
  !! FUSE TRIPPED: rule 'runaway_spend' -- spend accelerating: $20.22/min >= $20.00/min over 5 min window
       -> action 'log_alert' (shell): OK - exit 0: [SpendFuse] FUSE TRIPPED: spend accelerating: $20.22/min >= $20.00/min over 5 min window
[t=+   75s] spend=$   26.88  rate= 23.97/min
...
[t=+  360s] spend=$10351.01  rate=1487.83/min
--- scenario 'runaway_loop' complete: 1 trigger(s) fired ---
```

## Continuous monitoring

```bash
spendfuse watch
```

Polls the configured cost source every `poll_interval_seconds` (clamped to
1-3600s so the watcher itself can never become a runaway process), tracks a
bounded rolling history, and fires configured actions the instant a rule's
condition is met. Stop it with Ctrl+C.

## Configuration

`spendfuse init` writes `.spendfuse/config.yaml` with inline comments. The
shape:

```yaml
cost_source:
  type: simulated          # or: aws
  state_file: .spendfuse/simulated_state.json
  initial_usd: 0.0
  increment_usd: 0.0

poll_interval_seconds: 5   # clamped to [1, 3600]
max_history_samples: 500   # bounds memory over a long-running watch

rules:
  - name: runaway_spend
    max_total_usd: 100.0             # absolute ceiling (optional)
    max_rate_usd_per_minute: 20.0    # rate ceiling (optional) ...
    window_minutes: 5                # ... over this trailing window
    actions: [log_alert]             # at least one of the above two must be set

actions:
  log_alert:
    type: shell
    command: "echo [SpendFuse] FUSE TRIPPED: $SPENDFUSE_REASON"

  # notify_webhook:
  #   type: webhook
  #   url: "https://example.com/spendfuse-alert"

  # kill_offender:
  #   type: kill_process
  #   process_name: "runaway_script.py"
```

A rule fires the moment *either* of its two conditions (absolute ceiling
and/or rate ceiling) is first crossed, and re-arms once spend drops back
below threshold -- it won't re-fire every poll while a breach persists.

The rate ceiling is a least-squares linear regression slope over the
samples inside the trailing window, not a naive two-point delta, so a
single noisy poll can't spuriously trip -- or mask -- an accelerating trend.

### Actions

- **`shell`** -- runs `command` via the shell (config is trusted, same
  model as a crontab entry). Trigger context is exposed as
  `SPENDFUSE_RULE_NAME`, `SPENDFUSE_REASON`, `SPENDFUSE_TOTAL_USD`,
  `SPENDFUSE_RATE_USD_PER_MINUTE` environment variables.
- **`webhook`** -- POSTs a JSON payload (`rule_name`, `reason`, `total_usd`,
  `rate_usd_per_minute`, `timestamp`) to `url`.
- **`kill_process`** -- terminates (then, if it doesn't exit within
  `grace_period_seconds`, force-kills) processes matching `pid` or an exact
  `process_name` (optionally widened to a cmdline substring match via
  `match_cmdline: true`). Never matches spendfuse's own process. Every
  match and outcome is logged.

## Adding another cost source

Implement `spendfuse.sources.base.CostSource` (one method:
`get_current_spend() -> CostSample`) and register it in
`build_cost_source()` in `spendfuse/sources/__init__.py`. Nothing in the
engine, CLI, or actions needs to change.

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Covers the threshold/rate math (including the regression-based rate
calculation and window filtering), the simulated cost source, config
loading/validation, and each action type actually firing -- the
`kill_process` test spawns its own throwaway subprocess to kill (never
touching anything else on the machine), and the `webhook` test posts to a
local mock HTTP server rather than the network.

## Scope

This is v1: no CI config, no Docker, no GCP/Azure adapters (though the
interface is designed so adding one is a single new file). See "Adding
another cost source" above.

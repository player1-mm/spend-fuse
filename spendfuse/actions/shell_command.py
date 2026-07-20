from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

from .base import Action, ActionResult

DEFAULT_TIMEOUT_SECONDS = 30


class ShellCommandAction(Action):
    """Runs a shell command from the (user-authored, trusted) config file.

    The command string comes from the local config the user wrote
    themselves -- the same trust model as a crontab entry -- so it is run
    via the shell to allow pipes/redirects. Trigger context is exposed to
    the command as SPENDFUSE_* environment variables.
    """

    def execute(self, context: Dict[str, Any]) -> ActionResult:
        command = self.params.get("command")
        if not command:
            return ActionResult(self.name, "shell", False, "no 'command' configured")

        timeout = float(self.params.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        env = os.environ.copy()
        env["SPENDFUSE_RULE_NAME"] = str(context.get("rule_name", ""))
        env["SPENDFUSE_REASON"] = str(context.get("reason", ""))
        env["SPENDFUSE_TOTAL_USD"] = str(context.get("total_usd", ""))
        env["SPENDFUSE_RATE_USD_PER_MINUTE"] = str(context.get("rate_usd_per_minute", ""))

        try:
            result = subprocess.run(
                command,
                shell=True,
                env=env,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            return ActionResult(self.name, "shell", False, f"command timed out after {timeout}s")
        except OSError as exc:
            return ActionResult(self.name, "shell", False, f"failed to run command: {exc}")

        output = (result.stdout or "").strip()
        if result.returncode == 0:
            detail = f"exit 0" + (f": {output}" if output else "")
            return ActionResult(self.name, "shell", True, detail)

        stderr = (result.stderr or "").strip()
        detail = f"exit {result.returncode}" + (f": {stderr or output}" if (stderr or output) else "")
        return ActionResult(self.name, "shell", False, detail)

"""Kill a process by PID or by name -- the genuinely destructive action.

Scoped deliberately narrowly:
  * Matches ONLY what the config explicitly names: an exact PID, or an
    exact process-name match (optionally widened to a cmdline substring
    match via `match_cmdline: true`, which the user must opt into).
  * Never matches spendfuse's own process.
  * Always tries a graceful terminate() first, waits `grace_period_seconds`,
    and only escalates to kill() for stragglers.
  * Every match found and every outcome (terminated / killed / failed /
    not found) is captured in the returned ActionResult detail string so
    it lands in the event log verbatim -- there is no silent kill.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import psutil

from .base import Action, ActionResult

DEFAULT_GRACE_PERIOD_SECONDS = 3.0


def _describe(proc: "psutil.Process") -> str:
    try:
        cmdline = " ".join(proc.cmdline())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        cmdline = "<unavailable>"
    try:
        name = proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        name = "<unavailable>"
    return f"pid={proc.pid} name={name!r} cmdline={cmdline!r}"


class KillProcessAction(Action):
    def _find_candidates(self) -> List["psutil.Process"]:
        own_pid = os.getpid()
        pid = self.params.get("pid")
        if pid is not None:
            try:
                proc = psutil.Process(int(pid))
            except psutil.NoSuchProcess:
                return []
            if proc.pid == own_pid:
                return []
            return [proc]

        process_name = self.params.get("process_name")
        if not process_name:
            return []
        match_cmdline = bool(self.params.get("match_cmdline", False))

        candidates = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            if proc.pid == own_pid:
                continue
            info = proc.info
            name_match = info.get("name") == process_name
            cmdline_match = match_cmdline and process_name in " ".join(info.get("cmdline") or [])
            if name_match or cmdline_match:
                candidates.append(proc)

        if not self.params.get("kill_all_matches", True) and candidates:
            candidates = sorted(candidates, key=lambda p: p.pid)[:1]
        return candidates

    def execute(self, context: Dict[str, Any]) -> ActionResult:
        if not self.params.get("pid") and not self.params.get("process_name"):
            return ActionResult(self.name, "kill_process", False, "no 'pid' or 'process_name' configured")

        candidates = self._find_candidates()
        if not candidates:
            target = self.params.get("pid") or self.params.get("process_name")
            return ActionResult(self.name, "kill_process", False, f"no matching process found for '{target}'")

        grace_period = float(self.params.get("grace_period_seconds", DEFAULT_GRACE_PERIOD_SECONDS))
        outcomes = []
        for proc in candidates:
            desc = _describe(proc)
            try:
                proc.terminate()
                proc.wait(timeout=grace_period)
                outcomes.append(f"terminated [{desc}]")
            except psutil.TimeoutExpired:
                try:
                    proc.kill()
                    outcomes.append(f"force-killed [{desc}]")
                except psutil.NoSuchProcess:
                    outcomes.append(f"terminated [{desc}]")
                except psutil.AccessDenied:
                    outcomes.append(f"FAILED (access denied on kill) [{desc}]")
            except psutil.NoSuchProcess:
                outcomes.append(f"already gone [{desc}]")
            except psutil.AccessDenied:
                outcomes.append(f"FAILED (access denied on terminate) [{desc}]")

        success = all("FAILED" not in o for o in outcomes)
        return ActionResult(self.name, "kill_process", success, "; ".join(outcomes))

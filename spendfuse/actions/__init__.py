"""Action registry: each entry is what a rule's `actions:` list can name."""
from __future__ import annotations

from typing import Any, Dict

from .base import Action, ActionResult
from .kill_process import KillProcessAction
from .shell_command import ShellCommandAction
from .webhook import WebhookAction

__all__ = ["Action", "ActionResult", "build_actions"]

_ACTION_TYPES = {
    "shell": ShellCommandAction,
    "webhook": WebhookAction,
    "kill_process": KillProcessAction,
}


def build_actions(actions_config: Dict[str, Dict[str, Any]]) -> Dict[str, Action]:
    actions: Dict[str, Action] = {}
    for name, spec in actions_config.items():
        spec = dict(spec)
        action_type = spec.pop("type", None)
        cls = _ACTION_TYPES.get(action_type)
        if cls is None:
            raise ValueError(
                f"action '{name}' has unknown type '{action_type}' "
                f"(expected one of: {', '.join(sorted(_ACTION_TYPES))})"
            )
        actions[name] = cls(name, spec)
    return actions

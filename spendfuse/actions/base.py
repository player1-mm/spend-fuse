from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class ActionResult:
    action_name: str
    action_type: str
    success: bool
    detail: str


class Action(ABC):
    """A protective action a rule can trigger.

    `context` passed to `execute()` describes why the fuse tripped:
    rule_name, reason, total_usd, rate_usd_per_minute, timestamp.
    """

    def __init__(self, name: str, params: Dict[str, Any]):
        self.name = name
        self.params = params

    @abstractmethod
    def execute(self, context: Dict[str, Any]) -> ActionResult:
        raise NotImplementedError

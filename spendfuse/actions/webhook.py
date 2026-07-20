from __future__ import annotations

from typing import Any, Dict

import requests

from .base import Action, ActionResult

DEFAULT_TIMEOUT_SECONDS = 10


class WebhookAction(Action):
    """POSTs (or otherwise sends) a JSON payload describing the trigger to a URL."""

    def execute(self, context: Dict[str, Any]) -> ActionResult:
        url = self.params.get("url")
        if not url:
            return ActionResult(self.name, "webhook", False, "no 'url' configured")

        method = str(self.params.get("method", "POST")).upper()
        timeout = float(self.params.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        payload = {
            "rule_name": context.get("rule_name"),
            "reason": context.get("reason"),
            "total_usd": context.get("total_usd"),
            "rate_usd_per_minute": context.get("rate_usd_per_minute"),
            "timestamp": context.get("timestamp"),
        }

        try:
            response = requests.request(method, url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            return ActionResult(self.name, "webhook", False, f"request failed: {exc}")

        success = 200 <= response.status_code < 300
        detail = f"{method} {url} -> HTTP {response.status_code}"
        return ActionResult(self.name, "webhook", success, detail)

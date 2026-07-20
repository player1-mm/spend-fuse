"""Real AWS Cost Explorer-backed cost source.

This is a genuine, working adapter -- not a stub -- but it needs real AWS
credentials (via the standard boto3 credential chain: environment
variables, `~/.aws/credentials`, an assumed role, SSO, etc.) and Cost
Explorer enabled on the account to actually run. `boto3` is an optional
dependency (`pip install -e ".[aws]"`) and is only imported when this
source is actually instantiated, so the rest of spendfuse works with zero
AWS setup.

Important caveat: Cost Explorer data is not real-time. AWS typically
updates it within a few hours, with some line items taking up to ~24h to
finalize. That lag is exactly the kind of blind spot spendfuse's
rate-based rule is meant to catch *before* the damage fully lands in your
bill -- for a genuinely real-time signal, pair this with a faster proxy
(a CloudWatch billing alarm poll, a usage counter from your own service,
etc.) via a custom CostSource.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .base import CostSample, CostSource


class AWSCostExplorerSource(CostSource):
    def __init__(
        self,
        profile: Optional[str] = None,
        granularity: str = "DAILY",
        lookback_days: int = 7,
    ):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                "the 'aws' cost source requires boto3. Install it with: "
                "pip install -e '.[aws]'"
            ) from exc

        if granularity not in ("DAILY", "HOURLY", "MONTHLY"):
            raise ValueError("granularity must be one of DAILY, HOURLY, MONTHLY")

        self.granularity = granularity
        self.lookback_days = lookback_days
        session = boto3.Session(profile_name=profile) if profile else boto3.Session()
        # Cost Explorer's API endpoint only exists in us-east-1, regardless
        # of which region the billed resources actually run in.
        self._client = session.client("ce", region_name="us-east-1")

    def get_current_spend(self) -> CostSample:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=self.lookback_days)
        response = self._client.get_cost_and_usage(
            TimePeriod={
                "Start": start.isoformat(),
                "End": (end + timedelta(days=1)).isoformat(),
            },
            Granularity=self.granularity,
            Metrics=["UnblendedCost"],
        )
        total = 0.0
        for period in response.get("ResultsByTime", []):
            amount = period.get("Total", {}).get("UnblendedCost", {}).get("Amount", "0")
            total += float(amount)
        return CostSample(timestamp=time.time(), total_usd=total)

"""Append-only JSONL event log backing `spendfuse log`."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


class EventLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: Dict) -> None:
        record = dict(event)
        record.setdefault("ts", time.time())
        record.setdefault("ts_iso", datetime.fromtimestamp(record["ts"], tz=timezone.utc).isoformat())
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def read_all(self) -> List[Dict]:
        if not self.path.exists():
            return []
        events = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def read_recent(self, limit: Optional[int] = None) -> List[Dict]:
        events = self.read_all()
        if limit is None:
            return events
        return events[-limit:]

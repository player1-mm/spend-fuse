import http.server
import json
import os
import subprocess
import sys
import threading

import psutil
import pytest

from spendfuse.actions.kill_process import KillProcessAction
from spendfuse.actions.shell_command import ShellCommandAction
from spendfuse.actions.webhook import WebhookAction

EMPTY_CONTEXT = {
    "rule_name": None,
    "reason": None,
    "total_usd": None,
    "rate_usd_per_minute": None,
    "timestamp": None,
}


# ---- shell action -----------------------------------------------------

def test_shell_action_success():
    action = ShellCommandAction("a", {"command": f'"{sys.executable}" -c "print(1)"'})
    result = action.execute(EMPTY_CONTEXT)
    assert result.success
    assert "1" in result.detail


def test_shell_action_nonzero_exit_is_failure():
    action = ShellCommandAction("a", {"command": f'"{sys.executable}" -c "import sys; sys.exit(3)"'})
    result = action.execute(EMPTY_CONTEXT)
    assert not result.success


def test_shell_action_missing_command():
    action = ShellCommandAction("a", {})
    result = action.execute(EMPTY_CONTEXT)
    assert not result.success


def test_shell_action_exposes_trigger_context_as_env_vars():
    script = "import os; print(os.environ['SPENDFUSE_REASON'])"
    action = ShellCommandAction("a", {"command": f'"{sys.executable}" -c "{script}"'})
    context = dict(EMPTY_CONTEXT, reason="rate too high")
    result = action.execute(context)
    assert result.success
    assert "rate too high" in result.detail


# ---- webhook action -- always against a local mock server, never the network ----

class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        _RecordingHandler.received.append(json.loads(body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):  # silence default request logging
        pass


@pytest.fixture
def local_mock_server():
    _RecordingHandler.received = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _RecordingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_webhook_action_posts_to_local_mock_server(local_mock_server):
    port = local_mock_server.server_address[1]
    action = WebhookAction("wh", {"url": f"http://127.0.0.1:{port}/"})
    context = dict(EMPTY_CONTEXT, rule_name="runaway_spend", reason="test", total_usd=50.0, rate_usd_per_minute=10.0)

    result = action.execute(context)

    assert result.success
    assert "200" in result.detail
    assert len(_RecordingHandler.received) == 1
    assert _RecordingHandler.received[0]["rule_name"] == "runaway_spend"


def test_webhook_action_missing_url():
    action = WebhookAction("wh", {})
    result = action.execute(EMPTY_CONTEXT)
    assert not result.success


def test_webhook_action_connection_failure_is_reported_not_raised():
    # port 1 is a privileged port nothing will be listening on locally
    action = WebhookAction("wh", {"url": "http://127.0.0.1:1/", "timeout_seconds": 1})
    result = action.execute(EMPTY_CONTEXT)
    assert not result.success
    assert "request failed" in result.detail


# ---- kill_process action -- only ever targets a throwaway process the test itself spawns ----

@pytest.fixture
def dummy_process():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_kill_process_terminates_dummy_process_by_pid(dummy_process):
    assert psutil.pid_exists(dummy_process.pid)

    action = KillProcessAction("k", {"pid": dummy_process.pid, "grace_period_seconds": 3})
    result = action.execute(EMPTY_CONTEXT)

    assert result.success
    dummy_process.wait(timeout=5)
    assert dummy_process.poll() is not None


def test_kill_process_refuses_to_target_its_own_pid():
    action = KillProcessAction("k", {"pid": os.getpid()})
    result = action.execute(EMPTY_CONTEXT)
    assert not result.success


def test_kill_process_no_match_is_reported_not_raised():
    action = KillProcessAction("k", {"process_name": "definitely_not_a_real_process_xyz123"})
    result = action.execute(EMPTY_CONTEXT)
    assert not result.success
    assert "no matching process" in result.detail


def test_kill_process_missing_target():
    action = KillProcessAction("k", {})
    result = action.execute(EMPTY_CONTEXT)
    assert not result.success

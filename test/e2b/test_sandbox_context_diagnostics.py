"""Cluster-free tests for SandboxContext failure diagnostics.

These files are collected with the rest of test/e2b/, so they must finish in
seconds, never call kubectl, and not depend on QUOTA_E2E_PROFILE.
"""
import re
import shlex
from types import SimpleNamespace

import pytest

from conftest_base import SandboxContext, pytest_runtest_makereport


class FakeSandbox:
    def __init__(self, sandbox_id, metadata=None):
        self.sandbox_id = sandbox_id
        self.metadata = metadata


@pytest.fixture(autouse=True)
def wait_for_sandbox():
    """Override the plugin autouse fixture that waits on the cluster warm pool."""
    yield


@pytest.fixture(autouse=True)
def _forbid_cluster_subprocess(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"unexpected subprocess.run in cluster-free test: {args!r}")

    monkeypatch.setattr("subprocess.run", forbidden)
    monkeypatch.setattr("conftest_base.subprocess.run", forbidden)
    monkeypatch.setattr("utils.subprocess.run", forbidden)


def _drive_failed_call_report(item):
    class Outcome:
        def get_result(self):
            return SimpleNamespace(when="call", failed=True)

    gen = pytest_runtest_makereport(item, call=object())
    next(gen)
    with pytest.raises(StopIteration):
        gen.send(Outcome())


def _record_kubectl(ctx, monkeypatch):
    kubectl_args = []
    shell_cmds = []
    monkeypatch.setattr(
        ctx, "_run_kubectl", lambda args, timeout=30: kubectl_args.append(list(args)) or "ok"
    )
    monkeypatch.setattr(
        ctx, "_run_kubectl_shell", lambda cmd, timeout=30: shell_cmds.append(cmd) or "ok"
    )
    monkeypatch.setattr(
        "conftest_base.resolve_sandbox_cr",
        lambda sandbox_id, metadata=None: ("default", f"pod-{sandbox_id}"),
    )
    return kubectl_args, shell_cmds


def test_hook_dumps_when_sandbox_context_exists_without_sandboxes(monkeypatch):
    ctx = SandboxContext()
    dumped = []
    monkeypatch.setattr(ctx, "_collect_diagnostics", lambda: dumped.append("dumped"))

    class Item:
        funcargs = {"sandbox_context": ctx}

    _drive_failed_call_report(Item())
    assert dumped == ["dumped"]


def test_hook_skips_dump_without_sandbox_context(monkeypatch):
    dumped = []
    monkeypatch.setattr(
        SandboxContext, "_collect_diagnostics", lambda self: dumped.append("dumped")
    )

    class Item:
        funcargs = {}

    _drive_failed_call_report(Item())
    assert dumped == []


def test_collect_diagnostics_without_sandboxes_still_dumps_component_logs(monkeypatch):
    ctx = SandboxContext()
    ctx.request_id = "req-empty"
    kubectl_args, shell_cmds = _record_kubectl(ctx, monkeypatch)

    ctx._collect_diagnostics()

    assert kubectl_args == []
    manager = [cmd for cmd in shell_cmds if "component=sandbox-manager" in cmd]
    controller = [cmd for cmd in shell_cmds if "control-plane=sandbox-controller-manager" in cmd]
    assert len(manager) == 1
    assert len(controller) == 1
    quoted = shlex.quote(ctx._log_grep_pattern())
    assert quoted in manager[0]
    assert quoted in controller[0]
    assert ctx._log_grep_needles() == ["req-empty"]


def test_log_grep_needles_are_deduplicated():
    ctx = SandboxContext()
    ctx.request_id = "req-1"
    ctx.add_log_grep("req-1", "anti-drift", "anti-drift", "key-1")
    ctx.add(FakeSandbox("sbx-1"))
    ctx.add(FakeSandbox("req-1"))
    ctx.add(FakeSandbox("sbx-1"))
    ctx.add_log_grep("sbx-1")
    assert ctx._log_grep_needles() == ["req-1", "anti-drift", "key-1", "sbx-1"]


def test_empty_log_grep_needles_are_ignored():
    ctx = SandboxContext()
    ctx.request_id = "req-1"
    ctx.add_log_grep("", None, "kept", "")
    ctx.add(FakeSandbox(""))
    ctx.add(FakeSandbox(None))
    assert ctx._log_grep_needles() == ["req-1", "kept"]


def test_component_logs_dumped_once_per_failure_with_multiple_sandboxes(monkeypatch):
    ctx = SandboxContext()
    ctx.request_id = "req-1"
    ctx.add(FakeSandbox("sbx-a"))
    ctx.add(FakeSandbox("sbx-b"))
    _, shell_cmds = _record_kubectl(ctx, monkeypatch)

    ctx._collect_diagnostics()

    manager = [cmd for cmd in shell_cmds if "component=sandbox-manager" in cmd]
    controller = [cmd for cmd in shell_cmds if "control-plane=sandbox-controller-manager" in cmd]
    assert len(manager) == 1
    assert len(controller) == 1
    quoted = shlex.quote(ctx._log_grep_pattern())
    assert quoted in manager[0]
    assert quoted in controller[0]
    assert ctx._log_grep_needles() == ["req-1", "sbx-a", "sbx-b"]


def test_log_grep_matches_special_characters_literally(monkeypatch):
    ctx = SandboxContext()
    ctx.request_id = "req-1"
    ctx.add_log_grep("foo.bar", "a|b", "x(y)")
    pattern = ctx._log_grep_pattern()
    compiled = re.compile(pattern)
    assert compiled.search("foo.bar")
    assert compiled.search("a|b")
    assert compiled.search("x(y)")
    assert compiled.search("fooXbar") is None
    assert compiled.search("ab") is None
    assert compiled.search("xy") is None

    _, shell_cmds = _record_kubectl(ctx, monkeypatch)
    ctx._collect_diagnostics()
    quoted = shlex.quote(pattern)
    manager = [cmd for cmd in shell_cmds if "component=sandbox-manager" in cmd]
    assert manager
    assert quoted in manager[0]
    assert "| grep -E " in manager[0]

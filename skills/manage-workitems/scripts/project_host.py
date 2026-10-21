"""Explicit host selection without changing persisted project state."""

from contextvars import ContextVar
import os
from pathlib import Path
import shlex
import sys

_HOST = ContextVar("project_host", default=None)


def select(host):
    return _HOST.set(host)


def reset(token):
    _HOST.reset(token)


def current_session():
    host = _HOST.get()
    if host is None:
        return os.environ.get("CODEX_THREAD_ID") or os.environ.get("PROJECT_SESSION_ID")
    directory = str(Path(__file__).resolve().parents[3] / "scripts")
    if directory not in sys.path:
        sys.path.insert(0, directory)
    from host_agents_common import adapter
    return adapter(host).session()


def session_error():
    if _HOST.get() == "qoder":
        return "PROJECT_SESSION_ID is required for Qoder workflow identity"
    return "CODEX_THREAD_ID or PROJECT_SESSION_ID is required for workflow identity"


def bind_commands(result, host):
    if host != "qoder":
        return result
    entry = Path(__file__).with_name("project.py").resolve()
    if isinstance(result, dict):
        bound = {}
        for key, value in result.items():
            if key.endswith("_command") and isinstance(value, str):
                arguments = shlex.split(value)
                if len(arguments) > 1 and Path(arguments[1]).resolve() == entry:
                    value = shlex.join(arguments[:2] + ["--host", host] + arguments[2:])
            else:
                value = bind_commands(value, host)
            bound[key] = value
        return bound
    if isinstance(result, list):
        return [bind_commands(value, host) for value in result]
    return result

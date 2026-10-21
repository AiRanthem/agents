"""Opaque execution identity and caller-provided continuation entrypoints."""

from contextvars import ContextVar
import os
from pathlib import Path
import shlex

UNSET = object()
_SESSION = ContextVar("project_session", default=UNSET)


def select(session):
    return _SESSION.set(session)


def reset(token):
    _SESSION.reset(token)


def current_session():
    session = _SESSION.get()
    return os.environ.get("PROJECT_SESSION_ID") if session is UNSET else session


def session_error():
    return "A stable execution session is required; supply PROJECT_SESSION_ID or an explicit caller identity"


def bind_commands(result, command_prefix):
    if command_prefix is None:
        return result
    entry = Path(__file__).with_name("project.py").resolve()
    if isinstance(result, dict):
        bound = {}
        for key, value in result.items():
            if key.endswith("_command") and isinstance(value, str):
                arguments = shlex.split(value)
                if len(arguments) > 1 and Path(arguments[1]).resolve() == entry:
                    value = shlex.join([*command_prefix, *arguments[2:]])
            else:
                value = bind_commands(value, command_prefix)
            bound[key] = value
        return bound
    if isinstance(result, list):
        return [bind_commands(value, command_prefix) for value in result]
    return result

#!/usr/bin/env python3
"""Codex project entrypoint; keep native identity in this directory."""

import importlib.util
import os
from pathlib import Path
import sys

DIRECTORY = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("_project_codex_host", DIRECTORY / "host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
sys.path.insert(0, str(DIRECTORY.parent / "skills/manage-workitems/scripts"))
import project as core


def main(argv=None):
    session = host.session()
    command = [sys.executable, str(Path(__file__).resolve())]
    if session is not None:
        if os.environ.get("CODEX_THREAD_ID"):
            command = ["env", "CODEX_THREAD_ID=" + session, *command]
        else:
            command = ["env", "-u", "CODEX_THREAD_ID", "PROJECT_SESSION_ID=" + session, *command]
    return core.main(argv, session=session, command_prefix=command)


if __name__ == "__main__":
    raise SystemExit(main())

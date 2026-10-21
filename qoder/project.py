#!/usr/bin/env python3
"""Qoder project entrypoint; keep native identity in this directory."""

import importlib.util
from pathlib import Path
import sys

DIRECTORY = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("_project_qoder_host", DIRECTORY / "host.py")
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
sys.path.insert(0, str(DIRECTORY.parent / "skills/manage-workitems/scripts"))
import project as core


def main(argv=None):
    session = host.session()
    command = [sys.executable, str(Path(__file__).resolve())]
    if session is not None:
        command = ["env", "PROJECT_SESSION_ID=" + session, *command]
    return core.main(argv, session=session, command_prefix=command)


if __name__ == "__main__":
    raise SystemExit(main())

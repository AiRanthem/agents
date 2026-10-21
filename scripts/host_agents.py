#!/usr/bin/env python3
"""Check project-stage agents or print native role definitions."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from host_agents_common import ROOT, ROLES, SKILLS, adapter, check, main, role_config


if __name__ == "__main__":
    raise SystemExit(main())

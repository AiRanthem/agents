#!/usr/bin/env python3
"""Load scoped delegation guidance for Astra subagents."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delegation import run_hook


if __name__ == "__main__":
    sys.exit(run_hook("SubagentStart"))

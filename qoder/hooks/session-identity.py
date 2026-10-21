#!/usr/bin/env python3
"""Expose the stable Qoder session identity to the main agent at SessionStart boundaries."""

import json
from pathlib import Path
import sys


def main():
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError):
        return 1
    if not isinstance(event, dict):
        return 1
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        return 1
    context = (
        f"Qoder session identity: session_id={session_id}. This value is stable across every "
        "turn of this session, including resume and compaction. When a project runtime command "
        "requires a session identity, export PROJECT_SESSION_ID with exactly this value in the "
        "same command and use the dev-kit qoder/project.py entrypoint. This entrypoint reads "
        "only PROJECT_SESSION_ID. Do not use a per-turn "
        "value, a worker ID, or a random value instead. "
        f"For an authorized dev-kit installation request, read {Path(__file__).resolve().parents[1] / 'INSTALL.md'} "
        "and supply that contract alongside the shared installation contract. "
        "Active native Plan maps to the shared read-only planning contract; Agent maps to ordinary "
        "execution subject to actual permissions."
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Load the main-agent delegation policy for Codex SessionStart hooks."""

import json
from pathlib import Path
import sys


def main():
    event = json.load(sys.stdin)
    if event["hook_event_name"] != "SessionStart":
        return

    # Codex 0.159.2 routes spawned children to SubagentStart, not SessionStart.
    # known-limit: history forks retain hook context; delegation uses fork_turns=none.
    # Recheck core/src/hook_runtime.rs and agent/control/spawn.rs on Codex upgrades.
    policy = (Path(__file__).resolve().parents[1] / "prompts/delegation.md").read_text(
        encoding="utf-8"
    )
    if not policy.strip():
        raise ValueError("The delegation policy is empty")
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": policy,
        }
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Unable to load the Codex delegation policy: {error}", file=sys.stderr)
        sys.exit(1)

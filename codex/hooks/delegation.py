"""Assemble the applicable delegation fragments from the repository."""

import json
from pathlib import Path
import sys


SHARED = ("delegation-task.md", "delegation-evidence.md", "delegation-lifecycle.md")


def prompt_names(event, expected):
    if event["hook_event_name"] != expected:
        return ()
    model = event.get("model")
    families = (set(model.split("-")) & {"astra", "sol", "luna"}
                if isinstance(model, str) and model.startswith("gpt-") else set())
    family = next(iter(families)) if len(families) == 1 else None
    if expected == "SubagentStart":
        return ("delegation-subagent.md", *SHARED, "delegation-astra.md") if family == "astra" else ()
    if family == "luna":
        return ()
    names = ("delegation.md", *SHARED)
    return (*names, f"delegation-{family}.md") if family in {"astra", "sol"} else names


def run_hook(expected):
    try:
        names = prompt_names(json.load(sys.stdin), expected)
        if not names:
            return 0
        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        parts = []
        for name in names:
            content = (prompt_dir / name).read_text(encoding="utf-8")
            if not content.strip():
                raise ValueError(f"The delegation prompt is empty: {name}")
            parts.append(content.strip())
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": expected, "additionalContext": "\n\n".join(parts) + "\n",
        }}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Unable to load the Codex delegation policy: {error}", file=sys.stderr)
        return 1

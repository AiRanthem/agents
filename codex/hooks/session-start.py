#!/usr/bin/env python3
"""Load main-agent delegation at Codex session boundaries."""

import json
from pathlib import Path
import sys


def main():
    try:
        event = json.load(sys.stdin)
        if event["hook_event_name"] != "SessionStart":
            return 0

        model = event.get("model")
        families = set()
        if isinstance(model, str) and model.startswith("gpt-"):
            families = set(model.split("-")) & {"astra", "sol", "luna"}
        family = next(iter(families)) if len(families) == 1 else None
        if family == "luna":
            return 0

        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        entry = "delegation.md"
        content = (prompt_dir / entry).read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"The delegation prompt is empty: {entry}")

        references = ["delegation-task.md", "delegation-evidence.md", "delegation-lifecycle.md"]
        if family in {"astra", "sol"}:
            references.append("delegation-routing.md")
        index = "\n".join(f"- {prompt_dir / name}" for name in references)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart", "additionalContext": f"{content}\n\n{index}\n",
        }}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Unable to load the Codex delegation policy: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

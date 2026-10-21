#!/usr/bin/env python3
"""Qoder project-stage configuration and session identity."""

import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import host_agents_common as common


def role_config(name):
    source = common.ROOT / "qoder" / "agents" / f"{name}.md"
    content = source.read_text()
    config = common.markdown_config(content)
    common.validate_role(source, name, config)
    if re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", config["model"]) is None:
        raise ValueError(f"{source}: expected model format [display name](model ID)")
    if not config.get("effort"):
        raise ValueError(f"{source}: missing effort")
    if type(config.get("maxTurns")) is not int or config["maxTurns"] <= 0:
        raise ValueError(f"{source}: maxTurns must be a positive integer")
    return source, content, config


def injected_role(name):
    _, _, config = role_config(name)
    model = config["model"].split("](", 1)[1].removesuffix(")")
    return {name: {"description": config["description"], "prompt": config["developer_instructions"],
                   "model": model, "effort": config["effort"],
                   "maxTurns": config["maxTurns"]}}


def _settings_gaps(home):
    path = home / ".qoder" / "settings.json"
    try:
        settings = json.loads(path.read_text())
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        groups = settings.get("hooks", {}).get("SessionStart", [])
        overrides = settings.get("agents", {}).get("overrides", {})
        if not isinstance(groups, list) or not isinstance(overrides, dict):
            raise ValueError("invalid SessionStart or agents.overrides")
        handlers = [hook for group in groups for hook in group.get("hooks", [])
                    if "session-identity.py" in hook.get("command", "")]
        expected = {"type": "command", "command": "python3 ~/.qoder/hooks/session-identity.py", "timeout": 10}
        gaps = []
        if not any(all(hook.get(key) == value for key, value in expected.items())
                   and not group.get("matcher") and not group.get("async")
                   and not hook.get("async")
                   for group in groups for hook in group.get("hooks", [])):
            gaps.append(f"missing current SessionStart identity handler: {path}")
        if len(handlers) != 1:
            gaps.append(f"expected exactly one SessionStart identity handler: {path}")
        for name in common.ROLES:
            _, _, config = role_config(name)
            override = overrides.get(name, {})
            if not isinstance(override, dict):
                raise ValueError(f"invalid agents.overrides.{name}")
            if override.get("enabled") is False:
                gaps.append(f"native Qoder agent disabled by override: {name}")
            model = override.get("modelConfig", {}).get("model", config["model"])
            model_id = config["model"].split("](", 1)[1].removesuffix(")")
            turns = override.get("runConfig", {}).get("maxTurns", config["maxTurns"])
            if model not in (config["model"], model_id) or turns != config["maxTurns"]:
                gaps.append(f"native Qoder agent override differs from repository: {name}")
        return gaps
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return [f"unreadable Qoder settings: {path}: {error}"]


def check(home):
    result = common.check_files("qoder", home, role_config, profile_fields=("effort",))
    hook = home / ".qoder" / "hooks" / "session-identity.py"
    source = common.ROOT / "qoder" / "hooks" / "session-identity.py"
    if not hook.is_symlink() or not hook.exists() or hook.resolve() != source.resolve():
        result["missing"].append(f"identity hook must link to repository script: {hook} -> {source}")
    result["missing"].extend(_settings_gaps(home))
    result["configuration_scope"] = {
        "settings": str(home / ".qoder" / "settings.json"),
        "hook": str(hook),
        "override_fields": ["enabled", "modelConfig.model", "runConfig.maxTurns"],
    }
    result["disk_ready"] = not result["missing"]
    return result


def session():
    return os.environ.get("PROJECT_SESSION_ID")


if __name__ == "__main__":
    raise SystemExit(common.main(host="qoder"))

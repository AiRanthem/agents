#!/usr/bin/env python3
"""Qoder project-stage configuration and session identity."""

import json
import argparse
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    "project-design-reviewer": "design-review",
    "project-implementer": "implementation",
    "project-implementation-reviewer": "code-review",
    "project-fixer": "fix",
}
SKILLS = ("advance-project", "review-design", "explore-design", "implement-design",
          "review-implementation", "receiving-code-review")


def _markdown_config(content):
    # known-limit: JSON scalars cover these templates; richer frontmatter requires a YAML parser.
    header, body = content.removeprefix("---\n").split("\n---\n", 1)
    config = dict((key, json.loads(value.strip()))
                  for key, value in (line.split(":", 1) for line in header.splitlines()))
    config["developer_instructions"] = body.strip()
    return config


def _validate_role(source, name, config):
    for key in ("name", "description", "model", "developer_instructions"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{source}: missing {key}")
    if config["name"] != name:
        raise ValueError(f"{source}: native role name mismatch")


def _check_files(home, role_config, *, profile_fields=()):
    host = 'qoder'
    missing, roles = [], {}
    for name, stage in ROLES.items():
        source, content, config = role_config(name)
        target = home / f".{host}" / "agents" / source.name
        roles[name] = {"stage": stage, "source": str(source), "installed": str(target),
                       "model": config["model"]}
        for key in profile_fields:
            roles[name][key] = config[key]
        if target.is_symlink():
            kind = "TOML" if source.suffix == ".toml" else "Markdown"
            missing.append(f"native {host.capitalize()} agent must be a regular {kind} file: {target}")
        elif not target.is_file():
            missing.append(f"missing native agent: {target}")
        elif target.read_text() != content:
            missing.append(f"native agent differs from repository: {target}")
    skill_root = home / ".agents" / "skills"
    for name in SKILLS:
        skill_dir = skill_root / name
        expected = ROOT / "skills" / name
        try:
            if not skill_dir.is_symlink() or skill_dir.resolve(strict=True) != expected.resolve():
                missing.append(f"skill must link to repository directory: {skill_dir} -> {expected}")
                continue
            with (skill_dir / "SKILL.md").open("rb") as entry:
                entry.read(1)
        except (OSError, RuntimeError, ValueError) as error:
            missing.append(f"unreadable skill entry: {skill_dir / 'SKILL.md'}: {error}")
    return {"host": host, "disk_ready": not missing, "roles": roles, "missing": missing,
            "runtime_verified": False}


def role_config(name):
    source = ROOT / "qoder" / "agents" / f"{name}.md"
    content = source.read_text()
    config = _markdown_config(content)
    _validate_role(source, name, config)
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
        for name in ROLES:
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
    result = _check_files(home, role_config, profile_fields=("effort",))
    hook = home / ".qoder" / "hooks" / "session-identity.py"
    source = ROOT / "qoder" / "hooks" / "session-identity.py"
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "role"))
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--name", choices=ROLES)
    args = parser.parse_args(argv)
    try:
        if args.command == "role":
            if args.name is None:
                parser.error("role requires --name")
            source, _, config = role_config(args.name)
            result = injected_role(args.name)
        else:
            result = check(args.home)
        print(json.dumps(result, indent=2))
        return 0 if args.command == "role" or result["disk_ready"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"host": 'qoder', "disk_ready": False, "missing": [str(error)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Codex project-stage configuration and session identity."""

import argparse
import json
import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    "project-design-reviewer": "design-review",
    "project-implementer": "implementation",
    "project-implementation-reviewer": "code-review",
    "project-fixer": "fix",
}
SKILLS = ("advance-project", "review-design", "explore-design", "implement-design",
          "review-implementation", "receiving-code-review")


def _validate_role(source, name, config):
    for key in ("name", "description", "model", "developer_instructions"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{source}: missing {key}")
    if config["name"] != name:
        raise ValueError(f"{source}: native role name mismatch")


def _check_files(home, role_config, *, profile_fields=()):
    host = 'codex'
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
    source = ROOT / "codex" / "agents" / f"{name}.toml"
    content = source.read_text()
    config = tomllib.loads(content)
    _validate_role(source, name, config)
    if not config.get("model_reasoning_effort"):
        raise ValueError(f"{source}: missing model_reasoning_effort")
    return source, content, config


def check(home):
    return _check_files(home, role_config,
                              profile_fields=("model_reasoning_effort",))


def session():
    return os.environ.get("CODEX_THREAD_ID") or os.environ.get("PROJECT_SESSION_ID")


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
            result = {"host": "codex", "source": str(source), **config}
        else:
            result = check(args.home)
        print(json.dumps(result, indent=2))
        return 0 if args.command == "role" or result["disk_ready"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"host": 'codex', "disk_ready": False, "missing": [str(error)]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

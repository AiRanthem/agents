#!/usr/bin/env python3
"""Check project-stage agents or print native role definitions."""

import argparse
import json
from pathlib import Path
import sys
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


def role_config(host, name):
    extension = "toml" if host == "codex" else "md"
    source = ROOT / host / "agents" / f"{name}.{extension}"
    content = source.read_text()
    if host == "codex":
        config = tomllib.loads(content)
    else:
        # These checked-in templates deliberately use JSON strings as YAML scalars.
        # known-limit: this is not a general YAML parser; a richer frontmatter
        # format must replace this reader with a YAML parser before it is adopted.
        header, body = content.removeprefix("---\n").split("\n---\n", 1)
        config = dict((key, json.loads(value.strip()))
                      for key, value in (line.split(":", 1) for line in header.splitlines()))
        config["developer_instructions"] = body.strip()
    for key in ("name", "description", "model", "developer_instructions"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{source}: missing {key}")
    if config["name"] != name:
        raise ValueError(f"{source}: native role name mismatch")
    if host == "codex" and not config.get("model_reasoning_effort"):
        raise ValueError(f"{source}: missing model_reasoning_effort")
    if host == "qoder" and not config.get("effort"):
        raise ValueError(f"{source}: missing effort")
    return source, content, config


def _skill_files(directory):
    files = {}
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError(f"copied skill contains a symlink: {path}")
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    return files


def check(host, home, *, agents_dir=None, roles_file=None, skills_dir=None):
    if host != "cursor" and any(value is not None for value in (agents_dir, roles_file, skills_dir)):
        raise ValueError("explicit role/skill sources are supported only for Cursor")
    if agents_dir is not None and roles_file is not None:
        raise ValueError("select either an agents directory or injected roles")
    injected = None
    if roles_file is not None:
        injected = json.loads(roles_file.read_text())
        if not isinstance(injected, dict):
            raise ValueError("injected roles must be an object keyed by native role name")
    missing, roles = [], {}
    for name, stage in ROLES.items():
        source, content, config = role_config(host, name)
        target = (agents_dir if agents_dir is not None else home / f".{host}" / "agents") / source.name
        roles[name] = {"stage": stage, "source": str(source), "installed": str(target),
                       "model": config["model"]}
        if host == "codex":
            roles[name]["model_reasoning_effort"] = config["model_reasoning_effort"]
        if host == "qoder":
            roles[name]["effort"] = config["effort"]
        if injected is not None:
            actual = injected.get(name)
            if (not isinstance(actual, dict) or not isinstance(actual.get("source"), str) or
                    not actual["source"].strip()):
                missing.append(f"missing injected role or source: {name}")
            else:
                roles[name]["installed"] = actual["source"]
                if any(actual.get(key) != value for key, value in config.items()):
                    missing.append(f"injected role differs from repository: {name}")
            continue
        if host in ("codex", "qoder") and target.is_symlink():
            kind = "TOML" if host == "codex" else "Markdown"
            missing.append(f"native {host.capitalize()} agent must be a regular {kind} file: {target}")
        elif host == "cursor" and agents_dir is None and (not target.is_symlink() or target.resolve() != source.resolve()):
            missing.append(f"native Cursor agent must link to repository template: {target} -> {source}")
        elif not target.is_file():
            missing.append(f"missing native agent: {target}")
        elif target.read_text() != content:
            missing.append(f"native agent differs from repository: {target}")
    skill_root = skills_dir if skills_dir is not None else home / (".cursor" if host == "cursor" else ".agents") / "skills"
    for name in SKILLS:
        skill_dir = skill_root / name
        expected = ROOT / "skills" / name
        try:
            if not skill_dir.is_symlink() or skill_dir.resolve(strict=True) != expected.resolve():
                if skills_dir is not None and skill_dir.is_dir() and not skill_dir.is_symlink():
                    if _skill_files(skill_dir) != _skill_files(expected):
                        missing.append(f"copied skill differs from repository: {skill_dir}")
                else:
                    missing.append(f"skill must link to repository directory: {skill_dir} -> {expected}")
                continue
            with (skill_dir / "SKILL.md").open("rb") as entry:
                entry.read(1)
        except (OSError, RuntimeError, ValueError) as error:
            missing.append(f"unreadable skill entry: {skill_dir / 'SKILL.md'}: {error}")
    return {"host": host, "disk_ready": not missing, "roles": roles, "missing": missing,
            "runtime_verified": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "role"))
    parser.add_argument("--host", required=True, choices=("codex", "cursor", "qoder"))
    parser.add_argument("--home", type=Path, default=Path.home())
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--agents-dir", type=Path, help="Cursor project/cloud native agent directory")
    sources.add_argument("--roles-file", type=Path, help="Cursor injected role definitions and actual sources (JSON)")
    parser.add_argument("--skills-dir", type=Path, help="Cursor skill directory; accepts exact copies or repository links")
    parser.add_argument("--name", choices=ROLES, help="Native stage role for explicit dispatch")
    args = parser.parse_args(argv)
    try:
        if args.command == "role":
            if args.name is None:
                parser.error("role requires --name")
            source, _, config = role_config(args.host, args.name)
            print(json.dumps({"host": args.host, "source": str(source), **config}, indent=2))
            return 0
        result = check(args.host, args.home, agents_dir=args.agents_dir,
                       roles_file=args.roles_file, skills_dir=args.skills_dir)
        print(json.dumps(result, indent=2))
        return 0 if result["disk_ready"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        failure = {"host": args.host, "disk_ready": False, "missing": [str(error)]}
        print(json.dumps(failure))
        return 1


if __name__ == "__main__":
    sys.exit(main())

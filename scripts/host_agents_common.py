"""Shared file checks and CLI for project-stage host adapters."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    "project-design-reviewer": "design-review",
    "project-implementer": "implementation",
    "project-implementation-reviewer": "code-review",
    "project-fixer": "fix",
}
SKILLS = ("advance-project", "review-design", "explore-design", "implement-design",
          "review-implementation", "receiving-code-review")


def adapter(host):
    if host not in ("codex", "qoder"):
        raise ValueError(f"no independent host entry: {host}")
    name = "_devkit_host_" + host
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / host / "host.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules[name] = module
    return sys.modules[name]


def markdown_config(content):
    # known-limit: JSON scalars cover these templates; richer frontmatter requires a YAML parser.
    header, body = content.removeprefix("---\n").split("\n---\n", 1)
    config = dict((key, json.loads(value.strip()))
                  for key, value in (line.split(":", 1) for line in header.splitlines()))
    config["developer_instructions"] = body.strip()
    return config


def validate_role(source, name, config):
    for key in ("name", "description", "model", "developer_instructions"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{source}: missing {key}")
    if config["name"] != name:
        raise ValueError(f"{source}: native role name mismatch")


def check_files(host, home, role_config, *, profile_fields=()):
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


def role_config(host, name):
    return adapter(host).role_config(name)


def check(host, home):
    return adapter(host).check(home)


def main(argv=None, *, host=None):
    parser = argparse.ArgumentParser(description="Check project-stage agents or print native role definitions.")
    parser.add_argument("command", choices=("check", "role"))
    parser.add_argument("--host", required=host is None, default=host,
                        choices=(host,) if host else ("codex", "qoder"))
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--name", choices=ROLES, help="Native stage role for explicit dispatch")
    args = parser.parse_args(argv)
    try:
        if args.command == "role":
            if args.name is None:
                parser.error("role requires --name")
            source, _, config = role_config(args.host, args.name)
            result = ({"host": args.host, "source": str(source), **config} if args.host != "qoder"
                      else adapter("qoder").injected_role(args.name))
            print(json.dumps(result, indent=2))
            return 0
        result = check(args.host, args.home)
        print(json.dumps(result, indent=2))
        return 0 if result["disk_ready"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        failure = {"host": args.host, "disk_ready": False, "missing": [str(error)]}
        print(json.dumps(failure))
        return 1

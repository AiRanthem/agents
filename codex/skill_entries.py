#!/usr/bin/env python3
"""Describe native skill links and disable duplicate shared discovery entries."""

import argparse
import json
from pathlib import Path
import tomllib

DIRECTORY = Path(__file__).resolve().parent


def entries(home):
    result = []
    for entry in sorted((DIRECTORY / "skills").glob("*/SKILL.md")):
        name = entry.parent.name
        source = (DIRECTORY.parent / ".agents/skills/install/SKILL.md" if name == "install"
                  else DIRECTORY.parent / "skills" / name / "SKILL.md")
        shared = (source if name == "install" else home / ".agents/skills" / name / "SKILL.md")
        result.append({"name": name, "source": str(entry.parent),
                       "target": str(home / ".codex/skills" / name),
                       "config": [{"path": str(path), "enabled": False}
                                  for path in dict.fromkeys((source, shared))]})
    return result


def check(home):
    missing = []
    try:
        config = tomllib.loads((home / '.codex/config.toml').read_text())
        skill_config = config.get('skills', {})
        if not isinstance(skill_config, dict):
            raise ValueError('skills must be a table')
        configured = skill_config.get('config', [])
        if not isinstance(configured, list):
            raise ValueError('skills.config must be an array')
    except (OSError, ValueError, TypeError) as error:
        missing.append(f'unreadable native skill configuration: {error}')
        configured = []
    for entry in entries(home):
        target = Path(entry['target'])
        try:
            linked = target.is_symlink() and target.resolve(strict=True) == Path(entry['source'])
        except (OSError, RuntimeError):
            linked = False
        if not linked:
            missing.append(f'native skill must link to repository entry: {target}')
        for expected in entry['config']:
            matches = [item for item in configured if isinstance(item, dict) and item.get('path') == expected['path']]
            if not matches or any(item.get('enabled') is not False for item in matches):
                missing.append(f'duplicate shared discovery must be disabled: {expected["path"]}')
    return {'disk_ready': not missing, 'missing': missing, 'runtime_verified': False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = check(args.home.resolve()) if args.check else entries(args.home.resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if args.check and not result["disk_ready"] else 0)

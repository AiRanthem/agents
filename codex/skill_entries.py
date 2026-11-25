#!/usr/bin/env python3
"""Describe and check shared and Codex-specific skill installations."""

import argparse
import json
from pathlib import Path
import re
import tomllib

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent
ROUTING_ADAPTER = 'adapt-agent-routing'


def _skills(root):
    return {path.parent.name: path.parent for path in sorted(root.glob('*/SKILL.md'))}


def _installed_entry(target, source):
    try:
        if target.readlink() != source:
            return False
        with (target / 'SKILL.md').open('rb') as entry:
            return bool(entry.read(1))
    except OSError:
        return False


def entries(home, *, bootstrap=False):
    shared = _skills(ROOT / 'skills')
    entries = []
    for skills, destination in ((shared, home / '.agents/skills'),
                                (_skills(DIRECTORY / 'skills'), home / '.codex/skills')):
        for name, source in skills.items():
            config = []
            if destination == home / '.codex/skills' and name in shared:
                duplicate = shared[name]
                alias = home / '.agents/skills' / name
                paths = [duplicate / 'SKILL.md']
                if bootstrap or _installed_entry(alias, duplicate):
                    paths.append(alias / 'SKILL.md')
                config = [{'path': str(path), 'enabled': False} for path in paths]
            entries.append({'name': name, 'source': str(source),
                            'target': str(destination / name), 'config': config})
    return entries


def source_gaps():
    shared = _skills(ROOT / 'skills')
    native = _skills(DIRECTORY / 'skills')
    gaps = []
    if ROUTING_ADAPTER not in native:
        gaps.append(f'missing native skill adapter: {ROUTING_ADAPTER}')
    if ROUTING_ADAPTER not in shared:
        gaps.append(f'missing shared source for native skill adapter: {ROUTING_ADAPTER}')
    for source in (*shared.values(), *native.values()):
        path = source / 'SKILL.md'
        try:
            prefix, frontmatter, _ = path.read_text().split('---\n', 2)
            if (prefix or f'name: {source.name}' not in frontmatter.splitlines()
                    or not re.search(r'^description:[ \t]+\S', frontmatter, re.MULTILINE)):
                raise ValueError('expected matching name and description')
        except (OSError, ValueError) as error:
            gaps.append(f'invalid skill source: {path}: {error}')

    for name, source in native.items():
        path = source / 'agents/openai.yaml'
        try:
            # known-limit: check the fields used by these simple templates. A YAML parser
            # or the host must validate richer metadata.
            body = path.read_text()
            interface = re.search(r'^interface:\n((?:^[ ]{2}[^\n]+\n?)+)', body, re.MULTILINE)
            fields = re.findall(r'^  display_name: (.+)$', interface[1], re.MULTILINE) if interface else []
            if len(fields) != 1 or not isinstance(label := json.loads(fields[0]), str) or not label.strip():
                raise ValueError('expected a nonempty interface.display_name')
            policy_keys = re.findall(r'^policy:', body, re.MULTILINE)
            policies = re.findall(r'^policy:[ \t]*\n((?:^[ ]{2}[^\n]+\n?)+)', body, re.MULTILINE)
            flags = re.findall(r'^  allow_implicit_invocation: (.+)$', policies[0], re.MULTILINE) if len(policies) == 1 else []
            if policy_keys and (len(policy_keys) != 1 or flags not in (['true'], ['false'])):
                raise ValueError('expected a boolean policy.allow_implicit_invocation')
            if name == ROUTING_ADAPTER and flags == ['false']:
                raise ValueError('routing adapter must allow implicit invocation')
        except (OSError, ValueError) as error:
            gaps.append(f'invalid native skill metadata: {path}: {error}')
    return gaps


def _configured_paths(home):
    config = tomllib.loads((home / '.codex/config.toml').read_text())
    skills = config.get('skills', {})
    if not isinstance(skills, dict) or not isinstance(configured := skills.get('config', []), list):
        raise ValueError('skills.config must be an array')
    result = {}
    for item in configured:
        if isinstance(item, dict) and isinstance(item.get('path'), str):
            result.setdefault(item['path'], []).append(item.get('enabled'))
    return result


def _retired_links(destination, source_root, active_names):
    for path in sorted(destination.glob('*')):
        if path.name in active_names:
            continue
        try:
            target = path.parent / path.readlink()
            # Resolve only the parent, which must exist. Resolving a dangling
            # path lexically can erase a missing directory followed by '..'.
            if target.name == path.name and target.parent.resolve(strict=True) == source_root:
                yield path
        except (OSError, RuntimeError):
            continue


def check(home):
    missing = source_gaps()
    try:
        configured = _configured_paths(home)
    except (OSError, ValueError) as error:
        missing.append(f'unreadable native skill configuration: {error}')
        configured = {}

    shared = _skills(ROOT / 'skills')
    native = _skills(DIRECTORY / 'skills')
    for entry in entries(home):
        name = entry['name']
        source = Path(entry['source'])
        target = Path(entry['target'])
        if not _installed_entry(target, source):
            missing.append(f'skill must link to repository entry by absolute path: {target}')
        if target.parent == home / '.codex/skills' or name not in native:
            for path in (source, target):
                if any(flag is False for flag in configured.get(str(path / 'SKILL.md'), [])):
                    missing.append(f'skill must be enabled: {path / "SKILL.md"}')
        for required in entry['config']:
            flags = configured.get(required['path'], [])
            if not flags or any(flag is not False for flag in flags):
                missing.append(f'duplicate shared discovery must be disabled: {required["path"]}')

    for destination, source_root, names in (
        (home / '.codex/skills', DIRECTORY / 'skills', native),
        (home / '.agents/skills', ROOT / 'skills', shared),
    ):
        missing.extend(f'retired skill link: {path}' for path in _retired_links(destination, source_root, names))
    for path, flags in configured.items():
        source = Path(path)
        if (source.name == 'SKILL.md' and source.parent.parent == ROOT / 'skills'
                and source.parent.name not in shared and all(flag is False for flag in flags)):
            missing.append(f'retired shared discovery setting: {path}')
    return {'disk_ready': not missing, 'missing': missing, 'runtime_verified': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = check(args.home.resolve()) if args.check else entries(args.home.resolve())
    print(json.dumps(result, indent=2))
    raise SystemExit(1 if args.check and not result['disk_ready'] else 0)

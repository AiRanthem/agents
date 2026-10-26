#!/usr/bin/env python3
"""Bootstrap this dev kit in a fresh Cursor home (Python 3, standard library only)."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent
STATUSLINE_SAMPLE = '{"model":{"display_name":"Opus"},"context_window":{"used_percentage":25}}\n'


def skill_name(path):
    text = path.read_text(encoding='utf-8')
    if not text.startswith('---'):
        raise ValueError(f'{path}: missing frontmatter')
    end = text.find('\n---', 3)
    if end < 0:
        raise ValueError(f'{path}: unterminated frontmatter')
    for line in text[3:end].splitlines():
        if line.startswith('name:'):
            value = line.split(':', 1)[1].strip().strip('"').strip("'")
            if value:
                return value
    raise ValueError(f'{path}: frontmatter name missing')


def shared_skills():
    found = []
    for manifest in sorted((ROOT / 'skills').glob('*/SKILL.md')):
        if skill_name(manifest) != manifest.parent.name:
            raise ValueError(f'{manifest}: name differs from directory')
        found.append(manifest.parent.resolve())
    if not found:
        raise ValueError('no shared skills found')
    return found


def managed_config():
    config = json.loads((DIRECTORY / 'cli-config.json').read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('cli-config.json must be a JSON object')
    status_line = json.loads((DIRECTORY / 'cli-statusline.json').read_text(encoding='utf-8'))
    if not isinstance(status_line, dict):
        raise ValueError('cli-statusline.json must be a JSON object')
    config['statusLine'] = status_line
    return config


def installation_links(home):
    links = {}
    rules = sorted(path.resolve() for path in (DIRECTORY / 'rules').glob('*.mdc') if path.is_file())
    agents = sorted(path.resolve() for path in (DIRECTORY / 'agents').glob('*.md') if path.is_file())
    if not rules:
        raise ValueError('no cursor rules found')
    if not agents:
        raise ValueError('no cursor agents found')
    for source in rules:
        links[home / '.cursor/rules' / source.name] = source
    for source in agents:
        links[home / '.cursor/agents' / source.name] = source
    statusline = (DIRECTORY / 'statusline.sh').resolve()
    if not statusline.is_file() or not os.access(statusline, os.X_OK):
        raise ValueError(f'{statusline} must be an executable file')
    links[home / '.cursor/statusline.sh'] = statusline
    for source in shared_skills():
        links[home / '.cursor/skills' / source.name] = source
        links[home / '.agents/skills' / source.name] = source
    return links


def assert_ordinary_parents(home, target):
    for parent in target.parents:
        if parent == home:
            break
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError(f'installation parent must be an ordinary directory: {parent}')


def classify_link(target, source):
    if target.is_symlink():
        try:
            current = target.resolve(strict=True)
        except OSError as error:
            raise ValueError(f'{target} is an unreadable symlink: {error}') from error
        if current == source:
            return 'keep'
        raise ValueError(f'{target} already exists; use an Agent for updates')
    if target.exists():
        raise ValueError(f'{target} already exists; use an Agent for updates')
    return 'create'


def plan_cli_config(dest, desired):
    if dest.is_symlink() or (dest.exists() and not dest.is_file()):
        raise ValueError(f'{dest} already exists; use an Agent for updates')
    if not dest.exists():
        return desired
    try:
        current = json.loads(dest.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f'{dest} is not valid JSON: {error}') from error
    if not isinstance(current, dict):
        raise ValueError(f'{dest} must be a JSON object')
    for key, value in desired.items():
        if key in current and current[key] != value:
            raise ValueError(f'{dest}: {key} differs from the repository; use an Agent for updates')
    if all(key in current for key in desired):
        return None
    updated = dict(current)
    for key, value in desired.items():
        updated.setdefault(key, value)
    return updated


def verify(home, links, desired):
    for target, source in links.items():
        try:
            linked = target.is_symlink() and target.resolve(strict=True) == source
        except OSError:
            linked = False
        if not linked:
            raise ValueError(f'{target} must link to {source}')
        if (source / 'SKILL.md').is_file():
            manifest = target / 'SKILL.md'
            try:
                with manifest.open('rb') as entry:
                    entry.read(1)
            except OSError as error:
                raise ValueError(f'unreadable skill: {manifest}: {error}') from error
    config_path = home / '.cursor/cli-config.json'
    config = json.loads(config_path.read_text(encoding='utf-8'))
    for key, value in desired.items():
        if config.get(key) != value:
            raise ValueError(f'{config_path}: {key} does not match the repository')
    script = home / '.cursor/statusline.sh'
    result = subprocess.run(
        [str(script)],
        input=STATUSLINE_SAMPLE,
        text=True,
        capture_output=True,
        timeout=15,
        env={**os.environ, 'HOME': str(home)},
        check=False,
    )
    if not result.stdout.strip():
        detail = result.stderr.strip() or f'exit {result.returncode}'
        raise ValueError(f'statusline produced no output: {detail}')


def install(home):
    home = home.resolve()
    links = installation_links(home)
    desired = managed_config()
    config_path = home / '.cursor/cli-config.json'
    for target in [*links, config_path]:
        assert_ordinary_parents(home, target)
    actions = {target: classify_link(target, source) for target, source in links.items()}
    replacement = plan_cli_config(config_path, desired)
    # known-limit: bootstrap is single-process and nontransactional. A failed cloud
    # home should be discarded. This script does not remove links for skills, rules,
    # or agents deleted from the repository; an Agent updates an existing installation.
    for target, source in links.items():
        if actions[target] != 'create':
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)
    if replacement is not None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(replacement, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    verify(home, links, desired)
    return {
        'status': 'disk_ready',
        'links': len(links),
        'created': sum(action == 'create' for action in actions.values()),
        'runtime_verified': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home(), help='target user home; defaults to current user')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(install(args.home.expanduser()), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

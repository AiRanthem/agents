#!/usr/bin/env python3
"""Bootstrap this dev kit in a fresh cloud-agent home (Python 3.11+)."""

import argparse
import json
import os
from pathlib import Path
import sys
import tomllib

import host
import skill_entries

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parent


def installation(home):
    """Build the first-install files and links; leave existing installations to an Agent."""
    codex = home / '.codex'
    configured_home = os.environ.get('CODEX_HOME')
    if configured_home and Path(configured_home).expanduser().resolve() != codex:
        raise ValueError('CODEX_HOME must match --home/.codex')
    override = codex / 'AGENTS.override.md'
    if override.exists() and override.read_text().strip():
        raise ValueError(f'{override} overrides kit instructions; resolve it before initialization')

    links = {codex / 'AGENTS.md': DIRECTORY / 'AGENTS.md'}
    for name in ('session-start.py', 'subagent-start.py'):
        links[codex / 'hooks' / name] = DIRECTORY / 'hooks' / name
    shared = sorted((ROOT / 'skills').glob('*/SKILL.md'))
    if not shared:
        raise ValueError('no shared skills found')
    for entry in shared:
        links[home / '.agents/skills' / entry.parent.name] = entry.parent
    native = skill_entries.entries(home)
    if not native:
        raise ValueError('no native skills found')
    for entry in native:
        links[Path(entry['target'])] = Path(entry['source'])

    files = {}
    for name in host.ROLES:
        host.role_config(name)
    for source in sorted((DIRECTORY / 'agents').glob('*.toml')):
        config = tomllib.loads(source.read_text())
        for key in ('name', 'description', 'developer_instructions'):
            if not isinstance(config.get(key), str) or not config[key].strip():
                raise ValueError(f'{source}: missing {key}')
        if config['name'] != source.stem:
            raise ValueError(f'{source}: name differs from filename')
        files[codex / 'agents' / source.name] = source.read_bytes()
    if not files:
        raise ValueError('no native agents found')
    hooks = (DIRECTORY / 'hooks.json').read_bytes()
    json.loads(hooks)
    files[codex / 'hooks.json'] = hooks

    # A cloud image may seed provider/model settings before the kit is installed.
    # Preserve those bytes; only append sections absent from that configuration.
    config_path = codex / 'config.toml'
    content = config_path.read_text() if config_path.exists() else ''
    config = tomllib.loads(content)
    if 'agents' in config or 'config' in config.get('skills', {}):
        raise ValueError(f'{config_path}: agents or skills.config already configured; use an Agent to integrate the kit')
    lines = [content, '', '[agents]', 'max_concurrent_threads_per_session = 20']
    for entry in native:
        for setting in entry['config']:
            lines.extend(['', '[[skills.config]]',
                          'path = ' + json.dumps(setting['path'], ensure_ascii=False), 'enabled = false'])
    candidate = '\n'.join(lines) + '\n'
    tomllib.loads(candidate)
    files[config_path] = candidate.encode('utf-8')

    # Preflight all owned destinations before creating the first entry.
    for target in [*links, *files]:
        for parent in target.parents:
            if parent == home:
                break
            if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                raise ValueError(f'installation parent must be an ordinary directory: {parent}')
        if target == config_path and target.is_file() and not target.is_symlink():
            continue
        if target.exists() or target.is_symlink():
            raise ValueError(f'{target} already exists; use an Agent for updates or reconciliation')
    for source in links.values():
        if not source.exists():
            raise ValueError(f'missing installation source: {source}')
    return links, files, content


def install(home):
    links, files, original_config = installation(home)
    config_path = home / '.codex/config.toml'
    # known-limit: bootstrap is single-process and nontransactional. Discard a failed
    # cloud home and initialize a fresh one; existing environments use the Agent installer.
    for target, source in links.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source)
    for target, content in files.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if target == config_path and target.exists():
            # Bootstrap runs in one initialization process, before the Agent starts.
            if target.read_text() != original_config:
                raise ValueError(f'{target} changed during initialization')
            with target.open('ab') as output:
                output.write(content[len(original_config.encode('utf-8')):])
        else:
            with target.open('xb') as output:
                output.write(content)
            target.chmod(0o600)
    errors = host.check(home)['missing'] + skill_entries.check(home)['missing']
    if errors:
        raise ValueError('; '.join(errors))
    return {'status': 'disk_ready', 'links': len(links), 'files': len(files),
            'runtime_verified': False,
            'next_step': 'Run Codex doctor; review new hooks in /hooks where supported, then start the Agent'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home(), help='target user home; defaults to current user')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(install(args.home.expanduser().resolve()), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())

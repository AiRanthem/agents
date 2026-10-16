"""Render the installed workspace assets without interpreting user Markdown."""
from __future__ import annotations

from pathlib import Path
import re


TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / 'create-project' / 'assets' / 'workspace'
DEVKIT_SOURCE = 'git@github.com:AiRanthem/agents.git'
GENERATED_PROJECT_PATHS = ('AGENTS.md', '.project/workflow.md', '.project/recovery.md')


def replacements(project, context=''):
    storage = project.get('storage', {})
    return {
        '{{PROJECT_ID}}': project['id'],
        '{{PROJECT_NAME}}': project['name'],
        '{{PROJECT_BACKGROUND}}': context.rstrip(),
        '{{STORAGE_BRANCH}}': storage.get('branch', ''),
        '{{STORAGE_URL}}': storage.get('url', ''),
        '{{DEVKIT_SOURCE}}': DEVKIT_SOURCE,
        '{{DELIVERY_CONVENTIONS}}': 'Follow the delivery requirements recorded in each work item.',
    }


def render_template(name, project, context=''):
    template = (TEMPLATE_ROOT / name).read_text(encoding='utf-8')
    values = replacements(project, context)
    found = set(re.findall(r'\{\{[^{}]+\}\}', template))
    unknown = found - values.keys()
    if unknown:
        raise ValueError(f'unknown template placeholder in {name}: {sorted(unknown)}')
    # A single substitution pass leaves braces in user text untouched.
    return re.sub(r'\{\{[^{}]+\}\}', lambda match: values[match.group(0)], template)


def render_workspace(project, context):
    return {source.relative_to(TEMPLATE_ROOT).as_posix():
            render_template(source.relative_to(TEMPLATE_ROOT).as_posix(), project, context).encode('utf-8')
            for source in sorted(TEMPLATE_ROOT.rglob('*')) if source.is_file()}


def project_entries(project):
    return {name: render_template(name, project) for name in GENERATED_PROJECT_PATHS}

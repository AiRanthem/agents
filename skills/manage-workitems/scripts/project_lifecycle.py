"""Project-owned source generations and exact, resumable internal-resource GC.

Records live in workflow.lifecycle and use the ordinary guarded publication path.
Only explicitly adopted internal resources are disposable; ordinary source refs
and unique, undisposed work remain protected. No remote-prefix discovery is used.
"""
import copy
import json
import re
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
import shlex
import shutil
import socket
import sys
import tempfile

try:
    import project_runtime as runtime
    import project_store as store
    import project_workflow as workflow
    import project_development as development
    import project_autonomy as autonomy
except ImportError:
    from . import project_runtime as runtime, project_store as store, project_workflow as workflow
    from . import project_development as development, project_autonomy as autonomy

ProjectError = runtime.ProjectError


def state(item):
    return item.setdefault('workflow', {}).setdefault('lifecycle', {})


def _id(*parts):
    return workflow._hash(workflow._canonical(parts))[:32]


def _local_id(item, kind, identity, host=None):
    return _id(item['id'], kind, [host or socket.gethostname(), identity])


def _time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ProjectError('resource timestamps require a timezone')
    return result


def _command(root, action, *args):
    return shlex.join([sys.executable, str(Path(__file__).with_name('project.py')), '--root', str(root),
                       'lifecycle', action, *map(str, args)])


def _item(root, selector):
    root, files = autonomy._files(root)
    item = store.item(files, workflow._resolve(store.items(files), selector))
    return root, files, item, workflow._identity(root, item=item["id"])


def _quiescent(root, files, item, identity):
    workflow._ownership(item, identity)
    handoff = state(item).get('handoff')
    if handoff and not workflow._ownership_module().handoff_authorized(handoff, identity):
        raise ProjectError('lifecycle has another control claim; use explicit takeover')
    if not workflow._ownership_module().authorized(item, identity):
        raise ProjectError('lifecycle has another control claim; use explicit takeover')
    # Unsettled metadata publications may still contain source or resource state.
    directory = root / '.project-local/publish'
    runtime._no_links(root, '.project-local/publish')
    for path in directory.glob('*/journal.json'):
        runtime._no_links(root, path.relative_to(root).as_posix())
        if runtime.publication_disposition(runtime.read_json(path)) not in {'published', 'rejected_before_push'}:
            raise ProjectError('unsettled project publication; resume its original intent first')
    if any((store.receipt(files, key) or {}).get('state') in {'pending', 'unknown'} for key in store.items(files)):
        raise ProjectError('unsettled project synchronization; preserve its original intent')


def _save(root, files, item, identity, message, publish):
    return autonomy._publish(root, files, [item], identity, message, publish)


def _settled(result):
    return result.get('status') in {'published', 'no_op'}


def handoff(root, selector, *, approval_source, mode, coordinator_session=None, publish=None):
    """Change execution ownership while retaining contract, source and baseline."""
    workflow._text(approval_source, 'explicit execution-mode and coordinator handoff authorization')
    if mode not in {'manual', 'autonomous'}:
        raise ProjectError('mode must be manual or autonomous')
    root, files, item, identity = _item(root, selector)
    _quiescent(root, files, item, identity)
    lifecycle = state(item)
    if lifecycle.get('transition') or lifecycle.get('replacement_pending') or (lifecycle.get('gc') or {}).get('state') in {'planned', 'collecting'}:
        raise ProjectError('settle the original resource transition before execution handoff')
    auth = autonomy._state(item)
    previous = auth.pop('authorization', None)
    if previous:
        lifecycle.setdefault('authorizations', []).append(previous)
    lifecycle['mode'] = mode
    lifecycle['handoff'] = {'from': identity['session'], 'to': coordinator_session or identity['session'],
                             'source': approval_source, 'created_at': workflow._now()}
    item['owner'] = None
    return _save(root, files, item, identity, 'Hand off execution mode ' + item['id'], publish)


def policy(root, selector, *, approval_source, grace_days=7, max_retained=2, max_snapshots=20, publish=None):
    workflow._text(approval_source, 'explicit internal archive publication and resource cleanup policy approval')
    if (type(grace_days) is not int or grace_days < 0 or type(max_retained) is not int or max_retained < 1 or
            type(max_snapshots) is not int or max_snapshots < 1):
        raise ProjectError('policy requires nonnegative grace days and positive retained-generation capacity')
    root, files, item, identity = _item(root, selector)
    _quiescent(root, files, item, identity)
    state(item)['policy'] = {'source': approval_source, 'grace_days': grace_days,
                             'max_retained': max_retained, 'max_snapshots': max_snapshots, 'recorded_by': identity['session']}
    return _save(root, files, item, identity, 'Adopt internal resource lifecycle ' + item['id'], publish)


def _policy(item):
    value = state(item).get('policy')
    if not value or not value.get('source'):
        raise ProjectError('explicit lifecycle policy required for internal archive publication and resource cleanup')
    return value


def capacity(item, *, retiring=False, snapshot=False):
    lifecycle = (item.get('workflow') or {}).get('lifecycle') or {}
    policy = lifecycle.get('policy')
    if not policy:
        return
    if snapshot:
        captures = list(lifecycle.get('checkpoints', {}).values())
        resident = [value for value in captures if lifecycle.get('resources', {}).get(
            _id(item['id'], 'remote-ref', [value['url'], value['ref']]), {}).get('state') != 'deleted']
        if len(resident) >= policy.get('max_snapshots', 20):
            raise ProjectError('snapshot resource capacity reached; release and collect unused internal refs')
        return
    pending = [key for key, value in lifecycle.get('generations', {}).items() if not value.get('disposition')]
    pending_paths = {value['development']['worktree'] for value in lifecycle.get('generations', {}).values()
                     if not value.get('disposition')}
    current = (item.get('development') or {}).get('worktree')
    resident = [descriptor['worktree'] for descriptor, _ in _descriptors(item).values()
                if descriptor['worktree'] != current and lifecycle.get('resources', {}).get(
                    _local_id(item, 'worktree', descriptor['worktree'], descriptor.get('host')), {}).get('state') != 'deleted']
    count = len(pending_paths | set(resident))
    if count > policy['max_retained'] or (retiring and count >= policy['max_retained']):
        raise ProjectError('retained-generation capacity reached; migrate/clean old resources: ' + ','.join(pending + resident))


def _resource(item, kind, identity, **values):
    if kind == 'remote-ref':
        key = _id(item['id'], kind, identity)
    else:
        values.setdefault('host', socket.gethostname())
        key = _local_id(item, kind, identity, values['host'])
    return key, {'id': key, 'item': item['id'], 'kind': kind, **values}


def _capture(item, identifier):
    captured = state(item).get('checkpoints', {}).get(identifier)
    if not captured:
        raise ProjectError('resource has no registered snapshot identity')
    return captured


def _descriptors(item):
    result = {}
    lifecycle = state(item)
    for key, value in lifecycle.get('generations', {}).items():
        descriptor = value.get('development')
        if descriptor:
            reasons = [] if value.get('disposition') else ['undisposed-source:' + key]
            result[descriptor['worktree']] = (descriptor, reasons)
    if item.get('development'):
        result[item['development']['worktree']] = (item['development'], ['current-development'])
    return result


def inventory(files, selector=None):
    rows = []
    for item in store.items(files).values():
        if selector and item['id'] != selector:
            continue
        saved = state(item).get('resources', {})
        captures = list(state(item).get('checkpoints', {}).values())
        for value in captures:
            reasons = ['pending-archive'] if value['status'] != 'published' else []
            reasons += ['unique-source:' + key for key, generation in state(item).get('generations', {}).items()
                        if value['id'] in [generation.get('checkpoint'), *generation.get('superseded_checkpoints', [])] and not generation.get('disposition')]
            # Physical cleanup still needs recovery after semantic migration.
            # Release that last recovery ref only after worktree removal is recorded.
            for generation in state(item).get('generations', {}).values():
                if generation.get('checkpoint') == value['id']:
                    path = generation['development']['worktree']
                    resource = saved.get(_local_id(item, 'worktree', path, generation['development'].get('host')), {})
                    if resource.get('state') != 'deleted':
                        reasons.append('physical-recovery:' + path)
            identities = [('remote-ref', [value['url'], value['ref']], value['ref']),
                          ('local-ref', value['branch'], 'refs/heads/' + value['branch'])]
            for kind, identity, ref in identities:
                key, row = _resource(item, kind, identity, repository=value['repository'], ref=ref,
                                     url=value['url'], oid=value.get('commit'), snapshot=value['id'])
                # Published preservation branches remain subject to checked-out-worktree protection.
                row['retained_by'] = reasons if kind == 'remote-ref' else (
                    ['pending-publication'] if value['status'] != 'published' else [])
                row = {**saved.get(key, {}), **row}
                rows.append(row)
        for descriptor, reasons in _descriptors(item).values():
            key, row = _resource(item, 'worktree', descriptor['worktree'], repository=descriptor.get('repository', item['repository']),
                                 descriptor=copy.deepcopy(descriptor), retained_by=reasons,
                                 host=descriptor.get('host', socket.gethostname()))
            row = {**saved.get(key, {}), **row}
            rows.append(row)
        # Preserve tombstones, even when the current pointer no longer mentions a resource.
        present = {row['id'] for row in rows}
        for key, row in saved.items():
            if key not in present:
                row = copy.deepcopy(row)
                if row.get('kind') == 'runtime-cache' and row.get('state') != 'deleted':
                    # known-limit: legacy caches can contain the only unpublished
                    # report. Retain them until a dedicated archival verifier can
                    # prove recovery from formal content, independent of workers.
                    row['retained_by'] = ['historical-runtime-cache']
                rows.append(row)
    return rows


def status(root, selector=None):
    root = runtime.find_project(root)
    files = runtime._working_files(root)
    identifier = workflow._resolve(store.items(files), selector) if selector else None
    pending = {key: {name: copy.deepcopy(value[name]) for name in ('transition', 'replacement', 'replacement_pending', 'gc', 'handoff') if name in value}
               for key, item in store.items(files).items() if not identifier or key == identifier
               for value in [state(item)]}
    return {'status': 'ready', 'resources': inventory(files, identifier), 'pending': pending, 'diagnostic_only': True}


def reconcile(files, writes):
    """Record reference release at the mutation, rather than at a later GC run."""
    prospective = store.apply_writes(files, writes)
    records = store.items(prospective)
    touched = set()
    for row in inventory(prospective):
        item = records[row['item']]
        if not state(item).get('policy'):
            continue
        resources = state(item).setdefault('resources', {})
        prior = resources.get(row['id'], {})
        value = copy.deepcopy(row)
        if prior.get('state') in {'deleting', 'deleted'}:
            if row.get('retained_by'):
                raise ProjectError('a retiring resource cannot acquire a new reference')
        elif row.get('retained_by'):
            value['state'] = 'live'
            value.pop('released_at', None)
            value.pop('eligible_at', None)
        else:
            value['state'] = 'released'
            value.setdefault('released_at', workflow._now())
        if value != prior:
            resources[row['id']] = value
            touched.add(item['id'])
    result = {}
    for identifier in touched:
        result.update(store.write_item(prospective, records[identifier]))
    return result


def _checkpoint(root, files, item, identity, source, publish, descriptor=None):
    """Store both index and working trees without touching source HEAD/index/files."""
    lifecycle = state(item)
    checkpoint = lifecycle.get('transition', {}).get('checkpoint')
    descriptor = descriptor or item['development']
    source_item = dict(item, development=descriptor)
    location = development.worktree_location(root, source_item, store.project(files))
    configuration = development._configuration(location, development._repository(item, store.project(files)))
    development._existing_record(root, source_item, store.project(files), location, configuration)
    if not checkpoint:
        capacity(item, snapshot=True)
        actual = development.snapshot(location)
        if any(entry.startswith(b'160000 ') for entry in development._git(location, 'ls-tree', '-rz', actual['tree']).stdout.split(b'\0')):
            raise ProjectError('nested repositories require explicit source preservation')
        # write-tree can update index cache metadata; use a private copy too.
        with tempfile.TemporaryDirectory(prefix='project-preserved-index-') as directory:
            index = Path(directory) / 'index'
            original = Path(development._text(location, 'rev-parse', '--git-path', 'index'))
            if not original.is_absolute():
                original = location / original
            shutil.copyfile(original, index)
            index_tree = development._text(location, 'write-tree', env={'GIT_INDEX_FILE': str(index)})
        key = secrets.token_hex(16)
        branch = 'preservation/' + store.project(files)['id'] + '/' + item['id'] + '/' + key
        ref = development._published_ref(location, descriptor['publish_remote'], branch,
                                           development._repository(item, store.project(files)))
        checkpoint = {'id': key, 'kind': 'preservation-checkpoint', 'item': item['id'],
                      'repository': item['repository'], 'branch': branch, 'ref': ref,
                      'url': descriptor['publish_url'], 'status': 'planned', 'source': actual,
                      'head': actual['head'], 'tree': actual['tree'], 'index_tree': index_tree,
                      'source_worktree': descriptor['worktree'],
                      'authorization_source': source, 'host': identity['machine'],
                      'common_dir': development._text(location, 'rev-parse', '--path-format=absolute', '--git-common-dir')}
        lifecycle.setdefault('checkpoints', {})[key] = checkpoint
        lifecycle.setdefault('transition', {})['checkpoint'] = key
        result = _save(root, files, item, identity, 'Plan preservation checkpoint ' + item['id'], publish)
        if not _settled(result):
            return result, None
        root, files, item, identity = _item(root, item['id'])
        lifecycle = state(item)
        checkpoint = lifecycle['checkpoints'][key]
    else:
        checkpoint = lifecycle['checkpoints'][checkpoint]
        if checkpoint.get('source_worktree') != descriptor['worktree']:
            raise ProjectError('resume the original preservation target before another transition')
    # Planned identity survives failed pushes. Preserve staged and unstaged distinctions.
    if development.snapshot(location) != checkpoint['source']:
        raise ProjectError('source changed during generation transition; preserve the original checkpoint intent')
    local = 'refs/heads/' + checkpoint['branch']
    if checkpoint['status'] == 'planned':
        index_commit = development._text(location, 'commit-tree', checkpoint['index_tree'], '-p', checkpoint['head'],
                                            '-m', 'Preserved index ' + checkpoint['id'])
        commit = development._text(location, 'commit-tree', checkpoint['tree'], '-p', index_commit,
                                      '-m', 'Unreviewed preservation checkpoint ' + checkpoint['id'])
        existing = development._git(location, 'rev-parse', '--verify', local, check=False)
        if existing.returncode == 0:
            commit = existing.stdout.decode().strip()
            if (development._text(location, 'rev-parse', commit + '^{tree}') != checkpoint['tree'] or
                    development._text(location, 'rev-parse', commit + '^^') != checkpoint['head'] or
                    development._text(location, 'rev-parse', commit + '^' + '^{tree}') != checkpoint['index_tree']):
                raise ProjectError('preservation branch differs from its recorded intent')
        else:
            development._git(location, 'update-ref', local, commit, '0' * len(commit))
        checkpoint.update(status='committed', commit=commit)
        result = _save(root, files, item, identity, 'Bind preservation checkpoint ' + item['id'], publish)
        if not _settled(result):
            return result, None
        root, files, item, identity = _item(root, item['id'])
        checkpoint = state(item)['checkpoints'][checkpoint['id']]
    remote = development._remote_head(location, checkpoint['url'], checkpoint['ref'])
    if remote is not None and remote != checkpoint['commit']:
        raise ProjectError('preservation remote ref changed; preserve the original intent')
    if remote is None:
        development._git(location, 'push', '--', checkpoint['url'], checkpoint['commit'] + ':' + checkpoint['ref'])
    if development._remote_head(location, checkpoint['url'], checkpoint['ref']) != checkpoint['commit']:
        raise ProjectError('preservation publication uncertain; resume the same transition')
    checkpoint['status'] = 'published'
    result = _save(root, files, item, identity, 'Verify preservation checkpoint ' + item['id'], publish)
    return result, checkpoint


def replan(root, selector, *, approval_source, mode='autonomous', coordinator_session=None, publish=None):
    """Close the old generation; prepare() creates the replacement from current inputs."""
    workflow._text(approval_source, 'explicit replan and mode-handoff authorization')
    if mode not in {'manual', 'autonomous'}:
        raise ProjectError('mode must be manual or autonomous')
    root, files, item, identity = _item(root, selector)
    _quiescent(root, files, item, identity)
    _policy(item)
    previous = state(item).get('last_replan') or {}
    if (previous.get('contract') == workflow._approval_binding(files, item) and
            previous.get('source_worktree') == (item.get('development') or {}).get('worktree') and
            state(item).get('replacement_pending')):
        return {'status': 'no_op', 'next_action': 'prepare_replacement', 'mode': state(item)['mode']}
    capacity(item, retiring=True)
    if any(row.get('state') == 'deleting' for row in inventory(files, item['id'])):
        raise ProjectError('resource deletion must settle before replacing this generation')
    auth = autonomy._state(item)
    if item.get('development'):
        state(item).setdefault('transition', {}).update(requested_mode=mode, coordinator_session=coordinator_session, source=approval_source)
        result, checkpoint = _checkpoint(root, files, item, identity, approval_source, publish)
        if not _settled(result):
            return result
        # Reread after write-ahead checkpoints; never rebuild an uncertain operation.
        root, files, item, identity = _item(root, item['id'])
        auth, lifecycle = autonomy._state(item), state(item)
        key = checkpoint['id']
        lifecycle.setdefault('generations', {})[key] = {'id': key, 'development': copy.deepcopy(item['development']),
            'checkpoint': checkpoint['id'],
            'retired_at': workflow._now(), 'source': approval_source}
    else:
        lifecycle = state(item)
    lifecycle.pop('transition', None)
    previous = auth.pop('authorization', None)
    if previous:
        lifecycle.setdefault('authorizations', []).append(previous)
    auth.pop('next_role', None)
    auth.pop('blocker', None)
    lifecycle['mode'] = mode
    lifecycle['replacement_pending'] = True
    lifecycle['fresh_reviews_required'] = True
    lifecycle['last_replan'] = {'contract': workflow._approval_binding(files, item),
                               'source_worktree': (item.get('development') or {}).get('worktree')}
    lifecycle['handoff'] = {'from': identity['session'], 'to': coordinator_session or identity['session'],
                             'source': approval_source, 'created_at': workflow._now()}
    workflow._design_reuse().capture(root, files, item)
    workflow._invalidate_implementation(item)
    item['design'].pop('review', None)
    if item['design'].get('approval'):
        item['design']['state'] = 'review-pending'
    item['status'], item['owner'] = 'in_progress', None
    # Retain the source pointer until prepare creates its replacement. Dirty source
    # is allowed only when it still exactly matches the verified checkpoint.
    return _save(root, files, item, identity, 'Retire generation and hand off ' + item['id'], publish)


def dispose(root, selector, *, generation, disposition, reference, approval_source=None, publish=None):
    root, files, item, identity = _item(root, selector)
    _quiescent(root, files, item, identity)
    _policy(item)
    workflow._text(reference, 'actual migration review or discard evidence')
    value = state(item).get('generations', {}).get(generation)
    if not value:
        raise ProjectError('unknown retained generation')
    if disposition == 'migrated':
        workflow._implementation_approved(files, item)
        if (item.get('development') or {}).get('worktree') == value['development']['worktree']:
            raise ProjectError('replacement generation must differ from the source')
        if workflow._code_snapshot(root, item, store.project(files)) != item['development']['reviewed_snapshot']:
            raise ProjectError('migration target differs from its independent review')
    elif disposition == 'discarded':
        workflow._text(approval_source, 'explicit authorization to discard this unique source generation')
    else:
        raise ProjectError('disposition must be migrated or discarded')
    value['disposition'] = {'kind': disposition, 'reference': reference, 'source': approval_source,
                             'recorded_by': identity['session'], 'created_at': workflow._now()}
    return _save(root, files, item, identity, 'Dispose retained source ' + item['id'], publish)


def source_preserved(root, files, item):
    """A retired dirty source can be read, never reset, while replacing its baseline."""
    actual = development.snapshot(development.worktree_location(root, item, store.project(files)))
    for value in state(item).get('checkpoints', {}).values():
        if value.get('status') == 'published' and value['source'] == actual:
            checkout = development.worktree_location(root, item, store.project(files))
            return development._remote_head(checkout, value['url'], value['ref']) == value['commit']
    return False


def replacement_item(item):
    """A controlled cross-host replacement uses the new host's bound repository.

    The old descriptor stays in generation history; it is not reinterpreted as a
    same-named path on the receiving machine.
    """
    descriptor = item.get('development') or {}
    lifecycle = state(item)
    host = descriptor.get('host')
    for generation in lifecycle.get('generations', {}).values():
        if generation['development'].get('worktree') == descriptor.get('worktree'):
            checkpoint = lifecycle.get('checkpoints', {}).get(generation.get('checkpoint'), {})
            host = host or checkpoint.get('host')
    if lifecycle.get('replacement_pending') and host and host != socket.gethostname():
        return dict(item, development=None)
    return item


def _matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _switch_reservation(root, item, project, desired):
    """Only adopt the exact old/current reservation during this recorded generation."""
    path = development._reservation_path(root, development._identity(project, item))
    wanted = {"identity": development._identity(project, item), "branch": desired["branch"],
              "worktree": desired["worktree"], "configuration": {key: desired[key] for key in
              ("base_remote", "base_ref", "base_url", "publish_remote", "publish_url")}}
    previous = path.read_bytes() if path.exists() else None
    if previous is not None:
        actual = store.load_yaml(previous, str(path))
        if actual == wanted:
            return
        old = item.get("development")
        expected = dict(wanted, branch=old["branch"], worktree=old["worktree"]) if old else None
        if actual != expected:
            raise ProjectError("development reservation differs from the retained generation")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(store.dump_yaml(wanted))
    try:
        if (path.read_bytes() if path.exists() else None) != previous:
            raise ProjectError("development reservation changed concurrently")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _new_worktree(root, files, item, generation, start, label):
    project = store.project(files)
    repo = development._repository(item, project)
    checkout = development._checkout(root, replacement_item(item), project, repo, {})
    configuration = development._configuration(checkout, repo)
    _, container = runtime._layout(root, project)
    branch = repo.get("branch_pattern", "feature/{project}/{item}-{session}").format(
        project=project["id"], item=item["id"], session=label + "-" + generation[:12])
    development._ref(checkout, "refs/heads/" + branch)
    relative = container / (item["id"] + "-" + label + "-" + generation[:12])
    base, _ = runtime._layout(root, project)
    location = runtime._resolve_worktree(root, project, base, relative)
    ref = development._published_ref(checkout, configuration["publish_remote"], branch, repo)
    if development._remote_head(checkout, configuration["publish_url"], ref):
        raise ProjectError("new development generation must use an unpublished branch")
    values = {"project-identity": development._identity(project, item), "project-base-commit": start,
              "project-configuration": json.dumps(configuration, sort_keys=True),
              "remote": configuration["publish_remote"], "merge": ref}
    local = development._git(checkout, "show-ref", "--verify", "refs/heads/" + branch, check=False).returncode == 0
    if local and development._config(checkout, "branch." + branch + ".project-identity") != values["project-identity"]:
        raise ProjectError("existing generation branch has no matching project identity")
    for key, value in values.items():
        old = development._config(checkout, "branch." + branch + "." + key)
        if old is not None and old != value:
            raise ProjectError("generation branch configuration differs from its intent")
        development._git(checkout, "config", "branch." + branch + "." + key, value)
    if not local:
        if location.exists():
            raise ProjectError("generation worktree path is already occupied")
        location.parent.mkdir(parents=True, exist_ok=True)
        development._git(checkout, "worktree", "add", "-b", branch, str(location), start)
    elif not location.exists():
        if development._text(checkout, "rev-parse", branch) != start:
            raise ProjectError("retained generation branch moved before worktree creation")
        location.parent.mkdir(parents=True, exist_ok=True)
        development._git(checkout, "worktree", "add", str(location), branch)
    if (not location.is_dir() or development._text(location, "symbolic-ref", "--short", "HEAD") != branch or
            development._text(location, "rev-parse", "HEAD") != start):
        raise ProjectError("generation worktree differs from its initial intent")
    if development._text(location, "rev-parse", "--path-format=absolute", "--git-common-dir") != development._text(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir"):
        raise ProjectError("generation worktree belongs to another Git repository")
    descriptor = {"repository": item["repository"], "branch": branch, "worktree": relative.as_posix(),
                  "base_commit": start, "publish_ref": ref, "branch_published": False, **configuration}
    descriptor["host"] = socket.gethostname()
    _switch_reservation(root, item, project, descriptor)
    return descriptor


def prepare(root, selector, *, publish=None):
    root, files, item, identity = _item(root, selector)
    _quiescent(root, files, item, identity)
    lifecycle = state(item)
    _policy(item)
    if not lifecycle.get('replacement_pending'):
        return {'status': 'no_op'}
    capacity(item)
    source_item = replacement_item(item)
    if source_item is not item:
        repo = development._repository(item, store.project(files))
        checkout = development._checkout(root, source_item, store.project(files), repo, {})
        checkpoints = [value for value in lifecycle.get('checkpoints', {}).values()
                       if value.get('source_worktree') == item['development']['worktree'] and value['status'] == 'published']
        if not any(development._remote_head(checkout, value['url'], value['ref']) == value['commit'] for value in checkpoints):
            raise ProjectError('cross-host replacement requires its verified preserved source')
    blocks = autonomy._dependency_blocks(root, files, item)
    if blocks:
        raise ProjectError('replacement requires actual accepted prerequisite delivery: ' + ','.join(blocks))
    plan = lifecycle.get('replacement')
    if not plan:
        repo = development._repository(item, store.project(files))
        checkout = development._checkout(root, source_item, store.project(files), repo, {})
        configuration = development._configuration(checkout, repo)
        base = development._base(checkout, configuration, development._identity(store.project(files), item))
        plan = {'generation': secrets.token_hex(16), 'base': base,
                'project_sha256': workflow._hash(files[store.project_path(files)])}
        lifecycle['replacement'] = plan
        result = _save(root, files, item, identity, 'Plan replacement formal baseline ' + item['id'], publish)
        if not _settled(result):
            return result
        root, files, item, identity = _item(root, item['id'])
        lifecycle, plan = state(item), state(item)['replacement']
    if plan['project_sha256'] != workflow._hash(files[store.project_path(files)]):
        raise ProjectError('replacement project configuration changed; preserve its original intent')
    item['development'] = _new_worktree(
        root, files, item, plan['generation'], plan['base'], 'formal')
    workflow._invalidate_implementation(item)
    item['design'].pop('review', None)
    item['status'], item['owner'] = 'in_progress', None
    lifecycle['replacement_pending'] = False
    # A completed intent must not select the same generation on a later replan.
    lifecycle.pop('replacement', None)
    return _save(root, files, item, identity, 'Bind replacement generation ' + item['id'], publish)


def adopt(root, selector, *, worktree, publish=None):
    """Give an already registered legacy source a recoverable disposition record."""
    root, files, item, identity = _item(root, selector)
    _quiescent(root, files, item, identity)
    policy = _policy(item)
    descriptor = _descriptors(item).get(worktree)
    if not descriptor or worktree == (item.get('development') or {}).get('worktree'):
        raise ProjectError('adoption requires an exact registered retained worktree; use replan for current source')
    existing = [value for value in state(item).get('generations', {}).values()
                if value['development']['worktree'] == worktree]
    if existing:
        source_item = dict(item, development=descriptor[0])
        actual = development.snapshot(development.worktree_location(root, source_item, store.project(files)))
        previous = state(item)['checkpoints'][existing[0]['checkpoint']]
        if previous['source'] == actual:
            return {'status': 'no_op', 'generation': existing[0]['id']}
    state(item).setdefault('transition', {}).update(action='adopt', source_worktree=worktree)
    result, checkpoint = _checkpoint(root, files, item, identity, policy['source'], publish, descriptor[0])
    if not _settled(result):
        return result
    root, files, item, identity = _item(root, item['id'])
    lifecycle = state(item)
    key = existing[0]['id'] if existing else checkpoint['id']
    generation = lifecycle.setdefault('generations', {}).setdefault(key, {
        'id': key, 'development': copy.deepcopy(descriptor[0]), 'retired_at': workflow._now(), 'source': policy['source']})
    if generation.get('checkpoint') and generation['checkpoint'] != checkpoint['id']:
        generation.setdefault('superseded_checkpoints', []).append(generation['checkpoint'])
        generation.pop('disposition', None)
    generation['checkpoint'] = checkpoint['id']
    lifecycle.pop('transition', None)
    result = _save(root, files, item, identity, 'Adopt retained source ' + item['id'], publish)
    return {**result, 'generation': key}


def _checkout(root, files, item, row):
    project = store.project(files)
    repository = development._repository(dict(item, repository=row['repository']), project)
    return development._checkout(root, dict(item, development=None), project, repository, {})


def _inspect(root, files, item, row):
    """Bind physical identity and safety facts; no delete is performed here."""
    if row['kind'] != 'remote-ref' and row.get('host') != socket.gethostname():
        raise ProjectError('local resource is retained on another host')
    if row['kind'] == 'runtime-cache':
        runtime._no_links(root, row['relative_path'])
        path = root / row['relative_path']
        result = dict(row, path=str(path))
        if not path.exists():
            return dict(result, absent=True)
        raise ProjectError('historical runtime cache requires explicit archival verification')
    checkout = _checkout(root, files, item, row)
    result = copy.deepcopy(row)
    common = development._text(checkout, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    if row['kind'] != 'remote-ref' and row.get('common_dir', common) != common:
        raise ProjectError('registered local Git repository changed; preserve its original resource locator')
    result.update(host=socket.gethostname(), common_dir=common)
    if row['kind'] == 'worktree':
        descriptor = row['descriptor']
        candidate = dict(item, development=descriptor, repository=row['repository'])
        path = development.worktree_location(root, candidate, store.project(files))
        result['path'] = str(path)
        if not path.exists():
            result['absent'] = True
            recoveries = [state(item)['checkpoints'][generation['checkpoint']]
                          for generation in state(item).get('generations', {}).values()
                          if generation['development']['worktree'] == descriptor['worktree'] and generation.get('checkpoint')]
            recoveries = [value for value in recoveries if value.get('status') == 'published' and
                          development._remote_head(checkout, value['url'], value['ref']) == value['commit']]
            if not recoveries:
                raise ProjectError('missing worktree requires a verified exact source recovery checkpoint')
            result['oid'] = row.get('oid', recoveries[-1]['head'])
            if result['oid'] != recoveries[-1]['head']:
                raise ProjectError('missing worktree source differs from its recovery checkpoint')
            result['recovery'] = copy.deepcopy(recoveries[-1])
            return result
        configuration = development._configuration(path, development._repository(candidate, store.project(files)))
        development._existing_record(root, candidate, store.project(files), path, configuration)
        actual = development.snapshot(path)
        try:
            from project_removal import _git_state
        except ImportError:
            from .project_removal import _git_state
        git_state = _git_state(path)
        if git_state['in_progress'] or git_state['submodules'] or any(
                row.get('worktree') == str(path) and ('locked' in row or 'prunable' in row) for row in git_state['worktrees']):
            raise ProjectError('retained worktree has unfinished Git state or nested repositories')
        branch = 'refs/heads/' + descriptor['branch']
        if any(value.get('branch') == branch and value.get('worktree') != str(path) for value in git_state['worktrees']):
            raise ProjectError('retained branch is used by another registered worktree')
        # Dirty/index/untracked/ignored data always blocks ordinary worktree removal.
        ignored = development._git(path, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z').stdout
        if not actual['clean'] or ignored:
            raise ProjectError('retained worktree contains user data; preserve/clean it before ordinary removal')
        if descriptor.get('branch_published') is not False:
            raise ProjectError('ordinary development worktree requires separately authorized cleanup')
        recoveries = [value for value in state(item).get('checkpoints', {}).values()
                      if value['status'] == 'published' and value['source'] == actual]
        if not recoveries:
            raise ProjectError('retained worktree has no exact verified source recovery checkpoint')
        recovery = recoveries[-1]
        if development._remote_head(checkout, recovery['url'], recovery['ref']) != recovery['commit']:
            raise ProjectError('source recovery ref is missing or changed')
        result.update(oid=actual['head'], recovery=copy.deepcopy(recovery), snapshot=actual)
    else:
        if not row.get('oid'):
            raise ProjectError('resource publication has not established its expected OID')
        if row['kind'] == 'remote-ref':
            actual = development._remote_head(checkout, row['url'], row['ref'])
        else:
            registered = development._text(checkout, 'worktree', 'list', '--porcelain')
            if 'branch ' + row['ref'] in registered.splitlines():
                raise ProjectError('local ref is checked out; retain its worktree')
            found = development._git(checkout, 'rev-parse', '--verify', row['ref'], check=False)
            actual = found.stdout.decode().strip() if found.returncode == 0 else None
            recovery = _capture(item, row['snapshot'])
            if actual is not None and development._remote_head(checkout, row['url'], recovery['ref']) != row['oid']:
                raise ProjectError('local snapshot ref has no exact verified remote recovery')
        if actual is not None and actual != row['oid']:
            raise ProjectError('resource ref differs from its recorded OID')
        result['absent'] = actual is None
    return result


def plan(root, selector, *, publish=None):
    root, files, item, identity = _item(root, selector)
    _quiescent(root, files, item, identity)
    policy = _policy(item)
    lifecycle = state(item)
    pending = lifecycle.get('gc')
    if pending and pending['state'] != 'completed':
        return _plan_output(root, item, pending)
    now = datetime.now(timezone.utc)
    rows, candidates, blocked = inventory(files, item['id']), [], []
    resources = lifecycle.setdefault('resources', {})
    for row in rows:
        value = copy.deepcopy(row)
        reasons = value.get('retained_by', [])
        if value.get('state') == 'deleted':
            continue
        if reasons:
            value.pop('released_at', None)
            value['state'] = 'live'
        else:
            value.setdefault('released_at', now.isoformat())
            value['state'] = 'released'
            due = _time(value['released_at']) + timedelta(days=policy['grace_days'] if value['kind'] == 'remote-ref' else 0)
            value['eligible_at'] = due.isoformat()
            if now >= due:
                try:
                    physical = _inspect(root, files, item, value)
                    physical['state'] = 'deleting'
                    candidates.append(physical)
                except (ProjectError, OSError, ValueError) as exc:
                    blocked.append({'resource': value['id'], 'reason': str(exc)})
        resources[value['id']] = value
    candidates.sort(key=lambda row: ({'runtime-cache': 0, 'local-ref': 0, 'worktree': 1, 'remote-ref': 2}[row['kind']], row['id']))
    intent = {'id': secrets.token_hex(16), 'state': 'planned' if candidates else 'completed', 'resources': candidates,
              'created_at': now.isoformat(), 'recorded_by': identity['session'], 'blocked': blocked}
    intent['digest'] = _intent_digest(intent)
    lifecycle['gc'] = intent
    for row in candidates:
        # Manifest evidence is immutable; progress must not alias its dictionaries
        # through YAML anchors when the resource's state changes.
        resources[row['id']] = copy.deepcopy(row)
    result = _save(root, files, item, identity, 'Plan exact resource collection ' + item['id'], publish)
    return {**result, **_plan_output(root, item, intent)} if _settled(result) else result


def _intent_digest(intent):
    return workflow._hash(workflow._canonical({key: value for key, value in intent.items() if key not in {'digest', 'state'}}))


def _plan_output(root, item, intent):
    return {'status': 'ready', 'intent': intent['id'], 'digest': intent['digest'],
            'resources': intent['resources'], 'blocked_resources': intent['blocked'],
            'collect_command': _command(root, 'collect', item['id'], '--intent', intent['id'], '--confirm', intent['digest'])}


def collect(root, selector, *, intent, confirm, publish=None):
    root, files, item, identity = _item(root, selector)
    _quiescent(root, files, item, identity)
    _policy(item)
    lifecycle = state(item)
    pending = lifecycle.get('gc') or {}
    if pending.get('id') != intent or pending.get('digest') != confirm:
        raise ProjectError('collection requires the exact program-generated intent and digest')
    if pending['state'] == 'completed':
        return {'status': 'no_op', 'intent': intent}
    # Recheck every candidate against current source-retention requirements.
    live = {row['id'] for row in inventory(files, item['id']) if row.get('retained_by')}
    if any(row['id'] in live for row in pending['resources']):
        raise ProjectError('collection candidate acquired a live reference')
    for row in pending['resources']:
        saved = lifecycle['resources'][row['id']]
        if saved['state'] == 'deleted':
            continue
        if row['host'] != socket.gethostname():
            raise ProjectError('local resource collection requires its recorded host')
        checkout = None
        if row['kind'] != 'runtime-cache':
            checkout = _checkout(root, files, item, row)
            if development._text(checkout, 'rev-parse', '--path-format=absolute', '--git-common-dir') != row['common_dir']:
                raise ProjectError('resource Git repository identity changed')
        try:
            if row['kind'] == 'runtime-cache':
                refreshed = _inspect(root, files, item, row)
                if refreshed['path'] != row['path']:
                    raise ProjectError('runtime cache path changed after collection planning')
                if not refreshed.get('absent'):
                    if refreshed.get('content_sha256') != row.get('content_sha256'):
                        raise ProjectError('runtime cache changed after collection planning')
                    # Remove only the registered file. Concurrent unknown files
                    # make rmdir fail and remain available for manual resolution.
                    directory = os.open(refreshed['path'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try:
                        if set(os.listdir(directory)) != {'manifest.yaml'}:
                            raise ProjectError('runtime cache contains unregistered data')
                        with os.fdopen(os.open('manifest.yaml', os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory), 'rb') as stream:
                            if workflow._hash(stream.read()) != row['content_sha256']:
                                raise ProjectError('runtime cache changed during collection')
                        os.unlink('manifest.yaml', dir_fd=directory)
                        os.rmdir(refreshed['path'])
                    finally:
                        os.close(directory)
            elif row['kind'] == 'remote-ref':
                actual = development._remote_head(checkout, row['url'], row['ref'])
                if actual is not None:
                    if actual != row['oid']:
                        raise ProjectError('remote ref moved; conditional deletion refused')
                    # Exact lease makes deletion conditional on the recorded OID.
                    development._git(checkout, 'push', '--force-with-lease=' + row['ref'] + ':' + row['oid'],
                                     '--', row['url'], ':' + row['ref'])
                if development._remote_head(checkout, row['url'], row['ref']) is not None:
                    raise ProjectError('remote deletion result is uncertain; resume the same collection')
            elif row['kind'] == 'local-ref':
                _inspect(root, files, item, row)
                actual = development._git(checkout, 'rev-parse', '--verify', row['ref'], check=False)
                if actual.returncode == 0:
                    development._git(checkout, 'update-ref', '-d', row['ref'], row['oid'])
            else:
                refreshed = _inspect(root, files, item, row)
                if not refreshed.get('absent'):
                    if refreshed.get('snapshot') != row.get('snapshot') or refreshed['path'] != row['path']:
                        raise ProjectError('worktree changed after collection planning')
                    development._git(checkout, 'worktree', 'remove', row['path'])
                branch = 'refs/heads/' + row['descriptor']['branch']
                if (row['descriptor'].get('branch_published') is False and
                        development._git(checkout, 'rev-parse', '--verify', branch, check=False).returncode == 0):
                    if 'branch ' + branch in development._text(checkout, 'worktree', 'list', '--porcelain').splitlines():
                        raise ProjectError('retained branch is used by another registered worktree')
                    development._git(checkout, 'update-ref', '-d', branch, row['oid'])
            saved.update(state='deleted', deleted_at=workflow._now())
            pending['state'] = 'collecting'
            result = _save(root, files, item, identity, 'Record collected resource ' + row['id'], publish)
            if not _settled(result):
                return result
            root, files, item, identity = _item(root, item['id'])
            lifecycle, pending = state(item), state(item)['gc']
        except (ProjectError, OSError, ValueError) as exc:
            return {'status': 'blocked', 'code': 'resource_collection_pending', 'message': str(exc),
                    'intent': intent, 'continuation_command': _command(root, 'collect', item['id'], '--intent', intent, '--confirm', confirm)}
    pending['state'] = 'completed'
    return _save(root, files, item, identity, 'Complete resource collection ' + item['id'], publish)


def validate(item):
    authors = (item.get('workflow') or {}).get('design_authors', [])
    if not isinstance(authors, list) or any(not runtime._nonempty(value) for value in authors):
        raise ProjectError('design authors must be actual contributing session identities')
    lifecycle = (item.get('workflow') or {}).get('lifecycle')
    if lifecycle is None:
        return
    if not isinstance(lifecycle, dict):
        raise ProjectError('lifecycle must be an object')
    policy = lifecycle.get('policy')
    if policy is not None and (not isinstance(policy, dict) or not policy.get('source') or
            type(policy.get('grace_days')) is not int or policy['grace_days'] < 0 or
            type(policy.get('max_retained')) is not int or policy['max_retained'] < 1 or
            type(policy.get('max_snapshots', 20)) is not int or policy.get('max_snapshots', 20) < 1):
        raise ProjectError('invalid resource lifecycle policy')
    handoff = lifecycle.get('handoff')
    if handoff is not None and (not isinstance(handoff, dict) or any(not runtime._nonempty(handoff.get(key)) for key in ('from', 'to', 'source'))):
        raise ProjectError('invalid coordinator handoff')
    for name in ('resources', 'generations', 'checkpoints'):
        values = lifecycle.get(name, {})
        if not isinstance(values, dict):
            raise ProjectError('lifecycle ' + name + ' must be an object')
        for key, value in values.items():
            if not isinstance(key, str) or not workflow.TICKET.fullmatch(key) or not isinstance(value, dict) or value.get('id') != key:
                raise ProjectError('invalid lifecycle resource identity')
            # Ordinary retained generations have historically included null optional metadata.
            active_fields = {field for field, content in value.items() if content not in (None, {}, [], '')}
            if name == 'generations' and active_fields - {
                    'id', 'development', 'checkpoint', 'retired_at', 'source', 'disposition', 'superseded_checkpoints'}:
                raise ProjectError('unsupported retained generation fields; preserve source before recovery')
            if name == 'resources' and (value.get('kind') not in {'worktree', 'local-ref', 'remote-ref', 'runtime-cache'} or
                    value.get('state') not in {'live', 'released', 'deleting', 'deleted'}):
                raise ProjectError('invalid resource lifecycle state')

    captures = lifecycle.get('checkpoints', {})
    for key, value in lifecycle.get('checkpoints', {}).items():
        if (value.get('kind') != 'preservation-checkpoint' or value.get('item') != item['id'] or
                value.get('status') not in {'planned', 'committed', 'published'} or
                not value.get('authorization_source') or not value.get('url') or
                not value.get('ref', '').startswith('refs/heads/') or
                not value.get('branch', '').startswith('preservation/') or not value['branch'].endswith('/' + key)):
            raise ProjectError('invalid preservation checkpoint evidence')
        for field in ('head', 'tree', 'index_tree') + (('commit',) if value['status'] != 'planned' else ()):
            if not _matches(r'[0-9a-f]{40}|[0-9a-f]{64}', value.get(field)):
                raise ProjectError('invalid preservation Git identity')
        source = value.get('source') or {}
        if (source.get('head') != value['head'] or source.get('tree') != value['tree'] or
                not _matches(r'[0-9a-f]{64}', source.get('dirty_digest')) or
                type(source.get('clean')) is not bool):
            raise ProjectError('invalid preservation source binding')
    for key, value in lifecycle.get('resources', {}).items():
        if value.get('item') != item['id']:
            raise ProjectError('resource belongs to another item')
        if value['kind'] == 'runtime-cache':
            attempt = value.get('attempt')
            relative = '.project-local/autonomy-results/' + str(attempt)
            if not _matches(workflow.TICKET.pattern, attempt) or value.get('relative_path') != relative:
                raise ProjectError('historical runtime cache must name its exact registered path')
            expected = _local_id(item, 'runtime-cache', relative, value.get('host'))
        elif value['kind'] in {'remote-ref', 'local-ref'}:
            captured = captures.get(value.get('snapshot')) if isinstance(value.get('snapshot'), str) else None
            if (not captured or value.get('url') != captured['url'] or value.get('oid') != captured.get('commit') or
                    value.get('repository') != captured['repository']):
                raise ProjectError('resource must name its exact registered snapshot')
            permitted = {captured['ref']} if value['kind'] == 'remote-ref' else {
                'refs/heads/' + captured['branch']}
            if value.get('ref') not in permitted:
                raise ProjectError('resource ref differs from its registered snapshot')
            if value['kind'] == 'remote-ref':
                expected = _id(item['id'], 'remote-ref', [value['url'], value['ref']])
            else:
                identity = captured['branch'] if value['ref'].startswith('refs/heads/') else value['ref']
                expected = _local_id(item, 'local-ref', identity, value.get('host'))
        else:
            descriptor = value.get('descriptor') or {}
            if descriptor.get('worktree') not in _descriptors(item):
                raise ProjectError('worktree resource must name a registered development')
            if runtime._relative_path(descriptor['worktree']) is None:
                raise ProjectError('invalid registered resource path')
            if descriptor != _descriptors(item)[descriptor['worktree']][0]:
                raise ProjectError('resource descriptor differs from its registered development')
            expected = _local_id(item, 'worktree', descriptor['worktree'], value.get('host'))
        if key != expected:
            raise ProjectError('resource ID differs from its exact registered locator')
    gc = lifecycle.get('gc')
    if gc is not None and (not isinstance(gc, dict) or gc.get('state') not in {'planned', 'collecting', 'completed'} or
            not workflow.TICKET.fullmatch(gc.get('id', '')) or gc.get('digest') != _intent_digest(gc) or
            not isinstance(gc.get('resources'), list) or any(value.get('id') not in lifecycle.get('resources', {}) for value in gc['resources'])):
        raise ProjectError('invalid collection intent or changed immutable manifest')
    if gc:
        for row in gc['resources']:
            saved = lifecycle['resources'][row['id']]
            for field in ('id', 'item', 'kind', 'repository', 'ref', 'url', 'oid', 'descriptor', 'host', 'common_dir', 'path', 'recovery', 'snapshot', 'relative_path', 'attempt', 'content_sha256'):
                if row.get(field) != saved.get(field):
                    raise ProjectError('collection target differs from its registered resource')

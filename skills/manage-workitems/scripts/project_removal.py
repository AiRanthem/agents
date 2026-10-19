"""Inspect exact local removal scope; execute only a confirmed unchanged manifest.

The digest guards accidental execution. The caller must separately obtain the
user's authorization for this exact manifest, as required by delete-project.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import uuid

try:
    import project_runtime as runtime
    import project_store as store
    import project_development as development
    import project_lifecycle as lifecycle
except ImportError:  # package entrypoint
    from . import project_runtime as runtime, project_store as store, project_development as development, project_lifecycle as lifecycle

ProjectError = runtime.ProjectError
_git = runtime._git
_text = runtime._git_text


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact_root(path):
    selected = Path(path).absolute()
    root = runtime.find_project(selected)
    if selected != root or selected.resolve() != selected:
        raise ProjectError("removal requires the exact real project Git root")
    return root


def _local(root):
    runtime._no_links(root, ".project-local/removal")
    directory = root / ".project-local/removal"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not directory.is_dir():
        raise ProjectError("removal state must be a directory")
    key = directory / "key"
    if key.is_symlink():
        raise ProjectError("removal key cannot be a symlink")
    try:
        descriptor = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        value = key.read_bytes()
    else:
        value = os.urandom(32)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
    if len(value) != 32:
        raise ProjectError("invalid removal key")
    for path in directory.iterdir():
        if path.name == "key":
            continue
        if path.is_symlink() or not path.is_file() or not re.fullmatch(r"[0-9a-f]{32}\.yaml", path.name):
            raise ProjectError("unaccounted data in removal state: " + str(path))
        record = store.load_yaml(path.read_bytes(), str(path))
        if (not isinstance(record, dict) or not isinstance(record.get("payload"), dict)
                or not hmac.compare_digest(str(record.get("signature", "")), _signed(record["payload"], value))):
            raise ProjectError("removal manifest was modified: " + str(path))
    return directory, value


def _signed(payload, key):
    return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def _inventory(path, excluded=()):
    """Hash all data, including ignored files and empty directories; never follow links."""
    rows = {}
    excluded = set(excluded)
    for directory, dirs, files in os.walk(path, followlinks=False):
        relative = Path(directory).relative_to(path).as_posix()
        dirs[:] = sorted(dirs)
        for name in list(dirs) + sorted(files):
            child = Path(directory) / name
            name = child.relative_to(path).as_posix()
            if name in excluded:
                if child.name in dirs:
                    dirs.remove(child.name)
                continue
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode):
                rows[name] = ["symlink", os.readlink(child)]
                if child.name in dirs:
                    dirs.remove(child.name)
            elif stat.S_ISDIR(info.st_mode):
                rows[name] = ["directory"]
            elif stat.S_ISREG(info.st_mode):
                rows[name] = ["file", stat.S_IMODE(info.st_mode), hashlib.sha256(child.read_bytes()).hexdigest()]
            else:
                rows[name] = ["special", info.st_mode]
    return rows


def _registrations(path):
    records = []
    for entry in _git(path, "worktree", "list", "--porcelain", "-z").stdout.split(b"\0\0"):
        values = {}
        for line in entry.split(b"\0"):
            if line:
                key, _, value = line.decode().partition(" ")
                values[key] = value
        if values:
            records.append(values)
    return records


def _outside_removed(path, name, removed):
    absolute = path / name.rstrip("/")
    return not any(absolute == target or target in absolute.parents or absolute in target.parents
                   for target in map(Path, removed))


def _git_state(path):
    if Path(_text(path, "rev-parse", "--show-toplevel")).resolve() != path:
        raise ProjectError(f"not an exact Git checkout root: {path}")
    gitdir = Path(_text(path, "rev-parse", "--absolute-git-dir")).resolve()
    common = Path(_text(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    progress = []
    for directory in {gitdir, common}:
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD", "rebase-merge",
                     "rebase-apply", "sequencer", "BISECT_START", "index.lock", "HEAD.lock", "shallow", "objects/info/alternates"):
            if (directory / name).exists():
                progress.append(str(directory / name))
    index = gitdir / "index"
    return {"head": _text(path, "rev-parse", "--verify", "HEAD^{commit}"),
            "branch": _text(path, "symbolic-ref", "--quiet", "HEAD", check=False),
            "common": str(common), "gitdir": str(gitdir),
            "status": _git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none").stdout.decode(),
            "ignored": _git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").stdout.decode().split("\0")[:-1],
            "refs": _text(path, "for-each-ref", "--format=%(refname) %(objectname)"),
            "config_sha256": hashlib.sha256(_git(path, "config", "--list", "--show-origin").stdout).hexdigest(),
            "stash": _text(path, "stash", "list", "--format=%H"), "in_progress": progress,
            "submodules": [entry.decode() for entry in _git(path, "ls-files", "--stage", "-z").stdout.split(b"\0")
                           if entry.startswith(b"160000 ")],
            "index": hashlib.sha256(index.read_bytes()).hexdigest() if index.is_file() else None,
            "worktrees": _registrations(path)}


def _recovery(path, url, ref, head):
    if not isinstance(url, str) or not url or not isinstance(ref, str) or not ref.startswith("refs/heads/"):
        raise ProjectError("recoverability requires an exact retained URL and refs/heads/ ref")
    if _git(path, "check-ref-format", ref, check=False).returncode:
        raise ProjectError("invalid retained ref")
    rows = _text(path, "ls-remote", "--refs", "--", url, ref).splitlines()
    if len(rows) != 1 or rows[0].split()[1:] != [ref]:
        raise ProjectError(f"retained remote ref is missing or ambiguous: {ref}")
    remote_head = rows[0].split()[0]
    # Exact fetch only, without changing local refs, FETCH_HEAD, or remote branches.
    _git(path, "-c", "core.hooksPath=/dev/null", "fetch", "--no-tags", "--no-prune",
         "--no-recurse-submodules", "--no-write-fetch-head", "--", url, ref)
    if _git(path, "merge-base", "--is-ancestor", head, remote_head, check=False).returncode:
        raise ProjectError(f"HEAD is not recoverable from retained {ref}")
    if _text(path, "ls-remote", "--refs", "--", url, ref).splitlines() != rows:
        raise ProjectError("retained remote ref changed during inspection")
    return {"url": url, "ref": ref, "head": remote_head}


def _unpublished_refs(path, state, recovery):
    for line in state["refs"].splitlines():
        ref, oid = line.split()
        if not ref.startswith("refs/remotes/") and _git(path, "merge-base", "--is-ancestor", oid,
                                                           recovery["head"], check=False).returncode:
            raise ProjectError("local ref is not recoverable from retained remote ref: " + ref)


def _allowed_local(root, inventory, blocked, project, items, retained):
    """Recognize disposable caches and prove completed journals are recoverable."""
    allowed = {".project-local", ".project-local/index.json", ".project-local/index.lock",
               ".project-local/main-workspace.json", ".project-local/repositories.yaml",
               ".project-local/workflow.key", ".project-local/repos"}
    # known-limit: unknown journal formats require explicit preservation; expand
    # this classifier only with a verified recoverability contract.
    local = root / ".project-local"
    for kind in ("publish", "edits", "identities", "development", "autonomy-results"):
        base = local / kind
        if not base.is_dir() or base.is_symlink():
            continue
        allowed.add(base.relative_to(root).as_posix())
        for entry in base.iterdir():
            name = entry.relative_to(root).as_posix()
            try:
                if entry.is_symlink():
                    continue
                if kind == "publish" and entry.is_dir():
                    if {child.name for child in entry.iterdir()} != {"journal.json", "bundle.json"}:
                        continue
                    runtime._no_links(root, name + "/journal.json")
                    runtime._no_links(root, name + "/bundle.json")
                    record = runtime.read_json(entry / "journal.json")
                    candidate = record.get("candidate")
                    if (record.get("state") != "published" or not retained or not candidate
                            or _git(root, "merge-base", "--is-ancestor", candidate, retained["head"], check=False).returncode):
                        continue
                    bundle = runtime.read_json(entry / "bundle.json")
                    runtime._validate_bundle(bundle)
                    recovered = runtime._tree_files(root, candidate)
                    if any(recovered.get(path) != (value.encode() if value is not None else None)
                           for path, value in bundle["writes"].items()):
                        continue
                    allowed.update({name, name + "/journal.json", name + "/bundle.json"})
                elif kind == "edits" and entry.is_dir():
                    runtime._no_links(root, name + "/manifest.yaml")
                    record = store.load_yaml((entry / "manifest.yaml").read_bytes())
                    signature = record.pop("signature", None)
                    key_path = local / "workflow.key"
                    runtime._no_links(root, ".project-local/workflow.key")
                    if (record.get("state") != "finished" or not isinstance(signature, str)
                            or not hmac.compare_digest(signature, _signed(record, key_path.read_bytes()))):
                        continue
                    expected = {"manifest.yaml", *record.get("draft_hashes", {})}
                    if {child.name for child in entry.iterdir()} != expected:
                        continue
                    if any(child.is_symlink() or not child.is_file() for child in entry.iterdir()):
                        continue
                    if any(hashlib.sha256((entry / path).read_bytes()).hexdigest() != digest
                           for path, digest in record.get("draft_hashes", {}).items()):
                        continue
                    allowed.add(name)
                    allowed.update(name + "/" + path for path in expected)
                elif kind == "identities" and entry.is_file():
                    record = store.load_yaml(entry.read_bytes())
                    if (isinstance(record, dict) and set(record) == {"session", "machine", "token"}
                            and all(isinstance(value, str) and value for value in record.values())
                            and entry.name == hashlib.sha256(record["session"].encode()).hexdigest() + ".yaml"):
                        allowed.add(name)
                elif kind == "development" and entry.is_file():
                    record = store.load_yaml(entry.read_bytes())
                    if not isinstance(record, dict) or set(record) != {"identity", "branch", "worktree", "configuration"}:
                        continue
                    matches = [item for item in items.values() if item.get("development") and
                               development._identity(project, item) == record["identity"]]
                    if (len(matches) == 1 and record["branch"] == matches[0]["development"]["branch"]
                            and record["worktree"] == matches[0]["development"]["worktree"]
                            and entry.name == hashlib.sha256(record["identity"].encode()).hexdigest() + ".yaml"):
                        allowed.add(name)
                elif kind == "autonomy-results" and entry.is_dir():
                    matches = [item for item in items.values() if entry.name in
                               ((item.get("workflow") or {}).get("autonomy") or {}).get("executions", {})]
                    if len(matches) != 1:
                        continue
                    _, resource = lifecycle._resource(matches[0], "runtime-cache", name,
                                                      relative_path=name, attempt=entry.name)
                    lifecycle._inspect(root, {}, matches[0], resource)
                    allowed.update({name, name + "/manifest.yaml"})
            except (ProjectError, OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
    for name, entry in inventory.items():
        if name.startswith(".project-local/") and (name not in allowed or entry[0] in {"symlink", "special"}):
            blocked.append("unaccounted local data or unresolved operation: " + name)


def _inspect(root):
    blocked, resources, preserved = [], [], []
    files = runtime._working_files(root)
    project, items = store.project(files), store.items(files)
    errors = runtime.validate_project(root)
    if errors:
        blocked.extend("invalid project: " + error for error in errors)
    for identifier, item in items.items():
        if item.get("owner"):
            blocked.append("active owner: " + identifier)
        resource_state = (item.get("workflow") or {}).get("lifecycle") or {}
        if resource_state.get("transition") or (resource_state.get("gc") or {}).get("state") in {"planned", "collecting"}:
            blocked.append("unresolved resource lifecycle: " + identifier)
        receipt = store.receipt(files, identifier)
        if receipt and receipt.get("state") != "verified":
            blocked.append("unresolved sync: " + identifier)
    if errors:
        _allowed_local(root, _inventory(root, (".git", ".project-local/removal")),
                       blocked, project, items, None)
        return {"project_id": project.get("id"), "root": str(root),
                "resources": [{"kind": "project", "path": str(root), "action": "blocked"}],
                "preserved": [], "blocked": sorted(set(blocked)),
                "remote_policy": "retain all remote branches and Aone records"}
    main = None
    if project.get("main_workspace"):
        try:
            main = runtime._worktree_base(root, project, "main_workspace")
            entry = {"kind": "main_workspace", "path": str(main),
                     "agents_sha256": hashlib.sha256((main / "AGENTS.md").read_bytes()).hexdigest()}
            top = _git(main, "rev-parse", "--show-toplevel", check=False)
            if not top.returncode and Path(top.stdout.decode().strip()).resolve() == main:
                entry["git"] = _git_state(main)
            preserved.append(entry)
        except ProjectError as exc:
            blocked.append(str(exc))
    state = _git_state(root)
    state["ignored"] = [name for name in state["ignored"] if not name.startswith(".project-local/removal/")]
    root_resource = {"kind": "project", "path": str(root), "action": "remove_directory", "git": state}
    resources.append(root_resource)
    try:
        storage = runtime._storage_config(root)
        recovery = _recovery(root, storage["url"], "refs/heads/" + storage["branch"], state["head"])
        _unpublished_refs(root, state, recovery)
        root_resource["retained"] = recovery
    except ProjectError as exc:
        blocked.append(str(exc))
    targets = {}
    for identifier, item in items.items():
        for descriptor, _ in lifecycle._descriptors(item).values():
            try:
                target = development.worktree_location(root, dict(item, development=descriptor), project)
                if target in targets:
                    raise ProjectError("duplicate worktree ownership: " + str(target))
                targets[target] = (identifier, descriptor)
            except ProjectError as exc:
                blocked.append(str(exc))
    bindings = development._bindings(root)
    repositories = {repo["id"]: repo for repo in project.get("repositories", [])}
    for repository, value in bindings.items():
        path = Path(value)
        if not path.is_absolute() or path.resolve() != path or not path.is_dir():
            blocked.append("invalid or missing local source binding: " + value)
            continue
        runtime._worktree_components(Path(path.anchor), PurePosixPath(*path.parts[1:]))
        if root in path.parents:
            if path != root / ".project-local/repos" / repository or repository not in repositories:
                blocked.append("unrecognized local clone: " + value)
                continue
            targets[path] = (None, None)
        else:
            preserved.append({"kind": "external_source", "path": str(path),
                              "git": _git_state(path)})
    for target, (identifier, recorded) in targets.items():
        resource = {"kind": "item_worktree" if identifier else "local_clone", "item": identifier, "path": str(target)}
        resources.append(resource)
        if not target.exists():
            resource["action"] = "already_absent"
            continue
        try:
            runtime._worktree_components(Path(target.anchor), PurePosixPath(*target.parts[1:]))
            current = _git_state(target)
            resource["git"] = current
            linked = current["gitdir"] != current["common"]
            resource["action"] = "worktree_remove" if linked else "remove_directory"
            if identifier:
                item = items[identifier]
                repo = development._repository(item, project)
                if current["branch"] != "refs/heads/" + recorded["branch"]:
                    raise ProjectError("item worktree branch differs from recorded development")
                development._check_identity(target, recorded["branch"], development._identity(project, item))
                remote = recorded.get("publish_remote") or repo.get("publish_remote") or "origin"
                url = recorded.get("publish_url") or repo.get("publish_url") or repo["url"]
                if development._url(target, remote, push=True) != url:
                    raise ProjectError("item publishing URL differs from recorded repository")
                ref = recorded.get("publish_ref") or development._published_ref(target, remote, recorded["branch"], repo)
            else:
                repo = repositories[target.name]
                url, ref = repo["url"], repo.get("base_ref")
            try:
                recovery = _recovery(target, url, ref, current["head"])
            except ProjectError:
                checkpoints = (lifecycle.state(items[identifier]).get("checkpoints", {}) if identifier else {}).values()
                matches = [value for value in checkpoints if value.get("status") == "published" and
                           _git(target, "merge-base", "--is-ancestor", current["head"], value["commit"], check=False).returncode == 0]
                if not matches:
                    raise
                saved = matches[-1]
                recovery = _recovery(target, saved["url"], saved["ref"], current["head"])
            resource["retained"] = recovery
            if not linked:
                _unpublished_refs(target, current, recovery)
                if len(current["worktrees"]) != 1:
                    raise ProjectError("local clone has other linked worktrees; preserve it before removal")
            else:
                survivors = [Path(row["worktree"]) for row in current["worktrees"]
                             if "worktree" in row and Path(row["worktree"]) not in targets
                             and Path(row["worktree"]) != root and root not in Path(row["worktree"]).parents
                             and "locked" not in row and "prunable" not in row]
                if not survivors:
                    raise ProjectError("linked worktree requires a surviving registered Git repository")
                survivor = survivors[0]
                if not survivor.is_dir() or Path(_text(survivor, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() != Path(current["common"]):
                    raise ProjectError("surviving source repository identity differs")
                resource["survivor"] = str(survivor)
                preserved.append({"kind": "source_repository", "path": str(survivor), "git": _git_state(survivor)})
            resource["inventory"] = _inventory(target, (".git",))
            if current["status"] or current["ignored"]:
                raise ProjectError("code checkout contains staged, unstaged, untracked, or ignored data")
        except (ProjectError, OSError, ValueError) as exc:
            blocked.append(str(target) + ": " + str(exc))
    for row in state["worktrees"]:
        if row.get("worktree") != str(root):
            blocked.append("project management repository has another worktree: " + row.get("worktree", "unknown"))
    excludes = [".git", ".project-local/removal"]
    excludes.extend(str(path.relative_to(root)) for path in targets if root in path.parents)
    inventory = _inventory(root, excludes)
    root_resource["inventory"] = inventory
    _allowed_local(root, inventory, blocked, project, items, root_resource.get("retained"))
    tracked = set(_git(root, "ls-files", "-z").stdout.decode().split("\0")[:-1])
    base, container = runtime._layout(root, project)
    containers = {container.as_posix(), *(parent.as_posix() for parent in container.parents if str(parent) != ".")} if base == "project" else set()
    for name, entry in inventory.items():
        if entry[0] == "symlink" or entry[0] == "special":
            blocked.append("unaccounted link or special file: " + name)
        elif name.startswith(".project-local/") or name == ".project-local" or name in tracked:
            continue
        elif entry[0] == "directory" and (name in containers or any(value.startswith(name + "/") for value in tracked)
                or any(str(target).startswith(str(root / name) + "/") for target in targets)):
            continue
        else:
            blocked.append("unregistered or ignored project data: " + name)
    if state["status"]:
        blocked.append("project has staged, unstaged or untracked data")
    for resource in resources:
        current = resource.get("git", {})
        if current.get("stash"):
            blocked.append("Git stash must be preserved: " + resource["path"])
        if current.get("in_progress"):
            blocked.append("in-progress Git or dependent object storage: " + resource["path"])
        if current.get("submodules"):
            blocked.append("submodule recovery requires explicit preservation: " + resource["path"])
        if any("locked" in row or "prunable" in row for row in current.get("worktrees", [])
               if row.get("worktree") == resource["path"]):
            blocked.append("locked or prunable worktree: " + resource["path"])
    for entry in preserved:
        preserved_path = Path(entry["path"])
        if any(Path(resource["path"]) == preserved_path or Path(resource["path"]) in preserved_path.parents
               for resource in resources if resource.get("action") != "already_absent"):
            blocked.append("removal overlaps preserved resource: " + entry["path"])
    # Unknown reference/checkpoint locations cannot be assigned ownership by their name.
    for identifier, item in items.items():
        for key in set(item) | set(item.get("development") or {}):
            if "worktree" in key or "clone" in key:
                if key == "worktree" and key in (item.get("development") or {}):
                    continue
                blocked.append("unclassified item resource: " + identifier + "." + key)
    for key in project:
        if key != "worktrees" and ("worktree" in key or "clone" in key or "reference" in key):
            blocked.append("unclassified project resource: " + key)
    retained_resources = lifecycle.inventory(files)
    return {"project_id": project["id"], "root": str(root), "resources": resources,
            "retained_resource_registry": {"recovery": root_resource.get("retained"), "resources": retained_resources},
            "preserved": preserved, "blocked": sorted(set(blocked)),
            "remote_policy": "retain all remote branches and Aone records"}


def removal_plan(root):
    root = _exact_root(root)
    directory, key = _local(root)
    with runtime._project_lock(root):
        inspected = _inspect(root)
        identifier = uuid.uuid4().hex
        payload = {"version": 1, "manifest": identifier, **inspected}
        digest = _digest(payload)
        record = {"payload": payload, "digest": digest, "signature": _signed(payload, key)}
        path = directory / (identifier + ".yaml")
        with path.open("x", encoding="utf-8") as stream:
            stream.write(store.dump_yaml(record))
        path.chmod(0o600)
    return {"status": "blocked" if inspected["blocked"] else "awaiting_confirmation",
            "manifest": identifier, "digest": digest, "manifest_path": str(path), **inspected,
            "action": "resolve_blockers_then_create_manifest" if inspected["blocked"] else "obtain_user_confirmation_of_exact_manifest"}


def remove(root, manifest_id, confirm):
    root = _exact_root(root)
    if not isinstance(manifest_id, str) or not re.fullmatch(r"[0-9a-f]{32}", manifest_id):
        raise ProjectError("invalid removal manifest id")
    directory, key = _local(root)
    path = directory / (manifest_id + ".yaml")
    runtime._no_links(root, path.relative_to(root).as_posix())
    record = store.load_yaml(path.read_bytes(), str(path))
    if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
        raise ProjectError("invalid removal manifest")
    payload = record["payload"]
    if not hmac.compare_digest(str(record.get("signature", "")), _signed(payload, key)) or record.get("digest") != _digest(payload):
        raise ProjectError("removal manifest was modified; generate another manifest")
    if payload.get("manifest") != manifest_id or payload.get("root") != str(root) or confirm != record["digest"]:
        raise ProjectError("remove requires --confirm with this exact manifest digest")
    if payload.get("blocked"):
        return {"status": "blocked", "manifest": manifest_id, "blocked": payload["blocked"]}
    removed = []
    with runtime._project_lock(root):
        current = _inspect(root)
        expected = {key: value for key, value in payload.items() if key not in {"manifest", "version"}}
        if current != expected:
            raise ProjectError("removal state changed since confirmation; generate and confirm a new manifest")
        # known-limit: Git and unrelated processes do not share this program's lock.
        # The caller must stop writers; a filesystem snapshot/OS lock is needed to
        # eliminate changes by uncooperative writers after final inspection.
        resources = sorted(current["resources"], key=lambda value: len(Path(value["path"]).parts), reverse=True)
        try:
            for resource in resources:
                target = Path(resource["path"])
                if resource["action"] == "already_absent":
                    continue
                if resource["action"] == "worktree_remove":
                    _git(Path(resource["survivor"]), "-c", "core.hooksPath=/dev/null", "worktree", "remove", "--", str(target))
                else:
                    shutil.rmtree(target)
                if target.exists():
                    raise ProjectError("removed path still exists: " + str(target))
                removed.append(str(target))
            for resource in current["preserved"]:
                preserved_path = Path(resource["path"])
                if not preserved_path.is_dir():
                    raise ProjectError("preserved resource is unavailable: " + resource["path"])
                if "agents_sha256" in resource and hashlib.sha256((preserved_path / "AGENTS.md").read_bytes()).hexdigest() != resource["agents_sha256"]:
                    raise ProjectError("preserved main workspace instructions changed")
                if "git" in resource:
                    before = dict(resource["git"])
                    after = _git_state(preserved_path)
                    before["worktrees"] = [row for row in before["worktrees"] if row.get("worktree") not in removed]
                    # A removed nested checkout naturally changes its containing
                    # repository's ignored/untracked directory entries.
                    for snapshot in (before, after):
                        snapshot["ignored"] = [name for name in snapshot["ignored"]
                                               if _outside_removed(preserved_path, name, removed)]
                        snapshot["status"] = "\0".join(row for row in snapshot["status"].split("\0")
                            if not (row.startswith("?? ") and not _outside_removed(preserved_path, row[3:], removed)))
                    if before != after:
                        raise ProjectError("preserved Git repository changed: " + resource["path"])
            retained = [resource["retained"] for resource in resources if "retained" in resource]
            # Query via a surviving Git repository, or cwd outside the removed root.
            observer = Path(current["preserved"][0]["path"]) if current["preserved"] else root.parent
            for recovery in retained:
                rows = _text(observer, "ls-remote", "--refs", "--", recovery["url"], recovery["ref"]).splitlines()
                if rows != [recovery["head"] + "\t" + recovery["ref"]]:
                    raise ProjectError("retained remote ref changed during removal: " + recovery["ref"])
        except (ProjectError, OSError) as exc:
            return {"status": "partial", "manifest": manifest_id, "removed": removed,
                    "error": str(exc), "action": "inspect_partial_removal_without_broadening_scope"}
    return {"status": "removed", "manifest": manifest_id, "digest": record["digest"],
            "removed": removed, "preserved": current["preserved"], "retained": retained,
            "retained_resource_registry": current["retained_resource_registry"]}

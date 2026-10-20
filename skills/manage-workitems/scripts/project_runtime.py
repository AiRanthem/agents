#!/usr/bin/env python3
"""Validate and publish a small Git-backed project workspace.

This helper owns structural validation and optimistic Git publication. Business
transitions and external reconciliation use the higher-level workflow commands.
"""

import argparse
import contextlib
import fcntl
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import uuid

try:  # Support direct scripts and package-module entrypoints.
    from workitem_ids import allocate_ids, hierarchy_errors
    import project_store as store
except ImportError:  # pragma: no cover - exercised by the module CLI smoke check.
    from .workitem_ids import allocate_ids, hierarchy_errors
    from . import project_store as store


STATUSES = {"new", "in_progress", "developing", "awaiting_delivery", "done", "cancelled"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
HASH = re.compile(r"[0-9a-f]{64}\Z")
LAYOUT_RESERVED = {".git", ".project", ".project-local"}


class ProjectError(Exception):
    """An operation stopped without claiming publication success."""


class ProjectPermissionError(ProjectError):
    """The harness must permit the same locked project operation."""

    def __init__(self, path, error):
        self.path = str(path)
        super().__init__(f"project operation requires write access to {path}: {error}")


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _decode_json(data, label):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_json_object,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeError, ValueError) as exc:
        raise ProjectError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def read_json(path):
    """Read strict UTF-8 JSON, rejecting duplicate keys and non-finite numbers."""
    path = Path(path)
    try:
        return _decode_json(path.read_bytes(), str(path))
    except OSError as exc:
        raise ProjectError(f"cannot read {path}: {exc}") from exc


def _git(root, *args, data=None, env=None, check=True):
    process_env = os.environ.copy()
    # Ambient Git overrides must not redirect this operation to another repository.
    for key in list(process_env):
        if key.startswith("GIT_"):
            process_env.pop(key)
    process_env.update(env or {})
    result = subprocess.run(["git", "-C", str(root), *args], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=process_env)
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise ProjectError(f"git {args[0]} failed: {detail}")
    return result


def _git_text(root, *args, **kwargs):
    return _git(root, *args, **kwargs).stdout.decode("utf-8").strip()


def find_project(path):
    """Recognize the current Git root's marker; never cross a nested Git boundary."""
    start = Path(path).absolute()
    if start.is_symlink():
        raise ProjectError("project commands cannot enter through a symlink")
    if start.is_file():
        start = start.parent
    if not start.is_dir():
        raise ProjectError(f"not a directory: {start}")
    result = _git(start, "rev-parse", "--show-toplevel", check=False)
    if result.returncode:
        raise ProjectError("the current path is not in a project Git workspace")
    root = Path(result.stdout.decode("utf-8").strip()).resolve()
    resolved = start.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ProjectError("path is outside the project Git workspace") from exc
    lexical_root = next((ancestor for ancestor in (start, *start.parents) if ancestor.resolve() == root), None)
    if lexical_root is None or lexical_root.is_symlink():
        raise ProjectError("project commands cannot enter through a symlink alias")
    _no_links(lexical_root, start.relative_to(lexical_root).as_posix())
    if relative.parts and relative.parts[0] in {"worktrees", ".project-local", ".git"}:
        raise ProjectError("project commands are not enabled inside local or code worktrees")
    markers = [root / f".project/project.{extension}" for extension in ("json", "yaml")]
    present = [marker for marker in markers if marker.exists() or marker.is_symlink()]
    if len(present) != 1 or not present[0].is_file() or present[0].is_symlink() or (root / ".project").is_symlink():
        raise ProjectError("the current Git root requires exactly one regular project.json or project.yaml marker")
    # A linked code worktree sharing an outer workspace must not acquire its marker.
    common = Path(_git_text(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    git_dir = Path(_git_text(root, "rev-parse", "--absolute-git-dir"))
    if common.resolve() != git_dir.resolve():
        raise ProjectError("a linked Git worktree is not a project management root")
    return root


def _identifier(value):
    return isinstance(value, str) and bool(IDENTIFIER.fullmatch(value))


def new_ids(root, slugs, parent=None):
    """Read current local metadata only and print-ready candidate IDs; no reservation."""
    root = find_project(root)
    _no_links(root, "workitems")
    directory = root / "workitems"
    if directory.exists() and not directory.is_dir():
        raise ProjectError("workitems must be a directory")
    files = {}
    marker = ".project/project.yaml" if (root / ".project/project.yaml").is_file() else ".project/project.json"
    files[marker] = (root / marker).read_bytes()
    for pattern in ("*/item.json", "*/metadata.yaml"):
        for path in sorted(directory.glob(pattern)):
            name = path.relative_to(root).as_posix()
            _no_links(root, name)
            if not path.is_file():
                raise ProjectError(f"item metadata must be a regular file: {path}")
            files[name] = path.read_bytes()
    try:
        items = store.items(files)
    except store.StoreError as exc:
        raise ProjectError(str(exc)) from exc
    for identifier, metadata in items.items():
        if not _identifier(identifier) or metadata.get("id") != identifier:
            raise ProjectError(f"item metadata id must be safe and match its directory: {identifier}")
    try:
        return allocate_ids(items, slugs, parent)
    except ValueError as exc:
        raise ProjectError(str(exc)) from exc


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _one_of(value, choices):
    return isinstance(value, str) and value in choices


def _relative_path(value):
    if not _nonempty(value) or "\\" in value or "\x00" in value:
        return None
    path = PurePosixPath(value)
    if not path.parts or path.is_absolute() or str(path) != value or any(part in {".", ".."} for part in path.parts):
        return None
    return path


def _layout(root, project):
    """Validate portable layout metadata without inspecting machine bindings."""
    if not isinstance(project, dict):
        raise ProjectError(".project/project.json must be an object")
    main = project.get("main_workspace")
    if "main_workspace" in project:
        if not isinstance(main, dict) or not _identifier(main.get("id")) or not _nonempty(main.get("name")):
            raise ProjectError("project.main_workspace must contain a safe id and nonempty name")
        if "repository" not in main:
            raise ProjectError("project.main_workspace.repository is required (may be null)")
        repository = main["repository"]
        if repository is not None:
            if not isinstance(repository, dict) or not _nonempty(repository.get("url")):
                raise ProjectError("project.main_workspace.repository must be null or contain a nonempty url")
            ref = repository.get("ref")
            if (not _nonempty(ref) or not ref.startswith("refs/") or
                    _git(root, "check-ref-format", ref, check=False).returncode):
                raise ProjectError("project.main_workspace.repository.ref must be a full Git ref")
    layout = project.get("worktrees", {"base": "project", "path": "worktrees"})
    if not isinstance(layout, dict) or not _one_of(layout.get("base"), {"project", "main_workspace"}):
        raise ProjectError("project.worktrees.base must be project or main_workspace")
    path = _relative_path(layout.get("path"))
    if path is None or any(part.lower() in LAYOUT_RESERVED for part in path.parts):
        raise ProjectError("project.worktrees.path must be a normalized relative path outside reserved management/Git directories")
    if layout["base"] == "project" and path.parts[0] != "worktrees":
        raise ProjectError("project worktrees.path must be at or under worktrees/")
    if layout["base"] == "main_workspace" and (main is None or len(path.parts) < 2):
        raise ProjectError("main_workspace worktrees require main_workspace and a dedicated relative subdirectory with at least two components")
    return layout["base"], path


def _worktree_relative(value, container):
    path = _relative_path(value)
    if (path is None or path.parts[:len(container.parts)] != container.parts or
            len(path.parts) <= len(container.parts) or any(part.lower() in LAYOUT_RESERVED for part in path.parts)):
        raise ProjectError(f"development.worktree must be a normalized relative path below {container}/")
    return path


def _worktree_components(base, relative):
    """Inspect directory components only; code repositories may occupy the leaf."""
    cursor = base
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ProjectError(f"development.worktree cannot use symlinks: {cursor}")
        if cursor.exists() and not cursor.is_dir():
            raise ProjectError(f"worktree path component is not a directory: {cursor}")
    return cursor


def _worktree_base(root, project, base):
    if base == "project":
        return root
    binding_path = root / ".project-local/main-workspace.json"
    _no_links(root, ".project-local/main-workspace.json")
    if not binding_path.is_file():
        raise ProjectError("main workspace is not bound; provide .project-local/main-workspace.json with matching id and absolute root")
    binding = read_json(binding_path)
    if not isinstance(binding, dict) or binding.get("id") != project["main_workspace"]["id"]:
        raise ProjectError("main workspace binding id does not match project.main_workspace.id")
    root_value = binding.get("root")
    if not _nonempty(root_value) or not Path(root_value).is_absolute():
        raise ProjectError("main workspace binding root must be an absolute existing directory")
    main = Path(root_value)
    _worktree_components(Path(main.anchor), PurePosixPath(*main.parts[1:]))
    if not main.is_dir():
        raise ProjectError("main workspace binding root must be an absolute existing directory")
    main = main.resolve()
    if main == root or root in main.parents:
        raise ProjectError("main workspace root cannot equal the project or be inside the project")
    agents = main / "AGENTS.md"
    if agents.is_symlink() or not agents.is_file():
        raise ProjectError("main workspace root must contain a regular AGENTS.md")
    repository = project["main_workspace"]["repository"]
    if repository is not None:
        top = _git(main, "rev-parse", "--show-toplevel", check=False)
        if top.returncode or Path(top.stdout.decode().strip()).resolve() != main:
            raise ProjectError("main workspace repository must be rooted at the bound directory")
        urls = set()
        for remote in _git_text(main, "remote").splitlines():
            urls.update(_git_text(main, "remote", "get-url", "--all", remote).splitlines())
            urls.update(_git_text(main, "remote", "get-url", "--push", "--all", remote).splitlines())
        if repository["url"] not in urls:
            raise ProjectError("main workspace repository URL does not match any local effective remote URL")
    return main


def _resolve_worktree(root, project, base, relative):
    if "main_workspace" in project:
        _no_links(root, ".project/main-workspace.md")
        if not (root / ".project/main-workspace.md").is_file():
            raise ProjectError("associated project requires a regular .project/main-workspace.md")
    target = _worktree_components(_worktree_base(root, project, base), relative)
    if base == "main_workspace" and (target == root or root in target.parents):
        raise ProjectError("external worktree path cannot enter the project management directory")
    return target


def worktree_root(root):
    """Resolve the configured code-worktree directory; never create directories."""
    root = find_project(root)
    project = read_project(root)
    base, container = _layout(root, project)
    return _resolve_worktree(root, project, base, container)


def worktree_path(root, item_id):
    """Resolve one recorded worktree only after checking the local base binding."""
    root = find_project(root)
    if not _identifier(item_id):
        raise ProjectError("invalid workitem id")
    project = read_project(root)
    base, container = _layout(root, project)
    files = _working_files(root)
    try:
        item = store.item(files, item_id)
    except store.StoreError as exc:
        raise ProjectError(str(exc)) from exc
    development = item.get("development") if isinstance(item, dict) else None
    if not isinstance(development, dict):
        raise ProjectError(f"workitem {item_id} has no recorded development worktree")
    relative = _worktree_relative(development.get("worktree"), container)
    return _resolve_worktree(root, project, base, relative)


def _managed_path(name):
    """Allow only the approved management formats, never generic file writes."""
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ProjectError(f"invalid management path: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or str(path) != name or any(part in {".", ".."} for part in path.parts):
        raise ProjectError(f"path must be normalized and relative: {name!r}")
    parts = path.parts
    if name == "worktrees/.gitkeep":
        return path
    if any(part.lower() in {".git", ".project-local", "worktrees", ".env", "credentials",
                            "secrets", "id_rsa", "id_ed25519"} for part in parts):
        raise ProjectError(f"reserved or sensitive path: {name}")
    allowed = name in {"AGENTS.md", ".gitignore", ".project/project.json", ".project/project.yaml",
                       ".project/context.md", ".project/workflow.md", ".project/recovery.md",
                       ".project/main-workspace.md", ".project/project-instructions.md", ".project/business-instructions.md",
                       ".project/migration.yaml", ".project/graph.yaml"}
    allowed |= (len(parts) == 3 and parts[:2] in {(".project", "sync"), (".project", "state")}
                and PurePosixPath(parts[2]).suffix in ({".json", ".yaml"} if parts[1] == "sync" else {".yaml"})
                and _identifier(PurePosixPath(parts[2]).stem))
    allowed |= (len(parts) == 3 and parts[:2] == (".project", "history")
                and parts[2].endswith(".md") and _identifier(parts[2][:-3]))
    if len(parts) >= 3 and parts[0] == "workitems" and _identifier(parts[1]):
        allowed |= (len(parts) == 3 and parts[2] in {
            "item.json", "metadata.yaml", "requirement.md", "spec.md", "decisions.md", "decision.md",
            "context.md", "logs.md", "AGENTS.md", "handoff.md"})
        allowed |= (len(parts) >= 4 and parts[2] in {"reviews", "records"} and PurePosixPath(parts[-1]).suffix in ({".md", ".yaml"} if parts[2] == "records" else {".md"})
                    and all(_identifier(part) for part in parts[3:]))
    allowed |= (len(parts) == 2 and parts[0] == "evidence" and
                ((PurePosixPath(parts[1]).suffix in {".json", ".yaml"} and _identifier(PurePosixPath(parts[1]).stem)) or
                 (parts[1].endswith(".md") and _identifier(parts[1][:-3]))))
    if not allowed:
        raise ProjectError(f"not an approved management path: {name}")
    return path


def _no_links(root, name):
    cursor = root
    for part in PurePosixPath(name).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ProjectError(f"symlink path is forbidden: {name}")
        if cursor != root / name and cursor.exists() and not cursor.is_dir():
            raise ProjectError(f"non-directory path component: {name}")
        if cursor != root / name and (cursor / ".git").exists():
            raise ProjectError(f"nested repository is forbidden: {name}")


def _item_for_path(name):
    parts = PurePosixPath(name).parts
    if parts[0] == "workitems":
        return parts[1]
    if len(parts) == 3 and parts[:2] in {(".project", "sync"), (".project", "state")}:
        return PurePosixPath(parts[2]).stem
    return None


def _business_digest(files, item_id):
    prefix = f"workitems/{item_id}/"
    try:
        record = store.item(files, item_id)
    except store.StoreError as exc:
        raise ProjectError(str(exc)) from exc
    digest = hashlib.sha256()
    # Normalize storage-owned machine records, keeping owner outside business state.
    # v1's established digest remains byte-for-byte compatible.
    names = sorted(name for name in files if name.startswith(prefix))
    metadata = store.item_path(files, item_id)
    record.pop("owner", None)
    for name in names:
        content = files[name]
        if name == metadata:
            content = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        digest.update(name.encode() + b"\x00" + content + b"\x00")
    return digest.hexdigest()


def _ignore_errors(files):
    """Ask Git to interpret the prospective .gitignore without global exclusions."""
    if ".gitignore" not in files:
        return [".gitignore is required to ignore worktrees/ and .project-local/"]
    errors = []
    with tempfile.TemporaryDirectory(prefix="project-ignore-") as directory:
        temp = Path(directory)
        (temp / ".gitignore").write_bytes(files[".gitignore"])
        _git(temp, "init", "--quiet", "--template=")
        (temp / "worktrees/__project_code__/nested").mkdir(parents=True)
        (temp / "worktrees/.hidden-code").mkdir()
        (temp / ".project-local").mkdir()

        def ignored(name):
            return _git(temp, "-c", "core.excludesfile=/dev/null", "check-ignore", "--no-index",
                        "--quiet", "--", name, check=False).returncode == 0

        if not ignored(".project-local"):
            errors.append(".gitignore must ignore .project-local/")
        if not ignored("worktrees"):
            # The placeholder layout keeps the parent visible. Require blanket
            # directory coverage, and reject subsequent rules that could reopen
            # an arbitrary code directory. An ignored parent cannot be reopened
            # by negating files within it, so directory checks cover descendants.
            rules = files[".gitignore"].decode("utf-8", "replace").splitlines()
            blankets = {"/worktrees/*", "worktrees/*", "/worktrees/**", "worktrees/**"}
            coverage = [index for index, rule in enumerate(rules) if rule in blankets]
            valid = bool(coverage)
            if coverage:
                for rule in rules[coverage[-1] + 1:]:
                    if not rule.startswith("!") or rule in {"!/worktrees/.gitkeep", "!worktrees/.gitkeep"}:
                        continue
                    pattern = rule[1:].lstrip("/").rstrip("/")
                    # Slash-containing patterns are anchored to the ignore file;
                    # a literal other top-level directory cannot reopen worktrees.
                    first = pattern.split("/", 1)[0]
                    anchored_elsewhere = ("/" in pattern or rule.startswith("!/")) and first != "worktrees" and not any(c in first for c in "*?[")
                    if not anchored_elsewhere:
                        valid = False
            for name in ("worktrees/__project_code__", "worktrees/.hidden-code",
                         "worktrees/__project_code__/nested", "worktrees/__project_code__/nested/code.py"):
                valid = valid and ignored(name)
            if not valid:
                errors.append(".gitignore must ignore worktrees/ code directories recursively, with only .gitkeep exempt")
        if "worktrees/.gitkeep" in files and ignored("worktrees/.gitkeep"):
            errors.append(".gitignore must not ignore the tracked worktrees/.gitkeep placeholder")
    return errors


def _validate_legacy_files(root, files, digest_files=None):
    errors = []

    def need(condition, message):
        if not condition:
            errors.append(message)

    decoded = {}
    for name, data in sorted(files.items()):
        try:
            _managed_path(name)
            if name == "worktrees/.gitkeep" and data != b"":
                raise ProjectError("worktrees/.gitkeep must be a zero-byte placeholder")
            data.decode("utf-8")
            # known-limit: this rejects explicit private-key material, not all secret
            # formats. Review and a dedicated secret scanner must cover other credentials.
            if re.search(br"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----", data):
                raise ProjectError(f"private-key material is forbidden: {name}")
            if name.endswith(".json"):
                decoded[name] = _decode_json(data, name)
        except (ProjectError, UnicodeError) as exc:
            errors.append(str(exc))
    errors.extend(_ignore_errors(files))
    project = decoded.get(".project/project.json")
    if not isinstance(project, dict):
        errors.append(".project/project.json must be an object")
        return errors
    need(type(project.get("schema_version")) is int and project["schema_version"] == 1,
         "project.schema_version must be 1")
    need(_identifier(project.get("id")), "project.id must be a safe nonempty identifier")
    need(_nonempty(project.get("name")), "project.name must be nonempty")
    if "main_workspace" in project:
        need(".project/main-workspace.md" in files, "associated project requires .project/main-workspace.md")
    layout = None
    try:
        layout = _layout(root, project)
    except ProjectError as exc:
        errors.append(str(exc))
    storage = project.get("storage")
    if not isinstance(storage, dict):
        errors.append("project.storage must be an object")
    else:
        for key in ("remote", "branch", "url"):
            need(_nonempty(storage.get(key)), f"project.storage.{key} must be nonempty")
        need(_identifier(storage.get("remote")), "project.storage.remote must be a safe remote name")
        if _nonempty(storage.get("branch")):
            need(_git(root, "check-ref-format", "refs/heads/" + storage["branch"], check=False).returncode == 0,
                 "project.storage.branch must be a valid Git branch")
    backends = project.get("backends")
    if not isinstance(backends, dict) or "aone" not in backends:
        errors.append("project.backends must contain aone (null or configuration)")
    elif backends["aone"] is not None:
        aone = backends["aone"]
        if not isinstance(aone, dict):
            errors.append("project.backends.aone must be null or an object")
        else:
            for key in ("space_id", "type", "category"):
                need(_nonempty(aone.get(key)), f"project.backends.aone.{key} must be nonempty")
            mapping = aone.get("status_map")
            need(isinstance(mapping, dict) and all(key in STATUSES and _nonempty(value)
                                                  for key, value in mapping.items()),
                 "project.backends.aone.status_map must map local statuses to nonempty strings")
    repos = project.get("repositories")
    repo_ids = set()
    if not isinstance(repos, list):
        errors.append("project.repositories must be a list")
    else:
        for repo in repos:
            if not isinstance(repo, dict):
                errors.append("each repository must be an object")
                continue
            identifier = repo.get("id")
            need(_identifier(identifier), "repository.id must be a safe identifier")
            if _identifier(identifier):
                need(identifier not in repo_ids, f"duplicate repository id: {identifier}")
                repo_ids.add(identifier)
            for key in ("url", "base_ref"):
                need(_nonempty(repo.get(key)), f"repository {identifier}: {key} must be nonempty")
            if "publish_remote" in repo:
                need(_nonempty(repo["publish_remote"]), f"repository {identifier}: publish_remote must be nonempty")

    items = {}
    for name, item in decoded.items():
        parts = PurePosixPath(name).parts
        if len(parts) != 3 or parts[0] != "workitems" or parts[2] != "item.json":
            continue
        identifier = parts[1]
        if not isinstance(item, dict):
            errors.append(f"{name}: item must be an object")
            continue
        items[identifier] = item
        prefix = f"item {identifier}: "
        need(item.get("id") == identifier, prefix + "id must match its directory")
        need(_nonempty(item.get("title")), prefix + "title must be nonempty")
        need(_one_of(item.get("kind"), {"development", "aggregate"}), prefix + "invalid kind")
        need(_one_of(item.get("status"), STATUSES), prefix + "invalid status")
        need(type(item.get("archived")) is bool, prefix + "archived must be boolean")
        dependencies = item.get("depends_on")
        need(isinstance(dependencies, list) and all(_identifier(value) for value in dependencies),
             prefix + "depends_on must be a list of identifiers")
        if isinstance(dependencies, list) and all(_identifier(value) for value in dependencies):
            need(len(dependencies) == len(set(dependencies)), prefix + "duplicate dependencies")
        for key in ("split_from", "repository", "owner", "development"):
            need(key in item, prefix + f"{key} is required (may be null)")
        split = item.get("split_from")
        need(split is None or _identifier(split), prefix + "split_from must be null or an identifier")
        repository = item.get("repository")
        need(repository is None or (_identifier(repository) and repository in repo_ids),
             prefix + "repository must be null or one configured repository id")
        owner = item.get("owner")
        need(owner is None or (isinstance(owner, dict) and all(_nonempty(owner.get(key))
                                                             for key in ("machine", "session", "token"))),
             prefix + "owner must be null or contain machine/session/token")
        development = item.get("development")
        if development is not None:
            if not isinstance(development, dict):
                errors.append(prefix + "development must be null or an object")
            else:
                for key in ("worktree", "branch", "base_commit"):
                    need(_nonempty(development.get(key)), prefix + f"development.{key} must be nonempty")
                worktree = development.get("worktree")
                if _nonempty(worktree) and layout is not None:
                    try:
                        base, container = layout
                        relative = _worktree_relative(worktree, container)
                        if base == "project":
                            _worktree_components(root, relative)
                    except ProjectError as exc:
                        errors.append(prefix + str(exc))
                if _nonempty(development.get("branch")):
                    need(_git(root, "check-ref-format", "refs/heads/" + development["branch"], check=False).returncode == 0,
                         prefix + "development.branch must be a valid Git branch")
                need(isinstance(development.get("base_commit"), str) and
                     bool(re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", development["base_commit"])),
                     prefix + "development.base_commit must be a full Git object id")
            need(item.get("kind") == "development" and repository is not None,
                 prefix + "development requires development kind and one repository")
        if item.get("kind") == "aggregate":
            need(repository is None and development is None,
                 prefix + "aggregate cannot own a code repository or worktree")
        if item.get("status") == "developing":
            need(item.get("kind") == "development" and repository is not None and
                 isinstance(development, dict) and isinstance(owner, dict),
                 prefix + "developing requires repository, development and owner")
        delivery = item.get("delivery")
        if not isinstance(delivery, dict):
            errors.append(prefix + "delivery must be an object")
        else:
            required = delivery.get("required")
            evidence = delivery.get("evidence")
            need(isinstance(required, list) and bool(required) and all(_nonempty(value) for value in required),
                 prefix + "delivery.required must be a nonempty list of strings")
            need(_one_of(delivery.get("status"), {"pending", "delivered"}), prefix + "invalid delivery.status")
            need(isinstance(evidence, list) and all(isinstance(value, dict) and
                 _nonempty(value.get("kind")) and _nonempty(value.get("reference")) for value in evidence),
                 prefix + "delivery.evidence must contain kind/reference records")
            if item.get("status") == "done":
                need(delivery.get("status") == "delivered", prefix + "done requires delivered status")
            if delivery.get("status") == "delivered":
                need(item.get("status") == "done", prefix + "delivered requires done status; create a separate fix item")
                if isinstance(required, list) and isinstance(evidence, list):
                    kinds = {record.get("kind") for record in evidence if isinstance(record, dict)
                             and isinstance(record.get("kind"), str)}
                    need(all(value in kinds for value in required if isinstance(value, str)),
                         prefix + "delivered requires evidence for every delivery.required kind")
        need(_one_of(item.get("cleanup"), {"pending", "done", "not_applicable"}), prefix + "invalid cleanup")

    for name in files:
        parts = PurePosixPath(name).parts
        if parts[0] == "workitems" and len(parts) > 1:
            need(parts[1] in items, f"{name}: missing item.json")
    errors.extend(hierarchy_errors(items))
    graph = {}
    for identifier, item in items.items():
        dependencies = item.get("depends_on")
        graph[identifier] = [value for value in dependencies if _identifier(value)] if isinstance(dependencies, list) else []
        for dependency in graph[identifier]:
            need(dependency in items, f"item {identifier}: dangling dependency {dependency}")
            if item.get("kind") == "aggregate" and item.get("status") == "done" and dependency in items:
                child = items[dependency]
                child_delivery = child.get("delivery")
                need(child.get("status") != "cancelled" and isinstance(child_delivery, dict)
                     and child_delivery.get("status") == "delivered",
                     f"item {identifier}: done aggregate requires delivered, non-cancelled dependency {dependency}")
        split = item.get("split_from")
        if split is not None and _identifier(split):
            need(split in items and split != identifier, f"item {identifier}: invalid split_from {split}")
    # Iterative DFS avoids recursion limits on a large but otherwise valid DAG.
    visited, active = set(), set()
    for origin in graph:
        if origin in visited:
            continue
        stack = [(origin, False)]
        while stack:
            node, exiting = stack.pop()
            if exiting:
                active.discard(node)
                visited.add(node)
            elif node in active:
                errors.append(f"dependency cycle involving {node}")
            elif node not in visited:
                active.add(node)
                stack.append((node, True))
                stack.extend((neighbor, False) for neighbor in reversed(graph.get(node, [])))

    for name, receipt in decoded.items():
        parts = PurePosixPath(name).parts
        if len(parts) != 3 or parts[:2] != (".project", "sync"):
            continue
        identifier = PurePosixPath(parts[2]).stem
        prefix = f"{name}: "
        need(identifier in items, prefix + "receipt must refer to an existing workitem")
        if not isinstance(receipt, dict):
            errors.append(prefix + "receipt must be an object")
            continue
        need(_nonempty(receipt.get("intent_id")), prefix + "intent_id must be nonempty")
        need(isinstance(receipt.get("content_sha256"), str) and bool(HASH.fullmatch(receipt["content_sha256"])),
             prefix + "content_sha256 must be a lowercase SHA256 digest")
        need(_one_of(receipt.get("state"), {"pending", "unknown", "verified"}), prefix + "invalid state")
        for key in ("external_id", "baseline_fields", "git_source_commit", "checked_at"):
            need(key in receipt, prefix + f"{key} is required (may be null)")
            value = receipt.get(key)
            expected_type = dict if key == "baseline_fields" else str
            need(value is None or isinstance(value, expected_type), prefix + f"invalid {key} type")
            if receipt.get("state") == "verified":
                need(isinstance(value, expected_type) and bool(value), prefix + f"verified requires nonempty {key}")
        if receipt.get("state") == "verified" and identifier in items:
            try:
                need(receipt.get("content_sha256") == _business_digest(digest_files if digest_files is not None else files, identifier),
                     prefix + "verified receipt must match the current item business digest")
            except ProjectError as exc:
                errors.append(str(exc))

    for name in files:
        if name.startswith("evidence/") and name.endswith(".md"):
            need(name[:-3] + ".json" in decoded, f"{name}: evidence body requires same-id JSON metadata")
    for name, card in decoded.items():
        if not name.startswith("evidence/"):
            continue
        identifier = PurePosixPath(name).stem
        prefix = f"{name}: "
        if not isinstance(card, dict):
            errors.append(prefix + "evidence metadata must be an object")
            continue
        need(card.get("id") == identifier, prefix + "id must match filename")
        need(_identifier(card.get("repository")) and card["repository"] in repo_ids,
             prefix + "repository must be configured")
        for key in ("topic", "summary", "scope"):
            need(_nonempty(card.get(key)), prefix + key + " must be nonempty")
        need(_one_of(card.get("kind"), {"fact", "inference", "search", "verification"}), prefix + "invalid kind")
        need(isinstance(card.get("inputs"), dict), prefix + "inputs must be an object")
        body = card.get("body")
        need(body == f"evidence/{identifier}.md" and body in files,
             prefix + "body must reference the same-id Markdown file")
        sources = card.get("sources")
        need(isinstance(sources, list) and all(isinstance(source, dict) and _nonempty(source.get("path"))
                                             for source in sources), prefix + "sources must contain path records")
        if isinstance(sources, list):
            for source in sources:
                if not isinstance(source, dict):
                    continue
                for key in ("revision", "sha256"):
                    if key in source:
                        need(_nonempty(source[key]), prefix + f"source.{key} must be nonempty")
                if "sha256" in source:
                    need(isinstance(source["sha256"], str) and bool(HASH.fullmatch(source["sha256"])),
                         prefix + "source.sha256 must be a SHA256 digest")
    return errors


def _validate_files(root, files):
    """Validate one physical authority before reusing the established field checks."""
    try:
        legacy = store.as_legacy(files)
        errors = _validate_legacy_files(root, legacy, digest_files=files)
        if not store.is_v2(files):
            return errors + _fix_errors(store.items(files))
        marker = store.project(files)
        if type(marker.get("schema_version")) is not int or marker["schema_version"] != 2:
            errors.append("project.schema_version must be 2")
        records = store.items(files)
        if ".project/graph.yaml" in files:
            graph = store.load_yaml(files[".project/graph.yaml"], ".project/graph.yaml")
            if not isinstance(graph, dict) or set(graph) != {"revision"} or type(graph.get("revision")) is not int or graph["revision"] < 0:
                errors.append(".project/graph.yaml must contain only a nonnegative integer revision")
        for name, data in files.items():
            _managed_path(name)
            if name.endswith(".yaml"):
                store.load_yaml(data, name)
            if name.startswith(".project/state/") and PurePosixPath(name).stem not in records:
                errors.append(name + ": state must refer to an existing workitem")
        for identifier, record in records.items():
            prefix = f"item {identifier}: "
            design = record.get("design")
            if not (isinstance(design, dict) and design.get("file") == "spec.md" and
                    type(design.get("version")) is int and design["version"] >= 0 and
                    design.get("state") in {"draft", "review-pending", "implementable"}):
                errors.append(prefix + "design requires file spec.md, nonnegative integer version and draft/review-pending/implementable state")
            try:
                try:
                    from project_autonomy import validate_state
                except ImportError:
                    from .project_autonomy import validate_state
                validate_state(record)
            except ProjectError as exc:
                errors.append(prefix + str(exc))
            documents = record.get("documents")
            if not isinstance(documents, dict) or any(not _identifier(key) or not isinstance(value, str) or
                    len(PurePosixPath(value).parts) != 1 or value not in {
                        "requirement.md", "spec.md", "decision.md", "decisions.md", "context.md", "logs.md", "AGENTS.md", "handoff.md"}
                    for key, value in documents.items()):
                errors.append(prefix + "documents must map safe names to approved item Markdown documents")
            spec_name = f"workitems/{identifier}/spec.md"
            if isinstance(design, dict):
                if spec_name in files and (type(design.get("version")) is not int or design["version"] < 1):
                    errors.append(prefix + "an existing design requires version >= 1")
                if spec_name not in files and (design.get("version") != 0 or design.get("state") != "draft"):
                    errors.append(prefix + "an absent design requires version 0 and draft state")
        errors.extend(_fix_errors(records))
        return errors
    except (store.StoreError, ProjectError, UnicodeError) as exc:
        return [str(exc)]


def _fix_errors(records):
    errors, graph = [], {}
    for identifier, record in records.items():
        target = record.get("fixes")
        if target is None:
            continue
        if not _identifier(target) or target not in records:
            errors.append(f"item {identifier}: fixes must identify an existing delivered item")
            continue
        graph[identifier] = target
        if records[target].get("status") != "done" or records[target].get("delivery", {}).get("status") != "delivered":
            errors.append(f"item {identifier}: fixes target {target} must be delivered")
    for origin in graph:
        seen, node = set(), origin
        while node in graph:
            if node in seen:
                errors.append(f"fix relationship cycle involving {node}")
                break
            seen.add(node)
            node = graph[node]
    return errors


def read_project(root):
    """Read either physical project marker without inventing a second authority."""
    root = Path(root)
    files = {}
    for name in (".project/project.json", ".project/project.yaml"):
        _no_links(root, name)
        if (root / name).is_file():
            files[name] = (root / name).read_bytes()
    try:
        return store.project(files)
    except store.StoreError as exc:
        raise ProjectError(str(exc)) from exc


def _working_files(root, paths=("AGENTS.md", ".gitignore", ".project", "workitems", "evidence", "worktrees/.gitkeep")):
    files = {}
    for name in paths:
        _no_links(root, name)
        base = root / name
        if base.is_symlink():
            raise ProjectError(f"symlink path is forbidden: {name}")
        if base.is_file():
            files[name] = base.read_bytes()
        elif name == "worktrees/.gitkeep" and base.exists():
            raise ProjectError("worktrees/.gitkeep must be a regular zero-byte placeholder")
        elif base.is_dir():
            for directory, dirs, names in os.walk(base, followlinks=False):
                for leaf in dirs + names:
                    path = Path(directory) / leaf
                    relative = path.relative_to(root).as_posix()
                    if path.is_symlink():
                        raise ProjectError(f"symlink path is forbidden: {relative}")
                    if leaf == ".git":
                        raise ProjectError(f"nested repository is forbidden: {relative}")
                for leaf in names:
                    path = Path(directory) / leaf
                    relative = path.relative_to(root).as_posix()
                    _managed_path(relative)
                    if not path.is_file():
                        raise ProjectError(f"non-regular management file: {relative}")
                    files[relative] = path.read_bytes()
    return files


def _tree_files(root, revision):
    entries = []
    for entry in _git(root, "ls-tree", "-r", "-z", revision).stdout.split(b"\x00"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode("ascii").split()
        try:
            name = raw_name.decode("utf-8")
        except UnicodeError as exc:
            raise ProjectError("tracked paths must be UTF-8") from exc
        _managed_path(name)
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ProjectError(f"tracked symlinks or nested repositories are forbidden: {name}")
        entries.append((name, object_id))
    if not entries:
        return {}
    # One process reads the complete snapshot. Per-file cat-file processes made
    # every pre/post-publication check grow with the number of project documents.
    data = _git(root, "cat-file", "--batch",
                data="".join(oid + "\n" for _, oid in entries).encode("ascii")).stdout
    result, offset = {}, 0
    for name, expected in entries:
        end = data.find(b"\n", offset)
        header = data[offset:end].split() if end >= 0 else []
        if len(header) != 3 or header[0] != expected.encode("ascii") or header[1] != b"blob":
            raise ProjectError("invalid Git batch object header")
        try:
            size = int(header[2])
        except ValueError as exc:
            raise ProjectError("invalid Git batch object size") from exc
        start, offset = end + 1, end + 1 + size
        if size < 0 or data[offset:offset + 1] != b"\n":
            raise ProjectError("truncated Git batch object")
        result[name] = data[start:offset]
        offset += 1
    if offset != len(data):
        raise ProjectError("unexpected trailing Git batch data")
    return result


def _check_tracked_paths(root):
    # The index exists before the first commit too, so initialization can validate
    # its staged metadata without inventing a temporary bootstrap commit.
    for entry in _git(root, "ls-files", "--stage", "-z").stdout.split(b"\x00"):
        if not entry:
            continue
        metadata, raw_name = entry.split(b"\t", 1)
        mode, _, stage = metadata.decode("ascii").split()
        try:
            name = raw_name.decode("utf-8")
        except UnicodeError as exc:
            raise ProjectError("tracked paths must be UTF-8") from exc
        _managed_path(name)
        if stage != "0" or mode not in {"100644", "100755"}:
            raise ProjectError(f"tracked links, nested repositories or unresolved index entries: {name}")


def validate_project(root):
    """Return structural errors for the management files; never read code worktrees."""
    try:
        root = find_project(root)
        _check_tracked_paths(root)
        return _validate_files(root, _working_files(root))
    except (ProjectError, store.StoreError, OSError) as exc:
        return [str(exc)]


def item_digest(root, item_id):
    """Hash sorted workspace-relative paths and content, excluding owner and receipts.

    Machine records omit owner and use sorted-key compact UTF-8 JSON. V2 state
    is expanded into metadata before hashing. Other files retain original bytes.
    Each record is path + NUL + content + NUL; receipts are excluded.
    """
    root = find_project(root)
    if not _identifier(item_id):
        raise ProjectError("invalid workitem id")
    prefix = f"workitems/{item_id}/"
    files = _working_files(root)
    _no_links(root, store.item_path(files, item_id))
    return _business_digest(files, item_id)


def _clean_root(root):
    git_dir = Path(_git_text(root, "rev-parse", "--absolute-git-dir"))
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        if (git_dir / name).exists():
            raise ProjectError(f"unfinished Git operation: {name}; resolve it before publishing")
    result = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching")
    # No management file may hide behind an ignore rule. Only local data and code
    # worktrees are excluded from the management repository's cleanliness gate.
    records = result.stdout.split(b"\x00")
    for record in records:
        if not record:
            continue
        status, name = record[:2], record[3:].decode("utf-8", "replace")
        if status == b"!!" and (name.startswith("worktrees/") or name.startswith(".project-local/")):
            continue
        raise ProjectError(f"management root is dirty ({name}); do not stash, reset or mix changes")
    return _git_text(root, "rev-parse", "HEAD")


@contextlib.contextmanager
def _project_lock(root):
    common = Path(_git_text(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    lock = common / "project-publish.lock"
    if lock.is_symlink():
        raise ProjectError("publication lock cannot be a symlink")
    try:
        handle = lock.open("a+b")
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EPERM, errno.EROFS}:
            raise ProjectPermissionError(lock, error) from error
        raise
    with handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _validate_bundle(bundle):
    if not isinstance(bundle, dict):
        raise ProjectError("bundle must be an object")
    for key in ("message", "session"):
        if not _nonempty(bundle.get(key)):
            raise ProjectError(f"bundle.{key} must be nonempty")
    if "token" not in bundle or (bundle["token"] is not None and not _nonempty(bundle["token"])):
        raise ProjectError("bundle.token must be null or a nonempty string")
    checks, writes = bundle.get("checks"), bundle.get("writes")
    if not isinstance(checks, dict) or not isinstance(writes, dict) or not writes:
        raise ProjectError("bundle checks/writes must be objects, with at least one write")
    for name, expected in checks.items():
        _managed_path(name)
        if expected is not None and (not isinstance(expected, str) or not HASH.fullmatch(expected)):
            raise ProjectError(f"check {name}: expected null or lowercase raw-byte SHA256")
    for name, value in writes.items():
        _managed_path(name)
        if name not in checks:
            raise ProjectError(f"write has no byte check: {name}")
        if value is None:
            continue
        if not isinstance(value, str):
            raise ProjectError(f"write must contain UTF-8 text or null deletion: {name}")
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise ProjectError(f"write is not valid UTF-8 text: {name}") from exc


def _check_owners(bundle, current, prospective):
    try:
        import project_ownership
    except ImportError:
        from . import project_ownership
    transfer = None
    if "ownership_transfer" in bundle:
        transfer = project_ownership.validate_transfer(bundle, current, prospective)
    touched = {identifier for name in bundle["writes"] if (identifier := _item_for_path(name)) is not None}
    for identifier in touched:
        for snapshot in (current, prospective):
            name = store.item_path(snapshot, identifier)
            if name not in bundle["checks"]:
                raise ProjectError(f"item write must check {name}")
            if store.is_v2(snapshot):
                state_name = f".project/state/{identifier}.yaml"
                if state_name not in bundle["checks"]:
                    raise ProjectError(f"item write must check {state_name}")
        try:
            old = store.item(current, identifier) if store.item_path(current, identifier) in current else {}
            new = store.item(prospective, identifier) if store.item_path(prospective, identifier) in prospective else {}
        except store.StoreError as exc:
            raise ProjectError(str(exc)) from exc
        if not new:
            raise ProjectError(f"workitem deletion is forbidden: {identifier}")
        if store.is_v2(current):
            claim = project_ownership.claim_token(old)
            authorized = project_ownership.authorized(old, {"session": bundle["session"], "token": bundle["token"]})
            if ((claim is not None and claim != bundle["token"]) or not authorized) and transfer != identifier:
                raise ProjectError(f"item {identifier} has another control claim; use explicit takeover")
            if project_ownership.claim_token(new) not in {None, bundle["token"]}:
                raise ProjectError(f"item {identifier}: new control claim must match the publication token")
        owner = old.get("owner")
        if owner is not None:
            matching = (isinstance(owner, dict) and owner.get("token") == bundle["token"] and
                        (store.is_v2(current) or owner.get("session") == bundle["session"]))
            if not matching and transfer != identifier:
                if not store.is_v2(current):
                    raise ProjectError(f"item {identifier} is owned by another session/token; migrate before takeover")
                raise ProjectError(f"item {identifier} has another control claim; use explicit takeover")
        new_owner = new.get("owner")
        if new_owner is not None:
            unchanged_claim = store.is_v2(current) and new_owner == owner
            if (not isinstance(new_owner, dict) or new_owner.get("token") != bundle["token"] or
                    not unchanged_claim and new_owner.get("session") != bundle["session"]):
                raise ProjectError(f"item {identifier}: claim owner.session/token must match bundle.session/token; release before handoff")
        if old.get("delivery", {}).get("status") == "delivered" and (
                new.get("status") != "done" or new.get("delivery", {}).get("status") != "delivered"):
            raise ProjectError(f"item {identifier}: delivered items cannot reopen; create a separate fix item")


def _check_deletions(bundle, current, prospective):
    """Deletion is limited to explicit format migration and replaceable documents/state."""
    for name, value in bundle["writes"].items():
        if value is not None:
            continue
        if name not in current:
            raise ProjectError(f"cannot delete missing management file: {name}")
        replacement = None
        if name == ".project/project.json":
            replacement = ".project/project.yaml"
        elif re.fullmatch(r"workitems/[^/]+/item.json", name):
            replacement = name[:-9] + "metadata.yaml"
        elif name.startswith(".project/sync/") and name.endswith(".json"):
            replacement = name[:-5] + ".yaml"
        elif name.startswith("evidence/") and name.endswith(".json"):
            replacement = name[:-5] + ".yaml"
        if replacement:
            if not store.is_v2(prospective) or replacement not in bundle["writes"] or replacement not in prospective:
                raise ProjectError(f"migration deletion requires same-record YAML replacement: {name}")
        elif name == ".project/project.yaml" or name.endswith("/metadata.yaml") or name in {"AGENTS.md", ".gitignore", ".project/graph.yaml", ".project/migration.yaml"}:
            raise ProjectError(f"authority deletion is forbidden: {name}")
        elif name.startswith(".project/state/"):
            identifier = PurePosixPath(name).stem
            if store.item_path(prospective, identifier) not in prospective:
                raise ProjectError(f"state deletion requires retained workitem: {name}")
        elif name.startswith("evidence/") and name.endswith((".yaml", ".md")):
            base = str(PurePosixPath(name).with_suffix(""))
            pair = (base + ".yaml", base + ".md")
            if (not store.is_v2(current) or any(path not in current or path in prospective or
                    path not in bundle["writes"] or bundle["writes"][path] is not None or
                    path not in bundle["checks"] for path in pair)):
                raise ProjectError(f"knowledge retirement requires explicit guarded YAML/Markdown pair deletion: {name}")
        elif name.endswith(".yaml") and name.startswith(("evidence/", ".project/sync/")):
            raise ProjectError(f"evidence/receipt authority deletion is forbidden: {name}")


def _write_journal(path, state):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        os.chmod(temporary, 0o600)
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _fetch_selected(root, remote, branch):
    _git(root, "fetch", "--no-tags", "--no-prune", "--no-recurse-submodules", remote, "refs/heads/" + branch)
    return _git_text(root, "rev-parse", "FETCH_HEAD")


def _storage_config(root):
    """Check both configured and effective destinations before any network call."""
    storage = read_project(root)["storage"]
    remote, url = storage["remote"], storage["url"]
    urls = _git_text(root, "config", "--get-all", f"remote.{remote}.url").splitlines()
    push_urls = _git_text(root, "config", "--get-all", f"remote.{remote}.pushurl", check=False).splitlines()
    fetch_destinations = _git_text(root, "remote", "get-url", "--all", remote).splitlines()
    push_destinations = _git_text(root, "remote", "get-url", "--push", "--all", remote).splitlines()
    if urls != [url] or (push_urls and push_urls != [url]) or fetch_destinations != [url] or push_destinations != [url]:
        raise ProjectError("configured remote URL/push URL differs from project.storage.url")
    return storage


def refresh_project(root):
    """Fast-forward a clean management checkout from its exact authority."""
    root = find_project(root)
    with _project_lock(root):
        original = _clean_root(root)
        errors = validate_project(root)
        if errors:
            raise ProjectError("invalid current workspace:\n" + "\n".join(errors))
        storage = _storage_config(root)
        revision = _fetch_selected(root, storage["remote"], storage["branch"])
        if _git(root, "merge-base", "--is-ancestor", original, revision, check=False).returncode:
            raise ProjectError("root HEAD has unpublished/divergent commits; refresh cannot discard them")
        files = _tree_files(root, revision)
        marker = store.project(files)
        if not isinstance(marker, dict) or marker.get("storage") != storage:
            raise ProjectError("authoritative storage configuration changed")
        errors = _validate_files(root, files)
        if errors:
            raise ProjectError("invalid remote workspace:\n" + "\n".join(errors))
        if _clean_root(root) != original:
            raise ProjectError("local checkout changed while refreshing")
        if revision != original:
            _git(root, "-c", "core.hooksPath=/dev/null", "merge", "--ff-only", "--no-edit", revision)
        if _clean_root(root) != revision:
            raise ProjectError("refresh did not produce the expected clean checkout")
        return {"commit": revision, "changed": revision != original}


def _verify_publication(root, remote, branch, commit, bundle, storage):
    """Observe the remote ref, including races or post-receive ref changes."""
    # known-limit: this is a remote-state observation, not a server-enforced lease.
    # A later operation must refresh its item owner/guards; a hosted CAS service
    # would be needed to prevent direct Git writers from changing ownership later.
    verified = _fetch_selected(root, remote, branch)
    if _git(root, "merge-base", "--is-ancestor", commit, verified, check=False).returncode:
        raise ProjectError("remote verification failed: candidate is not contained in the selected remote ref")
    files = _tree_files(root, verified)
    for name, value in bundle["writes"].items():
        if files.get(name) != (value.encode("utf-8") if value is not None else None):
            raise ProjectError(f"remote verification failed: intended state changed for {name}")
    for name, expected in bundle["checks"].items():
        if name in bundle["writes"]:
            continue
        actual = hashlib.sha256(files[name]).hexdigest() if name in files else None
        if actual != expected:
            raise ProjectError(f"remote verification failed: guard/owner state changed for {name}")
    marker = store.project(files)
    if not isinstance(marker, dict) or marker.get("storage") != storage:
        raise ProjectError("remote verification failed: authoritative storage configuration changed")
    errors = _validate_files(root, files)
    if errors:
        raise ProjectError("invalid verified remote workspace:\n" + "\n".join(errors))
    return verified


def publish(root, bundle_path):
    """Publish checked writes against the latest authoritative remote branch.

    Returns the published commit and local journal path. A failed push never
    mutates root HEAD or claims success; the candidate and bundle remain available.
    Success includes verified_remote_commit observed after push; its tree must
    still contain the intended writes and unchanged non-write guards/owners.
    """
    root = find_project(root)
    bundle_path = Path(bundle_path)
    bundle_bytes = bundle_path.read_bytes()
    bundle = _decode_json(bundle_bytes, str(bundle_path))
    _validate_bundle(bundle)
    with _project_lock(root):
        original_head = _clean_root(root)
        errors = validate_project(root)
        if errors:
            raise ProjectError("invalid current workspace:\n" + "\n".join(errors))
        storage = _storage_config(root)
        remote, branch, url = (storage[key] for key in ("remote", "branch", "url"))
        for name in set(bundle["checks"]) | set(bundle["writes"]):
            _no_links(root, name)
        local = root / ".project-local"
        if local.is_symlink():
            raise ProjectError(".project-local cannot be a symlink")
        local.mkdir(mode=0o700, exist_ok=True)
        publications = local / "publish"
        if publications.is_symlink():
            raise ProjectError(".project-local/publish cannot be a symlink")
        publications.mkdir(mode=0o700, exist_ok=True)
        operation = publications / uuid.uuid4().hex
        operation.mkdir(mode=0o700)
        saved_bundle = operation / "bundle.json"
        saved_bundle.write_bytes(bundle_bytes)
        saved_bundle.chmod(0o600)
        journal = operation / "journal.json"
        state = {"state": "prepared", "original_head": original_head, "remote": remote,
                 "branch": branch, "bundle": str(saved_bundle)}
        _write_journal(journal, state)
        try:
            remote_head = _fetch_selected(root, remote, branch)
            state["remote_head"] = remote_head
            if _git(root, "merge-base", "--is-ancestor", original_head, remote_head, check=False).returncode:
                raise ProjectError("root HEAD has unpublished/divergent commits; publication cannot discard them")
            current = _tree_files(root, remote_head)
            for name, expected in bundle["checks"].items():
                actual = hashlib.sha256(current[name]).hexdigest() if name in current else None
                if actual != expected:
                    raise ProjectError(f"byte check conflict: {name}; refresh remote data and rebuild the bundle")
            prospective = store.apply_writes(current, bundle["writes"])
            _check_deletions(bundle, current, prospective)
            _check_owners(bundle, current, prospective)
            new_marker = store.project(prospective)
            if not isinstance(new_marker, dict) or new_marker.get("storage") != storage:
                raise ProjectError("publish cannot change authoritative storage remote/branch/url")
            errors = _validate_files(root, prospective)
            if errors:
                raise ProjectError("invalid prospective workspace:\n" + "\n".join(errors))
            with tempfile.TemporaryDirectory(prefix="project-index-") as directory:
                env = {"GIT_INDEX_FILE": str(Path(directory) / "index")}
                _git(root, "read-tree", remote_head, env=env)
                for name, data in bundle["writes"].items():
                    if data is None:
                        _git(root, "update-index", "--force-remove", "--", name, env=env)
                        continue
                    object_id = _git_text(root, "hash-object", "-w", "--stdin", data=data.encode("utf-8"))
                    _git(root, "update-index", "--add", "--cacheinfo", "100644", object_id, name, env=env)
                tree = _git_text(root, "write-tree", env=env)
            commit = _git_text(root, "commit-tree", tree, "-p", remote_head,
                               data=(bundle["message"] + "\n").encode("utf-8"))
            state.update(state="candidate", candidate=commit)
            _write_journal(journal, state)
            _git(root, "push", "--porcelain", "--no-follow-tags", remote, commit + ":refs/heads/" + branch)
            state["state"] = "push_returned_verification_pending"
            _write_journal(journal, state)
            verified = _verify_publication(root, remote, branch, commit, bundle, storage)
            state["verified_remote_commit"] = verified
            state["state"] = "remote_published_root_pending"
            _write_journal(journal, state)
            if _clean_root(root) != original_head:
                raise ProjectError("remote published but root HEAD changed concurrently; inspect journal before recovery")
            _git(root, "-c", "core.hooksPath=/dev/null", "merge", "--ff-only", "--no-edit", verified)
            if _clean_root(root) != verified:
                raise ProjectError("remote published but root did not become the expected clean commit")
            state["state"] = "published"
            _write_journal(journal, state)
            return {"commit": commit, "verified_remote_commit": verified, "journal": str(journal)}
        except (ProjectError, store.StoreError, OSError) as exc:
            state["error"] = str(exc)
            if state["state"] == "push_returned_verification_pending":
                state["state"] = "remote_verification_failed"
            elif state["state"] != "remote_published_root_pending":
                state["state"] = "failed"
            _write_journal(journal, state)
            raise ProjectError(f"{exc}\nretained bundle/journal: {operation}") from exc


def publication_disposition(state):
    """Separate rejected pre-push attempts from publication outcomes to recover.

    publish() saves its candidate before invoking push. A failed journal without
    that candidate or any later push evidence has no remote mutation to recover;
    its retained bundle is an unsubmitted intent, not a safe retry request.
    """
    if not isinstance(state, dict):
        raise ProjectError("publication journal must be an object")
    if state.get("state") == "published":
        return "published"
    if (state.get("state") == "failed" and
            not any(key in state for key in ("candidate", "verified_remote_commit", "recovery_attempts"))):
        return "rejected_before_push"
    return "pending"


def resume_publication(root, *, session=None, token=None, journal=None, expected_write_hashes=None):
    """Recover one existing publication intent; retry its candidate at most once.

    Only an unchanged original remote base permits a retry. A published candidate
    must still satisfy its writes/guards before the clean root can fast-forward.
    No candidate or bundle is rebuilt, and ambiguous outcomes retain their journal.
    Callers recovering an unlinked intent can require exact saved write hashes.
    """
    root = find_project(root)
    if not _nonempty(session) or token is not None and not _nonempty(token):
        raise ProjectError("publication recovery requires the original session and token")

    def blocked(code, detail, path=None):
        result = {"status": "blocked", "code": code, "action": "blocked", "reason": str(detail)}
        if path is not None:
            result["journal"] = str(path)
        return result

    def owned_journal(path):
        path = path if path.is_absolute() else root / path
        relative = path.relative_to(root)
        parts = relative.parts
        if (len(parts) != 4 or parts[:2] != (".project-local", "publish") or
                not re.fullmatch(r"[0-9a-f]{32}", parts[2]) or parts[3] != "journal.json"):
            raise ProjectError("recovery journal must be a program-owned .project-local/publish/<operation>/journal.json")
        _no_links(root, relative.as_posix())
        bundle_path = path.parent / "bundle.json"
        _no_links(root, bundle_path.relative_to(root).as_posix())
        if not path.is_file() or not bundle_path.is_file():
            raise ProjectError("recovery requires regular program-owned journal and bundle files")
        state, bundle = read_json(path), read_json(bundle_path)
        if not isinstance(state, dict) or state.get("bundle") != str(bundle_path):
            raise ProjectError("journal bundle path does not identify its program-owned saved bundle")
        _validate_bundle(bundle)
        if bundle["session"] != session or bundle["token"] != token:
            raise ProjectError("publication journal belongs to another session/token")
        return path, state, bundle

    with _project_lock(root):
        selected = None
        failure_code = "publication_journal_invalid"
        try:
            if journal is None:
                _no_links(root, ".project-local/publish")
                candidates = []
                for path in sorted((root / ".project-local/publish").glob("*/journal.json")):
                    # Ignore other identities without changing or recovering their intents.
                    try:
                        candidate = owned_journal(path)
                    except ProjectError as exc:
                        if "belongs to another" in str(exc):
                            continue
                        return blocked("publication_journal_invalid", exc, path)
                    if publication_disposition(candidate[1]) == "pending":
                        candidates.append(candidate)
                if not candidates:
                    return {"status": "no_op", "code": "publication_none_pending", "action": "none"}
                if len(candidates) != 1:
                    return {"status": "blocked", "code": "publication_journal_ambiguous", "action": "blocked",
                            "journals": [str(candidate[0]) for candidate in candidates]}
                selected, state, bundle = candidates[0]
            else:
                selected, state, bundle = owned_journal(Path(journal))
            if expected_write_hashes is not None and (not expected_write_hashes or any(
                    name not in bundle["writes"] or
                    (hashlib.sha256(bundle["writes"][name].encode("utf-8")).hexdigest()
                     if bundle["writes"][name] is not None else None) != expected
                    for name, expected in expected_write_hashes.items())):
                return blocked("publication_intent_mismatch",
                               "saved publication writes do not match the retained operation", selected)
            if publication_disposition(state) == "rejected_before_push":
                return blocked("publication_rejected_before_push",
                               "Publication was rejected before push; its saved writes will not be replayed. "
                               "Refresh current inputs and start a new operation.", selected)
            failure_code = "publication_local_dirty"
            original = _clean_root(root)
            failure_code = "publication_storage_changed"
            storage = _storage_config(root)
            if state.get("remote") != storage["remote"] or state.get("branch") != storage["branch"]:
                return blocked("publication_storage_changed", "journal remote/branch differs from project storage", selected)
            base, candidate, original_base = (state.get(key) for key in ("remote_head", "candidate", "original_head"))
            if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value)
                   for value in (base, candidate, original_base)):
                return blocked("publication_candidate_missing", "journal has no complete original base/candidate identity", selected)
            failure_code = "publication_candidate_invalid"
            parents = _git_text(root, "rev-list", "--parents", "-n", "1", candidate).split()
            if parents != [candidate, base] or _git(root, "merge-base", "--is-ancestor", original_base, base, check=False).returncode:
                return blocked("publication_candidate_invalid", "candidate must have exactly the recorded remote base as parent", selected)
            base_files = _tree_files(root, base)
            for name, expected in bundle["checks"].items():
                actual = hashlib.sha256(base_files[name]).hexdigest() if name in base_files else None
                if actual != expected:
                    return blocked("publication_guard_conflict", "saved bundle guard differs from original base: " + name, selected)
            intended = store.apply_writes(base_files, bundle["writes"])
            if _tree_files(root, candidate) != intended:
                return blocked("publication_candidate_invalid", "candidate tree differs from the saved bundle intent", selected)
            _check_deletions(bundle, base_files, intended)
            _check_owners(bundle, base_files, intended)
            if store.project(base_files).get("storage") != storage or store.project(intended).get("storage") != storage:
                return blocked("publication_storage_changed", "candidate/base storage differs from selected storage", selected)
            errors = _validate_files(root, intended)
            if errors:
                return blocked("publication_candidate_invalid", "\n".join(errors), selected)
            failure_code = "publication_outcome_unknown"
            remote = _fetch_selected(root, storage["remote"], storage["branch"])
            contained = _git(root, "merge-base", "--is-ancestor", candidate, remote, check=False).returncode == 0
            retried = False
            if not contained:
                if remote != base:
                    return blocked("publication_remote_changed", "selected remote changed from the recorded base without the candidate", selected)
                attempts = state.get("recovery_attempts", 0)
                if type(attempts) is not int or attempts != 0:
                    return blocked("publication_retry_exhausted", "the same candidate has already received its bounded recovery retry", selected)
                state.update(state="recovery_push_pending", recovery_attempts=1)
                _write_journal(selected, state)
                retried = True
                # A lost push response is reconciled by the verification fetch below.
                _git(root, "push", "--porcelain", "--no-follow-tags", storage["remote"],
                     candidate + ":refs/heads/" + storage["branch"], check=False)
            verified = _verify_publication(root, storage["remote"], storage["branch"], candidate, bundle, storage)
            failure_code = "publication_local_changed"
            if _git(root, "merge-base", "--is-ancestor", original, verified, check=False).returncode:
                return blocked("publication_local_diverged", "local HEAD is not contained in the verified remote", selected)
            if _clean_root(root) != original:
                return blocked("publication_local_changed", "local checkout changed during recovery", selected)
            if verified != original:
                _git(root, "-c", "core.hooksPath=/dev/null", "merge", "--ff-only", "--no-edit", verified)
            if _clean_root(root) != verified:
                return blocked("publication_local_changed", "recovery did not produce the expected clean root", selected)
            state.update(state="published", verified_remote_commit=verified)
            state.pop("error", None)
            _write_journal(selected, state)
            return {"status": "published", "code": "publication_retried" if retried else "publication_recovered",
                    "action": "completed", "commit": candidate, "verified_remote_commit": verified, "journal": str(selected)}
        except (ProjectError, store.StoreError, OSError, ValueError) as exc:
            return blocked(failure_code, exc, selected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "No Aone calls, takeover, arbitrary item deletion, stash, reset or force-push. Run from the "
        "management Git root or its non-nested management subdirectories."))
    parser.add_argument("--root", default=".", help="project directory (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check management schema, paths and dependency DAG; does not verify external delivery")
    identifier = commands.add_parser("new-id", help="print locally available hierarchical id candidates; no writes or reservation")
    identifier.add_argument("slugs", nargs="+", help="short lowercase ASCII phrase for each new item")
    identifier.add_argument("--parent", help="existing parent's full canonical hierarchical id (default: root level)")
    digest = commands.add_parser("digest", help="hash item business files (normalized item.json without owner), excluding sync receipts")
    digest.add_argument("item", help="workitem id")
    commands.add_parser("worktree-root", help="resolve the configured worktree directory; requires the local binding for an external base; no writes")
    worktree = commands.add_parser("worktree-path", help="resolve an item's recorded worktree with local binding and symlink checks; no writes")
    worktree.add_argument("item", help="workitem id")
    publication = commands.add_parser("publish", help="check a UTF-8 JSON bundle, validate the merged graph and publish one Git commit",
        description=("Publish only approved management files. The root must be clean with no "
                     "unfinished Git operation. The marker selects the exact remote URL and branch. "
                     "Checks are evaluated against that branch's latest tree, then the merged graph "
                     "is validated before one non-force push. Existing item owners must match the "
                     "bundle session/token; a new claim must name that session. No takeover."),
        epilog=("After push, fetch and verify the selected ref, intended writes and owner guards; "
                "only then fast-forward the root. Success prints candidate commit, "
                "verified_remote_commit and journal. Failure retains the bundle/candidate/journal "
                "under ignored .project-local/publish/. Inspect remote state before retrying. "
                "Receipt validation does not establish live Aone or delivery facts."))
    publication.add_argument("--bundle", required=True, help=(
        "JSON file with checks {relative_path: SHA256|null}, writes {relative_path: UTF8text|null deletion}, "
        "message, session, token (string|null). Every write requires a check; item files and sync receipts "
        "also require the item metadata check and v2 state check. Put local bundles under ignored .project-local/. "
        "Push failure retains a journal and candidate; inspect remote before rebuilding/retrying."))
    args = parser.parse_args(argv)
    try:
        if args.command == "new-id":
            print("\n".join(new_ids(args.root, args.slugs, args.parent)))
        elif args.command == "validate":
            errors = validate_project(args.root)
            if errors:
                raise ProjectError("\n".join(errors))
            print("valid")
        elif args.command == "digest":
            print(item_digest(args.root, args.item))
        elif args.command == "worktree-root":
            print(worktree_root(args.root))
        elif args.command == "worktree-path":
            print(worktree_path(args.root, args.item))
        elif args.command == "publish":
            print(json.dumps(publish(args.root, args.bundle), ensure_ascii=False))
    except (ProjectError, store.StoreError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

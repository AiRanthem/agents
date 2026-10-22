#!/usr/bin/env python3
"""Build and query a local, derived index of project work items and evidence."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Iterator

try:  # Imported when used as a script or as a module in tests.
    import project_runtime as runtime
    from project_runtime import ProjectError, find_project
    import project_store as store
    import project_retention as retention
    from workitem_ids import parse_id
except ImportError:  # pragma: no cover - test loader can inject the sibling module.
    from . import project_runtime as runtime
    from .project_runtime import ProjectError, find_project
    from . import project_store as store
    from . import project_retention as retention
    from .workitem_ids import parse_id


ROLES = ("manage", "explore", "review-design", "implement", "review-implementation")
INDEX_VERSION = 3
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
ITEM_STATUSES = {"new", "in_progress", "developing", "awaiting_delivery", "done", "cancelled"}


class ContextError(Exception):
    """An invalid or unsafe project context source."""


def _contained_file(root: Path, path: Path) -> Path:
    """Return a regular file below root, rejecting symlinks at every component."""
    root = root.resolve(strict=True)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ContextError(f"path escapes project workspace: {path}") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ContextError(f"path is not normalized within project workspace: {path}")
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise ContextError(f"cannot inspect project path {current}: {exc}") from exc
        if os.path.islink(current):
            raise ContextError(f"symlink is not allowed in project data path: {current}")
    if not current.is_file():
        raise ContextError(f"project data path is not a regular file: {current}")
    return current


def _read_bytes(root: Path, path: Path) -> bytes:
    safe = _contained_file(root, path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(safe, flags)
    except OSError as exc:
        raise ContextError(f"cannot read project metadata {safe}: {exc}") from exc
    try:
        with os.fdopen(fd, "rb") as stream:
            return stream.read()
    except OSError as exc:
        raise ContextError(f"cannot read project metadata {safe}: {exc}") from exc


def _json_bytes(data: bytes, path: Path) -> dict[str, Any]:
    try:
        def unique_object(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError(f"duplicate JSON key: {key}")
                result[key] = value
            return result

        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid JSON constant: {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ContextError(f"malformed canonical JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContextError(f"canonical JSON must contain an object: {path}")
    return value


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _record_files(directory: Path, suffixes: set[str]) -> list[Path]:
    """List machine records without opening or scanning their Markdown siblings."""
    if directory.is_symlink():
        raise ContextError(f"project metadata directory is unsafe: {directory}")
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise ContextError(f"project metadata directory is unsafe: {directory}")
    result = []
    for candidate in sorted(directory.iterdir()):
        if candidate.is_symlink():
            raise ContextError(f"project metadata file is unsafe: {candidate}")
        if candidate.is_dir():
            continue
        if candidate.suffix in suffixes:
            if not candidate.is_file() or not IDENTIFIER.fullmatch(candidate.stem):
                raise ContextError(f"project metadata file is unsafe: {candidate}")
            result.append(candidate)
    return result


def _snapshot_paths(root: Path, include_evidence: bool) -> list[str]:
    """Select canonical records via runtime snapshots; never read Markdown for listing."""
    project_dir = root / ".project"
    if project_dir.is_symlink() or not project_dir.is_dir():
        raise ContextError(f"project metadata directory is unsafe: {project_dir}")
    names = [f".project/{name}" for name in ("project.json", "project.yaml", "graph.yaml")
             if (project_dir / name).is_file()]
    for subdir, suffixes in (("state", {".yaml"}), ("sync", {".json", ".yaml"})):
        names.extend(str(path.relative_to(root)) for path in _record_files(project_dir / subdir, suffixes))

    workitems = root / "workitems"
    if workitems.is_symlink():
        raise ContextError(f"project metadata directory is unsafe: {workitems}")
    if workitems.exists() and not workitems.is_dir():
        raise ContextError(f"project metadata directory is unsafe: {workitems}")
    if workitems.is_dir():
        for item_dir in sorted(workitems.iterdir()):
            if item_dir.is_symlink() or not item_dir.is_dir() or not IDENTIFIER.fullmatch(item_dir.name):
                raise ContextError(f"work item directory is unsafe: {item_dir}")
            for name in ("item.json", "metadata.yaml"):
                path = item_dir / name
                if path.is_symlink():
                    raise ContextError(f"project metadata file is unsafe: {path}")
                if path.exists():
                    if not path.is_file():
                        raise ContextError(f"project metadata file is unsafe: {path}")
                    names.append(str(path.relative_to(root)))

    if include_evidence:
        names.extend(str(path.relative_to(root)) for path in _record_files(root / "evidence", {".json", ".yaml"}))
    if not any(name in names for name in (".project/project.json", ".project/project.yaml")):
        raise ContextError("project metadata marker is missing")
    return sorted(set(names))


def _snapshot(root: Path, include_evidence: bool) -> dict[str, bytes]:
    paths = _snapshot_paths(root, include_evidence)
    try:
        return runtime._working_files(root, paths=tuple(paths))
    except (ProjectError, OSError, ValueError) as exc:
        raise ContextError(f"cannot snapshot project records: {exc}") from exc


def _metadata(data: bytes, path: str) -> tuple[dict[str, Any], str]:
    try:
        value = store.load_yaml(data, path) if path.endswith(".yaml") else _json_bytes(data, Path(path))
    except store.StoreError as exc:
        if path.endswith(".json"):
            raise ContextError(f"malformed canonical JSON {path}: {exc}") from exc
        raise ContextError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ContextError(f"canonical record must contain an object: {path}")
    return value, _hash(data)


def _validate_evidence_body(root: Path, metadata: dict[str, Any], metadata_path: str) -> None:
    body = metadata.get("body")
    expected = f"evidence/{metadata.get('id')}.md"
    if not isinstance(body, str) or body != expected:
        raise ContextError(f"evidence body must point to its same-id Markdown file: {metadata_path}")
    relative = PurePosixPath(body)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "evidence":
        raise ContextError(f"evidence body path must remain under workspace evidence/: {metadata_path}")
    path = root.joinpath(*relative.parts)
    # The project schema requires the same-id body file. Verify only its path
    # and file type; evidence search indexes metadata and never reads body text.
    _contained_file(root, path)


def _validate_item_metadata(item: dict[str, Any], path: Path) -> None:
    if not isinstance(item.get("title"), str) or not item["title"].strip():
        raise ContextError(f"work item title must be a nonempty string: {path}")
    if not isinstance(item.get("kind"), str) or item["kind"] not in {"development", "aggregate"}:
        raise ContextError(f"work item kind is invalid: {path}")
    if not isinstance(item.get("status"), str) or item["status"] not in ITEM_STATUSES:
        raise ContextError(f"work item status is invalid: {path}")
    dependencies = item.get("depends_on")
    if not isinstance(dependencies, list) or any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in dependencies):
        raise ContextError(f"work item depends_on must be a list of identifiers: {path}")
    repository = item.get("repository")
    if repository is not None and (not isinstance(repository, str) or not IDENTIFIER.fullmatch(repository)):
        raise ContextError(f"work item repository must be an identifier or null: {path}")
    development = item.get("development")
    if development is not None and not isinstance(development, dict):
        raise ContextError(f"work item development must be an object or null: {path}")
    if isinstance(development, dict) and "worktree" in development:
        worktree = development["worktree"]
        if worktree is not None and not isinstance(worktree, str):
            raise ContextError(f"work item development.worktree must be a string or null: {path}")
    documents = item.get("documents", {})
    if not isinstance(documents, dict):
        raise ContextError(f"work item documents must be a role-to-path mapping: {path}")
    for role, relative in documents.items():
        if not isinstance(role, str) or not IDENTIFIER.fullmatch(role) or not _document_relative(relative):
            raise ContextError(f"work item document paths must be safe item-relative Markdown paths: {path}")
    design = item.get("design")
    if design is not None and (not isinstance(design, dict) or
                               not _document_relative(design.get("file"))):
        raise ContextError(f"work item design.file must be a safe item-relative Markdown path: {path}")
    if design is not None and design.get("next_action", "implement") not in ("implement", "split"):
        raise ContextError(f"work item design.next_action must be implement or split: {path}")


def _document_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith(".md") or "\\" in value or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return bool(path.parts) and not path.is_absolute() and str(path) == value and all(
        part not in {"", ".", ".."} for part in path.parts)


def _validate_evidence_metadata(root: Path, metadata: dict[str, Any], path: str, repository_ids: set[str]) -> None:
    repository = metadata.get("repository")
    if not isinstance(repository, str) or repository not in repository_ids:
        raise ContextError(f"evidence repository is not configured: {path}")
    for name in ("topic", "summary", "scope"):
        value = metadata.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ContextError(f"evidence {name} must be a nonempty string: {path}")
    if not isinstance(metadata.get("kind"), str) or metadata["kind"] not in {"fact", "inference", "search", "verification"}:
        raise ContextError(f"evidence kind is invalid: {path}")
    if not isinstance(metadata.get("inputs"), dict):
        raise ContextError(f"evidence inputs must be an object: {path}")
    sources = metadata.get("sources")
    if not isinstance(sources, list) or any(
        not isinstance(source, dict) or not isinstance(source.get("path"), str) or not source["path"].strip()
        for source in sources
    ):
        raise ContextError(f"evidence sources must contain path records: {path}")
    _validate_evidence_body(root, metadata, path)


def _load_sources(root: Path, include_evidence: bool) -> dict[str, Any]:
    files = _snapshot(root, include_evidence)
    try:
        marker = store.project(files)
        item_records = store.items(files)
    except store.StoreError as exc:
        if ".json:" in str(exc):
            raise ContextError(f"malformed canonical JSON: {exc}") from exc
        raise ContextError(f"invalid canonical project records: {exc}") from exc
    marker_path = store.project_path(files)
    _validate_project_record(marker, Path(marker_path))
    # Hash every included canonical machine record, including split state and
    # external receipts. The index is derived navigation data, never authority.
    sources = {name: _hash(data) for name, data in files.items()}
    main_workspace_marker = root / ".project" / "main-workspace.md"
    if "main_workspace" in marker:
        sources[".project/main-workspace.md"] = _main_workspace_marker_fingerprint(root, main_workspace_marker)
    repository_ids = {repository["id"] for repository in marker["repositories"]}

    item_entries = []
    for identifier, item in item_records.items():
        path = store.item_path(files, identifier)
        if not isinstance(item.get("id"), str) or not IDENTIFIER.fullmatch(item["id"]) or item["id"] != identifier:
            raise ContextError(f"work item metadata id must match its directory: {path}")
        _validate_item_metadata(item, Path(path))
        item_entries.append({"id": identifier, "metadata": item, "path": path,
                             "schema_version": 2 if store.is_v2(files) else 1,
                             "sha256": _hash(files[path])})

    receipts = []
    for path, data in sorted(files.items()):
        if not path.startswith(".project/sync/"):
            continue
        receipt, digest = _metadata(data, path)
        identifier = Path(path).stem
        if not IDENTIFIER.fullmatch(identifier):
            raise ContextError(f"receipt id is invalid: {path}")
        receipts.append({"id": identifier, "metadata": store.receipt(files, identifier), "path": path, "sha256": digest})

    evidences = []
    for path, data in sorted(files.items()):
        if not path.startswith("evidence/") or Path(path).suffix not in {".json", ".yaml"}:
            continue
        evidence, digest = _metadata(data, path)
        identifier = Path(path).stem
        if not IDENTIFIER.fullmatch(identifier) or evidence.get("id") != identifier:
            raise ContextError(f"evidence id must match its filename: {path}")
        _validate_evidence_metadata(root, evidence, path, repository_ids)
        evidences.append({"id": identifier, "metadata": evidence, "path": path, "sha256": digest})
    return {
        "version": INDEX_VERSION,
        "coverage": "items+evidence" if include_evidence else "items",
        "project": marker,
        "project_path": marker_path,
        "sources": sources,
        "items": sorted(item_entries, key=lambda entry: entry["id"]),
        "receipts": receipts,
        "evidence": sorted(evidences, key=lambda entry: entry["id"]),
    }


def _validate_project_record(project: dict[str, Any], path: Path) -> None:
    required = ("schema_version", "id", "name", "storage", "backends", "repositories")
    missing = [field for field in required if field not in project]
    if missing:
        raise ContextError(f"invalid project metadata {path}: missing {', '.join(missing)}")
    if type(project.get("schema_version")) is not int or project["schema_version"] not in {1, 2}:
        raise ContextError(f"invalid project metadata {path}: schema_version must be 1 or 2")
    if not isinstance(project.get("id"), str) or not project["id"] or not isinstance(project.get("name"), str) or not project["name"].strip():
        raise ContextError(f"invalid project metadata {path}: id and name must be nonempty strings")
    storage = project.get("storage")
    if not isinstance(storage, dict) or any(not isinstance(storage.get(key), str) or not storage[key].strip() for key in ("remote", "branch", "url")):
        raise ContextError(f"invalid project metadata {path}: storage requires remote, branch, and url")
    backends = project.get("backends")
    if not isinstance(backends, dict) or "aone" not in backends:
        raise ContextError(f"invalid project metadata {path}: backends must contain aone")
    repositories = project.get("repositories")
    if not isinstance(repositories, list) or any(not isinstance(repo, dict) for repo in repositories):
        raise ContextError(f"invalid project metadata {path}: repositories must be a list of objects")
    for repository in repositories:
        if not isinstance(repository.get("id"), str) or not IDENTIFIER.fullmatch(repository["id"]):
            raise ContextError(f"invalid project metadata {path}: repository id must be a valid identifier")
    main_workspace = project.get("main_workspace")
    if "main_workspace" in project:
        if not isinstance(main_workspace, dict):
            raise ContextError(f"invalid project metadata {path}: main_workspace must be an object")
        if not isinstance(main_workspace.get("id"), str) or not IDENTIFIER.fullmatch(main_workspace["id"]):
            raise ContextError(f"invalid project metadata {path}: main_workspace.id must be a safe identifier")
        if not isinstance(main_workspace.get("name"), str) or not main_workspace["name"].strip():
            raise ContextError(f"invalid project metadata {path}: main_workspace.name must be a nonempty string")
        if "repository" not in main_workspace:
            raise ContextError(f"invalid project metadata {path}: main_workspace.repository must be present")
        main_repository = main_workspace.get("repository")
        if main_repository is not None:
            if not isinstance(main_repository, dict) or not isinstance(main_repository.get("url"), str) or not main_repository["url"].strip():
                raise ContextError(f"invalid project metadata {path}: main_workspace.repository requires a nonempty url or null")
            if not isinstance(main_repository.get("ref"), str) or not _is_full_git_ref(main_repository["ref"]):
                raise ContextError(f"invalid project metadata {path}: main_workspace.repository.ref must be a full git ref")
    worktrees = project.get("worktrees")
    if "worktrees" in project:
        if not isinstance(worktrees, dict):
            raise ContextError(f"invalid project metadata {path}: worktrees must be an object")
        base, worktree_path = worktrees.get("base"), worktrees.get("path")
        if not isinstance(base, str) or base not in {"project", "main_workspace"}:
            raise ContextError(f"invalid project metadata {path}: worktrees.base must be project or main_workspace")
        parts = _relative_layout_parts(worktree_path) if isinstance(worktree_path, str) else None
        if parts is None:
            raise ContextError(f"invalid project metadata {path}: worktrees.path must be a normalized relative path")
        if base == "project" and parts[0] != "worktrees":
            raise ContextError(f"invalid project metadata {path}: project worktrees.path must be worktrees or a path below it")
        if base == "main_workspace" and not isinstance(main_workspace, dict):
            raise ContextError(f"invalid project metadata {path}: main_workspace worktree base requires main_workspace")
        unsafe_parts = any(part.lower() in {".git", ".project", ".project-local"} for part in parts)
        if base == "project" and unsafe_parts:
            raise ContextError(f"invalid project metadata {path}: project worktrees.path contains a reserved component")
        if base == "main_workspace" and (len(parts) < 2 or unsafe_parts):
            raise ContextError(f"invalid project metadata {path}: main_workspace worktrees.path must be a dedicated safe subdirectory")


def _is_full_git_ref(value: str) -> bool:
    if not value.startswith("refs/") or value == "@" or value.endswith(("/", ".", ".lock")):
        return False
    if any(char in value for char in " ~^:?*[\\]") or any(ord(char) < 32 or ord(char) == 127 for char in value) or ".." in value or "@{" in value:
        return False
    return all(part and not part.startswith(".") and not part.endswith(".lock") for part in value.split("/"))


def _relative_layout_parts(value: str) -> list[str] | None:
    if not value or "\\" in value or "\x00" in value or value.startswith("/"):
        return None
    parts = value.split("/")
    return parts if all(part not in {"", ".", ".."} for part in parts) else None


def _worktree_layout(project: dict[str, Any]) -> dict[str, str]:
    configured = project.get("worktrees")
    if configured is None:
        return {"base": "project", "path": "worktrees"}
    return {"base": configured["base"], "path": configured["path"]}


def _main_workspace_marker_fingerprint(root: Path, marker: Path) -> str:
    """Fingerprint marker metadata without opening or reading the main workspace body."""
    try:
        mode = marker.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        raise ContextError(f"cannot inspect main workspace marker {marker}: {exc}") from exc
    if os.path.islink(marker) or not marker.is_file():
        raise ContextError(f"main workspace marker is not a regular file: {marker}")
    stat = marker.stat()
    signature = f"{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}:{mode}"
    return _hash(signature.encode("ascii"))


def _validate_main_workspace_marker(root: Path) -> None:
    _contained_file(root, root / ".project" / "main-workspace.md")


def _index_path(root: Path) -> Path:
    return root / ".project-local" / "index.json"


@contextlib.contextmanager
def _index_lock(root: Path) -> Iterator[None]:
    local = root / ".project-local"
    if local.is_symlink():
        raise ContextError(f"local index directory must not be a symlink: {local}")
    local.mkdir(mode=0o700, parents=True, exist_ok=True)
    if local.is_symlink():
        raise ContextError(f"local index directory must not be a symlink: {local}")
    lock_path = local / "index.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_cache(root: Path) -> dict[str, Any] | None:
    path = _index_path(root)
    if path.parent.is_symlink() or not path.parent.is_dir():
        return None
    if not path.exists():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != INDEX_VERSION:
            return None
        if (not isinstance(value.get("sources"), dict) or not isinstance(value.get("items"), list)
                or not isinstance(value.get("receipts"), list) or not isinstance(value.get("evidence"), list)):
            return None
        return value
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _write_cache(root: Path, index: dict[str, Any]) -> None:
    path = _index_path(root)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = (json.dumps(index, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, name = tempfile.mkstemp(prefix="index.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def get_index(root: Path, force: bool = False, include_evidence: bool = True,
              write_cache: bool = True) -> tuple[dict[str, Any], bool]:
    """Return fresh derived records; writing the ignored cache is opt-in for CLI queries."""
    root = root.resolve(strict=True)
    lock = _index_lock(root) if write_cache else contextlib.nullcontext()
    with lock:
        # Scan authoritative metadata every time so added/removed files and raw
        # content changes are noticed. No code, worktree, or evidence body is read.
        fresh = _load_sources(root, include_evidence)
        cached = None if force else _read_cache(root)
        actual = dict(fresh["sources"])
        # A cache is only a derived lookup aid; source hashes are checked against
        # current files and never assert that evidence remains applicable.
        valid = (
            cached is not None
            and cached.get("coverage") == fresh["coverage"]
            and cached.get("source_hashes") == actual
            and cached.get("project") == fresh["project"]
            and cached.get("items") == fresh["items"]
            and cached.get("receipts") == fresh["receipts"]
            and cached.get("evidence") == fresh["evidence"]
        )
        if valid:
            return cached, False
        fresh["source_hashes"] = actual
        if write_cache:
            _write_cache(root, fresh)
        return fresh, True


def _match(item: dict[str, Any], query: str) -> bool:
    haystack = " ".join(str(item.get(key, "")) for key in ("id", "title", "kind", "status", "repository"))
    return query.casefold() in haystack.casefold()


def _resolve_item(entries: list[dict[str, Any]], selector: str) -> dict[str, Any]:
    """Prefer the canonical ID, otherwise require one exact metadata match."""
    for entry in entries:
        if entry["id"] == selector:
            return entry
    matches = []
    for entry in entries:
        parsed = parse_id(entry["id"])
        if (parsed is not None and selector in parsed) or entry["metadata"]["title"] == selector:
            matches.append(entry)
    if not matches:
        raise ContextError(f"work item not found: {selector}")
    if len(matches) > 1:
        candidates = "\n".join(f"{entry['id']}: {entry['metadata']['title']}" for entry in matches)
        raise ContextError(f"ambiguous work item selector {selector!r}:\n{candidates}")
    return matches[0]


def _page(rows: list[Any], limit: int, offset: int) -> dict[str, Any]:
    total = len(rows)
    page = rows[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "has_more": offset + len(page) < total, "results": page}


def _body_paths(root: Path, entry: dict[str, Any]) -> list[str]:
    found = []
    for relative in _document_routes(root, entry).values():
        path = root / relative
        if path.exists():
            _contained_file(root, path)
            found.append(relative)
    if entry.get("schema_version") == 2:
        identifier = entry["id"]
        names = (".project/project.yaml", entry["path"], f".project/state/{identifier}.yaml")
        try:
            files = runtime._working_files(root, paths=names)
            records = retention.record_metadata_paths(files, identifier)
            # Read only current state references, never enumerate historical
            # record directories or include their prose in the metadata index.
            pairs = records | {name[:-5] + ".md" for name in records}
            for name in sorted(pairs):
                if name.endswith(".yaml"):
                    files[name] = _read_bytes(root, root / name)
                else:
                    _contained_file(root, root / name)
                    files[name] = b""
            found.extend(sorted(name for name in retention.live_record_paths(files, identifier)
                                if name.endswith(".md")))
        except (ProjectError, store.StoreError) as exc:
            raise ContextError(str(exc)) from exc
        return list(dict.fromkeys(found))
    reviews = root / "workitems" / entry["id"] / "reviews"
    if reviews.exists():
        if reviews.is_symlink() or not reviews.is_dir():
            raise ContextError(f"review directory is unsafe: {reviews}")
        for path in sorted(reviews.glob("*.md")):
            _contained_file(root, path)
            found.append(str(path.relative_to(root)))
    return list(dict.fromkeys(found))


def _document_routes(root: Path, entry: dict[str, Any]) -> dict[str, str]:
    prefix = f"workitems/{entry['id']}/"
    metadata = entry["metadata"]
    if entry.get("schema_version") == 2:
        documents = metadata.get("documents") or {}
        allowed = {"requirement.md", "spec.md", "decision.md", "decisions.md", "context.md",
                   "logs.md", "AGENTS.md", "handoff.md"}
        if any(relative not in allowed for relative in documents.values()):
            raise ContextError("v2 document routes must name current item documents")
        routes = {"requirement": prefix + "requirement.md",
                  "context": prefix + "context.md",
                  "decision": prefix + "decision.md",
                  "logs": prefix + "logs.md"}
        routes.update({role: prefix + relative for role, relative in documents.items()})
        design = metadata.get("design")
        if isinstance(design, dict) and isinstance(design.get("file"), str):
            if design["file"] != "spec.md":
                raise ContextError("v2 design route must name spec.md")
            routes.setdefault("spec", prefix + design["file"])
        return routes

    routes = {}
    for role, candidates in {
        "requirement": ("requirement.md",),
        "context": ("context.md", "handoff.md"),
        "decision": ("decision.md", "decisions.md"),
        "logs": ("logs.md",),
        "spec": ("spec.md",),
    }.items():
        for name in candidates:
            path = root / prefix / name
            if path.exists():
                routes[role] = prefix + name
                break
    return routes


def _role_document_keys(role: str) -> tuple[str, ...]:
    return {
        "manage": (),
        "explore": ("requirement", "context", "decision", "spec", "logs"),
        "review-design": ("requirement", "spec", "decision", "context"),
        "implement": ("requirement", "context", "decision", "spec", "logs"),
        "review-implementation": ("requirement", "context", "decision", "spec", "logs"),
    }[role]


def _document_payload(root: Path, path: str) -> dict[str, Any]:
    target = root / path
    if not target.exists():
        return {"path": path, "exists": False, "sha256": None, "text": None}
    data = _read_bytes(root, target)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContextError(f"document is not UTF-8: {path}") from exc
    return {"path": path, "exists": True, "sha256": _hash(data), "text": text}


def _readiness(items: dict[str, dict[str, Any]], identifier: str) -> dict[str, Any]:
    """Report transitive delivery and open-fix blockers from canonical YAML state."""
    try:
        try:
            import project_workflow as workflow
        except ImportError:  # pragma: no cover - package entrypoint
            from . import project_workflow as workflow
        ancestors = workflow._ancestors(items, identifier)
        fixes = workflow._open_fixes(items, identifier)
    except Exception as exc:
        # Queries stay useful for malformed or cyclic graphs; readiness is then unknown.
        return {"known": False, "reason": str(exc)}
    dependencies = sorted(key for key in ancestors if
                          items[key].get("status") == "cancelled" or
                          items[key].get("delivery", {}).get("status") != "delivered")
    return {
        "known": True,
        "dependency_ready": not dependencies,
        "blocked": bool(dependencies or fixes),
        "blockers": {"dependencies": dependencies, "fixes": fixes},
        "design_state": (items[identifier].get("design") or {}).get("state"),
    }


def command(args: argparse.Namespace) -> dict[str, Any]:
    try:
        root = find_project(Path(args.path))
    except (ProjectError, OSError, ValueError) as exc:
        raise ContextError(str(exc)) from exc
    if not isinstance(root, Path):
        root = Path(root)
    include_evidence = args.command in ("search-evidence", "rebuild")
    # Ordinary query commands are read-only. Rebuild is the explicit operation
    # that writes the disposable cache under ignored .project-local/.
    index, rebuilt = get_index(root, force=args.command == "rebuild",
                               include_evidence=include_evidence,
                               write_cache=args.command == "rebuild")
    result: dict[str, Any]
    if args.command == "rebuild":
        result = {"rebuilt": True, "items": len(index["items"]), "evidence": len(index["evidence"]), "index": str(_index_path(root))}
    elif args.command == "list":
        rows = []
        all_items = {entry["id"]: entry["metadata"] for entry in index["items"]}
        for entry in index["items"]:
            row = dict(entry["metadata"])
            if entry.get("schema_version") == 2:
                row["readiness"] = _readiness(all_items, entry["id"])
            rows.append(row)
        if args.status:
            statuses = set(args.status)
            rows = [row for row in rows if row.get("status") in statuses]
        if args.query:
            rows = [row for row in rows if _match(row, args.query)]
        result = _page(rows, args.limit, args.offset)
    elif args.command == "show":
        entry = _resolve_item(index["items"], args.item)
        receipt = next((record for record in index["receipts"] if record["id"] == entry["id"]), None)
        result = {"metadata": entry["metadata"], "metadata_path": entry["path"],
                  "body_paths": _body_paths(root, entry),
                  "receipt": None if receipt is None else {
                      "metadata": receipt["metadata"], "metadata_path": receipt["path"],
                      "sha256": receipt["sha256"]}}
        if entry.get("schema_version") == 2:
            result["readiness"] = _readiness(
                {item["id"]: item["metadata"] for item in index["items"]}, entry["id"])
    elif args.command == "context":
        project = index["project"]
        main_workspace = project.get("main_workspace")
        if main_workspace is not None:
            # This project-owned navigation document explains how to bind the
            # separate main workspace; inspect its path without reading its body.
            _validate_main_workspace_marker(root)
        entry = _resolve_item(index["items"], args.item)
        canonical_id = entry["id"]
        role = args.role
        meta = entry["metadata"]
        body_paths = _body_paths(root, entry)
        routes = _document_routes(root, entry)
        selected_roles = _role_document_keys(role)
        selected = {Path(entry["path"]).name: entry["path"]}
        order: list[str] = [entry["path"]]
        payloads = {}
        for document_role in selected_roles:
            path = routes.get(document_role)
            if path is None:
                continue
            selected[Path(path).name] = path
            order.append(path)
            payloads[document_role] = _document_payload(root, path)
        deferred = [path for path in body_paths if path.startswith((f"workitems/{canonical_id}/reviews/", f"workitems/{canonical_id}/records/"))] if role in ("review-design", "review-implementation") else []
        receipt = next((record for record in index["receipts"] if record["id"] == canonical_id), None)
        readiness = (_readiness({item["id"]: item["metadata"] for item in index["items"]}, canonical_id)
                     if entry.get("schema_version") == 2 else None)
        if role in ("review-design", "review-implementation"):
            review_order = order
            result = {
                "item": canonical_id,
                "role": role,
                "entrypoint": entry["path"],
                "preread_order": review_order,
                "deferred_inputs": deferred,
                "inputs": selected,
                "documents": payloads,
                "notice": "Selected role documents are included with hashes. Review reports remain deferred until you form an independent assessment. Check relevant source before reaching conclusions.",
            }
        else:
            result = {
                "item": canonical_id,
                "role": role,
                "inputs": selected,
                "documents": payloads,
                "preread_order": order,
                "deferred_inputs": deferred,
                "repository": meta.get("repository"),
                "worktree": (meta.get("development") or {}).get("worktree") if role == "implement" and isinstance(meta.get("development"), dict) else None,
                "evidence_query_hint": "For relevant evidence, run search-evidence <topic> --repository <id> --limit <n> --offset <n>.",
                "notice": "Selected role documents are included with hashes. Evidence applicability requires consumer review; index hashes do not imply valid, current, or passed evidence.",
            }
        result["receipt"] = None if receipt is None else {
            "metadata": receipt["metadata"], "metadata_path": receipt["path"], "sha256": receipt["sha256"]}
        if readiness is not None:
            result["readiness"] = readiness
        result["worktree_layout"] = _worktree_layout(project)
        if main_workspace is not None:
            result["main_workspace"] = {
                "id": main_workspace["id"],
                "name": main_workspace["name"],
                "context_path": ".project/main-workspace.md",
                "binding_path": ".project-local/main-workspace.json",
            }
            result["main_workspace_routing_hint"] = (
                "Read the project-owned navigation document at context_path first; it explains how to bind the main workspace. "
                "After binding, read main workspace constraints when needed. The paths above do not assert that a binding exists or has been validated."
            )
    elif args.command == "search-evidence":
        rows = []
        for record in index["evidence"]:
            meta = record["metadata"]
            if args.repository and meta.get("repository") != args.repository:
                continue
            text = " ".join(str(meta.get(key, "")) for key in ("id", "topic", "summary", "kind", "scope", "repository"))
            if args.query.casefold() in text.casefold():
                rows.append({key: meta.get(key) for key in ("id", "repository", "topic", "summary", "kind", "scope", "sources", "body")})
                rows[-1]["applicability"] = "consumer must recheck against current scope and sources"
        result = _page(rows, args.limit, args.offset)
        result["notice"] = "Evidence bodies were not read. An empty result does not prove that no relevant evidence exists; use bounded source review."
    else:  # pragma: no cover - argparse constrains command values.
        raise ContextError(f"unsupported command {args.command}")
    result["index_rebuilt"] = rebuilt
    result["workspace"] = str(root)
    return result


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def _nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be 0 or greater")
    return number


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--path", default=".", help="path inside a project workspace")
    sub = p.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="list indexed work items")
    listing.add_argument("--status", action="append", help="filter by status (repeatable)")
    listing.add_argument("--query")
    listing.add_argument("--limit", type=_positive_int, default=50)
    listing.add_argument("--offset", type=_nonnegative_int, default=0)
    show = sub.add_parser("show", help="show work item metadata and body paths")
    show.add_argument("item", help="full item ID, hierarchy code, exact phrase or title")
    context = sub.add_parser("context", help="show role-specific input paths")
    context.add_argument("item", help="full item ID, hierarchy code, exact phrase or title")
    context.add_argument("--role", choices=ROLES, required=True)
    search = sub.add_parser("search-evidence", help="search evidence metadata")
    search.add_argument("query")
    search.add_argument("--repository")
    search.add_argument("--limit", type=_positive_int, default=50)
    search.add_argument("--offset", type=_nonnegative_int, default=0)
    sub.add_parser("rebuild", help="rebuild the local derived index")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        payload = command(args)
    except ContextError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

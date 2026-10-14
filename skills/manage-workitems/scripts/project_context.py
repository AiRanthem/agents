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
    from project_runtime import ProjectError, find_project
except ImportError:  # pragma: no cover - test loader can inject the sibling module.
    from .project_runtime import ProjectError, find_project


ROLES = ("manage", "explore", "review-design", "implement", "review-implementation")
INDEX_VERSION = 1
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


def _source_files(root: Path, include_evidence: bool) -> tuple[Path, list[Path], list[Path]]:
    marker = root / ".project" / "project.json"
    workitems = root / "workitems"
    evidence = root / "evidence"
    item_files: list[Path] = []
    evidence_files: list[Path] = []
    sources = [(workitems, "*/item.json", item_files)]
    if include_evidence:
        sources.append((evidence, "*.json", evidence_files))
    for directory, pattern, output in sources:
        if directory.is_symlink():
            raise ContextError(f"project metadata directory is unsafe: {directory}")
        if not directory.exists():
            continue
        if not directory.is_dir():
            raise ContextError(f"project metadata directory is unsafe: {directory}")
        for candidate in sorted(directory.glob(pattern)):
            if candidate.is_symlink() or not candidate.is_file():
                raise ContextError(f"project metadata file is unsafe: {candidate}")
            output.append(candidate)
    return marker, item_files, evidence_files


def _metadata(root: Path, path: Path) -> tuple[dict[str, Any], str]:
    raw = _read_bytes(root, path)
    return _json_bytes(raw, path), _hash(raw)


def _validate_evidence_body(root: Path, metadata: dict[str, Any], metadata_path: Path) -> None:
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


def _validate_evidence_metadata(root: Path, metadata: dict[str, Any], path: Path, repository_ids: set[str]) -> None:
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
    marker_path, item_paths, evidence_paths = _source_files(root, include_evidence)
    marker, marker_hash = _metadata(root, marker_path)
    # This lookup must remain metadata-only: runtime.validate_project currently
    # reads requirement/spec/review/evidence bodies. Structural validation for
    # writes belongs to project_runtime; this command checks only indexed records.
    _validate_project_record(marker, marker_path)
    sources = {".project/project.json": marker_hash}
    main_workspace_marker = root / ".project" / "main-workspace.md"
    if "main_workspace" in marker:
        sources[".project/main-workspace.md"] = _main_workspace_marker_fingerprint(root, main_workspace_marker)
    repository_ids = {repository["id"] for repository in marker["repositories"]}
    items = []
    for path in item_paths:
        item, digest = _metadata(root, path)
        if not isinstance(item.get("id"), str) or not IDENTIFIER.fullmatch(item["id"]):
            raise ContextError(f"work item metadata has no valid id: {path}")
        if item["id"] != path.parent.name:
            raise ContextError(f"work item id does not match its directory: {path}")
        _validate_item_metadata(item, path)
        items.append({"id": item["id"], "metadata": item, "path": str(path.relative_to(root)), "sha256": digest})
    evidences = []
    for path in evidence_paths:
        evidence, digest = _metadata(root, path)
        if not isinstance(evidence.get("id"), str) or not IDENTIFIER.fullmatch(evidence["id"]):
            raise ContextError(f"evidence metadata has no valid id: {path}")
        if evidence["id"] != path.stem:
            raise ContextError(f"evidence id does not match its filename: {path}")
        _validate_evidence_metadata(root, evidence, path, repository_ids)
        evidences.append({"id": evidence["id"], "metadata": evidence, "path": str(path.relative_to(root)), "sha256": digest})
    return {
        "version": INDEX_VERSION,
        "coverage": "items+evidence" if include_evidence else "items",
        "project": marker,
        "sources": sources,
        "items": sorted(items, key=lambda entry: entry["id"]),
        "evidence": sorted(evidences, key=lambda entry: entry["id"]),
    }


def _validate_project_record(project: dict[str, Any], path: Path) -> None:
    required = ("schema_version", "id", "name", "storage", "backends", "repositories")
    missing = [field for field in required if field not in project]
    if missing:
        raise ContextError(f"invalid project metadata {path}: missing {', '.join(missing)}")
    if type(project.get("schema_version")) is not int or project["schema_version"] != 1:
        raise ContextError(f"invalid project metadata {path}: schema_version must be 1")
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
    if not path.exists():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("version") != INDEX_VERSION:
            return None
        if not isinstance(value.get("sources"), dict) or not isinstance(value.get("items"), list) or not isinstance(value.get("evidence"), list):
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


def get_index(root: Path, force: bool = False, include_evidence: bool = True) -> tuple[dict[str, Any], bool]:
    """Return a fresh derived index and whether it had to be rebuilt."""
    root = root.resolve(strict=True)
    with _index_lock(root):
        # Scan authoritative metadata every time so added/removed files and raw
        # content changes are noticed. No code, worktree, or evidence body is read.
        fresh = _load_sources(root, include_evidence)
        cached = None if force else _read_cache(root)
        actual = dict(fresh["sources"])
        actual.update({entry["path"]: entry["sha256"] for entry in fresh["items"]})
        actual.update({entry["path"]: entry["sha256"] for entry in fresh["evidence"]})
        # A cache is only a derived lookup aid; source hashes are checked against
        # current files and never assert that evidence remains applicable.
        valid = (
            cached is not None
            and cached.get("coverage") == fresh["coverage"]
            and cached.get("source_hashes") == actual
            and cached.get("project") == fresh["project"]
            and cached.get("items") == fresh["items"]
            and cached.get("evidence") == fresh["evidence"]
        )
        if valid:
            return cached, False
        fresh["source_hashes"] = actual
        _write_cache(root, fresh)
        return fresh, True


def _match(item: dict[str, Any], query: str) -> bool:
    haystack = " ".join(str(item.get(key, "")) for key in ("id", "title", "kind", "status", "repository"))
    return query.casefold() in haystack.casefold()


def _page(rows: list[Any], limit: int, offset: int) -> dict[str, Any]:
    total = len(rows)
    page = rows[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "has_more": offset + len(page) < total, "results": page}


def _body_paths(root: Path, entry: dict[str, Any]) -> list[str]:
    directory = root / "workitems" / entry["id"]
    found = []
    for name in ("requirement.md", "spec.md", "decisions.md", "handoff.md"):
        path = directory / name
        if path.exists():
            _contained_file(root, path)
            found.append(str(path.relative_to(root)))
    reviews = directory / "reviews"
    if reviews.exists():
        if reviews.is_symlink() or not reviews.is_dir():
            raise ContextError(f"review directory is unsafe: {reviews}")
        for path in sorted(reviews.glob("*.md")):
            _contained_file(root, path)
            found.append(str(path.relative_to(root)))
    return found


def command(args: argparse.Namespace) -> dict[str, Any]:
    try:
        root = find_project(Path(args.path))
    except (ProjectError, OSError, ValueError) as exc:
        raise ContextError(str(exc)) from exc
    if not isinstance(root, Path):
        root = Path(root)
    include_evidence = args.command in ("search-evidence", "rebuild")
    index, rebuilt = get_index(root, force=args.command == "rebuild", include_evidence=include_evidence)
    result: dict[str, Any]
    if args.command == "rebuild":
        result = {"rebuilt": True, "items": len(index["items"]), "evidence": len(index["evidence"]), "index": str(_index_path(root))}
    elif args.command == "list":
        rows = [entry["metadata"] for entry in index["items"]]
        if args.status:
            statuses = set(args.status)
            rows = [row for row in rows if row.get("status") in statuses]
        if args.query:
            rows = [row for row in rows if _match(row, args.query)]
        result = _page(rows, args.limit, args.offset)
    elif args.command == "show":
        entry = next((row for row in index["items"] if row["id"] == args.item), None)
        if entry is None:
            raise ContextError(f"work item not found: {args.item}")
        result = {"metadata": entry["metadata"], "metadata_path": entry["path"], "body_paths": _body_paths(root, entry)}
    elif args.command == "context":
        project = index["project"]
        main_workspace = project.get("main_workspace")
        if main_workspace is not None:
            # This project-owned navigation document explains how to bind the
            # separate main workspace; inspect its path without reading its body.
            _validate_main_workspace_marker(root)
        entry = next((row for row in index["items"] if row["id"] == args.item), None)
        if entry is None:
            raise ContextError(f"work item not found: {args.item}")
        role = args.role
        meta = entry["metadata"]
        body_paths = [] if role == "manage" else _body_paths(root, entry)
        paths_by_name = {Path(path).name: path for path in body_paths}
        selected = {"item.json": entry["path"]}
        order: list[str] = [entry["path"]]
        if role == "explore":
            names = ("requirement.md", "spec.md", "decisions.md", "handoff.md")
        elif role == "review-design":
            names = ("requirement.md", "spec.md", "decisions.md", "handoff.md")
        elif role == "implement":
            names = ("requirement.md", "spec.md", "decisions.md", "handoff.md")
        elif role == "review-implementation":
            names = ("requirement.md", "spec.md", "decisions.md", "handoff.md")
        else:
            names = ()
        for name in names:
            if name in paths_by_name:
                selected[name] = paths_by_name[name]
                order.append(paths_by_name[name])
        deferred = [path for path in body_paths if path.startswith(f"workitems/{args.item}/reviews/")] if role in ("review-design", "review-implementation") else []
        if role in ("review-design", "review-implementation"):
            review_order = order
            if role == "review-design":
                review_order = [
                    paths_by_name[name]
                    for name in ("requirement.md", "spec.md", "decisions.md")
                    if name in paths_by_name
                ]
            result = {
                "item": args.item,
                "role": role,
                "entrypoint": entry["path"],
                "preread_order": review_order,
                "deferred_inputs": deferred,
                "notice": "No review finding, document, or evidence body was read. Check the current contract and relevant source before reaching conclusions.",
            }
        else:
            result = {
                "item": args.item,
                "role": role,
                "inputs": selected,
                "preread_order": order,
                "deferred_inputs": deferred,
                "repository": meta.get("repository"),
                "worktree": (meta.get("development") or {}).get("worktree") if role == "implement" and isinstance(meta.get("development"), dict) else None,
                "evidence_query_hint": "For relevant evidence, run search-evidence <topic> --repository <id> --limit <n> --offset <n>.",
                "notice": "No document or evidence body was read. Evidence applicability requires consumer review; index hashes do not imply valid, current, or passed evidence.",
            }
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
    show.add_argument("item")
    context = sub.add_parser("context", help="show role-specific input paths")
    context.add_argument("item")
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

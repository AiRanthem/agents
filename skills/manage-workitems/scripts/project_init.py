#!/usr/bin/env python3
"""Prepare or publish an independent schema-v2 project workspace.

Initialization creates project metadata only. It does not create work items,
code worktrees, or live backend records.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

try:
    import project_runtime as runtime
    import project_store as store
    from project_migration import project_instructions, generation_record
    import project_templates as templates
except ImportError:  # pragma: no cover - package-module entrypoint
    from . import project_runtime as runtime
    from . import project_store as store
    from .project_migration import project_instructions, generation_record
    from . import project_templates as templates


class ProjectInitError(Exception):
    """Initialization stopped; result carries the retained local state."""

    def __init__(self, message: str, result: dict[str, Any]):
        super().__init__(message)
        self.result = result


def _run(root: Path, *args: str, check: bool = True, data: bytes | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Keep Git from redirecting the requested path through ambient repository overrides.
    for key in tuple(env):
        if key.startswith("GIT_DIR") or key.startswith("GIT_WORK_TREE") or key.startswith("GIT_INDEX_FILE"):
            env.pop(key, None)
    result = subprocess.run(["git", "-C", str(root), *args], input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if check and result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {detail}")
    return result


def _text(root: Path, *args: str) -> str:
    return _run(root, *args).stdout.decode("utf-8").strip()


def _fail(stage: str, destination: Path, error: object, *, commit: str | None = None) -> ProjectInitError:
    result: dict[str, Any] = {
        "status": "failed",
        "stage": stage,
        "destination": str(destination),
        "error": str(error),
        "retained": destination.exists(),
    }
    if commit is not None:
        result["commit"] = commit
    return ProjectInitError(str(error), result)


def _validate_config(config: Any, context: Any, main_workspace_context: Any,
                     local_binding: Any) -> tuple[dict[str, Any], str, dict[str, Any] | None]:
    if not isinstance(config, dict):
        raise ValueError("config must be a project configuration object")
    config = json.loads(json.dumps(config, ensure_ascii=False))
    if type(config.get("schema_version")) is not int or config["schema_version"] not in {1, 2}:
        raise ValueError("config.schema_version must be 1 or 2")
    config["schema_version"] = 2
    if not isinstance(config.get("id"), str) or not runtime._identifier(config["id"]):
        raise ValueError("config.id must be a safe identifier")
    if not isinstance(config.get("name"), str) or not config["name"].strip():
        raise ValueError("config.name must be nonempty")
    storage = config.get("storage")
    if not isinstance(storage, dict):
        raise ValueError("config.storage must be an object")
    for key in ("remote", "branch", "url"):
        if not isinstance(storage.get(key), str) or not storage[key].strip():
            raise ValueError(f"config.storage.{key} must be nonempty")
    if not runtime._identifier(storage["remote"]):
        raise ValueError("config.storage.remote must be a safe remote name")
    if _check_ref(storage["branch"]):
        raise ValueError("config.storage.branch must be a valid branch name without refs/heads/")
    if not isinstance(context, str):
        raise ValueError("context must be Markdown text")

    associated = "main_workspace" in config
    if associated:
        if not isinstance(main_workspace_context, str) or not main_workspace_context.strip():
            raise ValueError("main_workspace_context Markdown is required when config.main_workspace is present")
        if local_binding is not None:
            local_binding = _validate_binding(config["main_workspace"], local_binding)
    elif main_workspace_context is not None or local_binding is not None:
        raise ValueError("main_workspace_context and local_binding require config.main_workspace")
    return config, context, local_binding


def _check_ref(branch: str) -> bool:
    if branch.startswith("refs/heads/"):
        return True
    result = subprocess.run(["git", "check-ref-format", "refs/heads/" + branch],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.returncode != 0


def _validate_binding(main: dict[str, Any], binding: Any) -> dict[str, Any]:
    if not isinstance(main, dict) or not runtime._identifier(main.get("id")):
        raise ValueError("config.main_workspace must contain a safe id")
    if not isinstance(binding, dict) or binding.get("id") != main["id"]:
        raise ValueError("local_binding.id must match config.main_workspace.id")
    root = binding.get("root")
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError("local_binding.root must be an absolute path")
    path = Path(root)
    if path.is_symlink() or not path.is_dir():
        raise ValueError("local_binding.root must be an existing regular directory")
    agents = path / "AGENTS.md"
    if agents.is_symlink() or not agents.is_file():
        raise ValueError("local_binding.root must contain a regular AGENTS.md")
    repository = main.get("repository")
    if repository is not None:
        top = _run(path, "rev-parse", "--show-toplevel", check=False)
        if top.returncode or Path(top.stdout.decode("utf-8").strip()).resolve() != path.resolve():
            raise ValueError("local_binding.root does not match the configured main-workspace repository root")
        urls: set[str] = set()
        for remote in _text(path, "remote").splitlines():
            urls.update(_text(path, "remote", "get-url", "--all", remote).splitlines())
            urls.update(_text(path, "remote", "get-url", "--push", "--all", remote).splitlines())
        if repository.get("url") not in urls:
            raise ValueError("local_binding.root has no effective remote matching main_workspace.repository.url")
    return {"id": main["id"], "root": str(path.resolve())}


def _render(config: dict[str, Any], context: str, main_workspace_context: str | None,
            local_binding: dict[str, Any] | None) -> dict[str, bytes]:
    files = templates.render_workspace(config, context)
    files.pop(".project/project.json", None)
    files[".project/project.yaml"] = store.dump_yaml(config).encode("utf-8")
    files[".project/graph.yaml"] = store.dump_yaml({"revision": 0}).encode("utf-8")
    if "main_workspace" in config:
        main = config["main_workspace"]
        repository = main.get("repository") if isinstance(main, dict) else None
        reference = "not configured" if repository is None else f"`{repository['url']}` at `{repository['ref']}`"
        binding_text = ("`.project-local/main-workspace.json`" if local_binding is not None
                        else "not bound on this machine; the program reports the missing verified binding input and accepts the original main-workspace root through its typed setup input")
        route = (
            f"# Main workspace association\n\n"
            f"Identity: **{main.get('name', '')}** (`{main.get('id', '')}`).\n\n"
            f"Recovery reference: {reference}.\n\n"
            f"Local binding: {binding_text}.\n\n"
            f"## Project-specific instructions and routes\n\n{main_workspace_context.rstrip()}\n"
        )
        files[".project/main-workspace.md"] = route.encode("utf-8")
    if local_binding is not None:
        files[".project-local/main-workspace.json"] = (json.dumps(local_binding, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    files[".project/project-instructions.md"] = project_instructions(files).encode("utf-8")
    files[".project/migration.yaml"] = store.dump_yaml(generation_record(files)).encode("utf-8")
    return files


def _prepare_candidate(files: dict[str, bytes]) -> None:
    """Run the same structural validator before touching the requested destination."""
    with tempfile.TemporaryDirectory(prefix="project-init-check-") as temp:
        root = Path(temp)
        # Machine-local binding is intentionally outside the managed Git tree
        # and the runtime's approved tracked-path set.
        tracked = {name: data for name, data in files.items() if not name.startswith(".project-local/")}
        errors = runtime._validate_files(root, tracked)
        if errors:
            raise ValueError("invalid project metadata:\n" + "\n".join(errors))


def _destination(path: str | os.PathLike[str]) -> Path:
    supplied = Path(path).expanduser().absolute()
    if supplied.is_symlink():
        raise ValueError("destination cannot be a symlink")
    parent = supplied.parent.resolve()
    target = parent / supplied.name
    if target.is_symlink():
        raise ValueError("destination cannot be a symlink")
    if target.exists():
        if not target.is_dir():
            raise ValueError("destination must be an absent or empty directory")
        if any(target.iterdir()):
            raise ValueError("destination must be absent or empty; existing nonempty directory was left untouched")
    return target


def _write_files(root: Path, files: dict[str, bytes]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def _configure_git(root: Path, storage: dict[str, str]) -> None:
    remote, branch = storage["remote"], storage["branch"]
    _run(root, "init", "--quiet")
    _run(root, "symbolic-ref", "HEAD", "refs/heads/" + branch)
    _run(root, "remote", "add", remote, storage["url"])
    _run(root, "config", "--local", f"remote.{remote}.fetch",
         f"+refs/heads/{branch}:refs/remotes/{remote}/{branch}")
    _run(root, "config", "--local", f"remote.{remote}.push",
         f"refs/heads/{branch}:refs/heads/{branch}")
    _run(root, "config", "--local", f"branch.{branch}.remote", remote)
    _run(root, "config", "--local", f"branch.{branch}.merge", "refs/heads/" + branch)
    fetch_urls = _text(root, "remote", "get-url", "--all", remote).splitlines()
    push_urls = _text(root, "remote", "get-url", "--push", "--all", remote).splitlines()
    if fetch_urls != [storage["url"]] or push_urls != [storage["url"]]:
        raise RuntimeError("effective fetch and push URLs must both equal config.storage.url")


def _identity(root: Path) -> None:
    for kind in ("GIT_AUTHOR_IDENT", "GIT_COMMITTER_IDENT"):
        result = _run(root, "var", kind, check=False)
        if result.returncode:
            raise RuntimeError(f"Git {kind.lower()} is unavailable; configure local or user identity before publishing")


def _remote_ref(root: Path, remote: str, branch: str) -> tuple[str, str]:
    ref = "refs/heads/" + branch
    result = _run(root, "ls-remote", "--refs", remote, ref, check=False)
    if result.returncode:
        raise RuntimeError("could not verify selected remote ref: " + result.stderr.decode("utf-8", "replace").strip())
    lines = [line.split("\t", 1) for line in result.stdout.decode("utf-8").splitlines() if line]
    matches = [(oid, name) for oid, name in lines if name == ref]
    if matches:
        raise FileExistsError(f"selected remote ref already exists: {ref}; choose another branch or use recovery")
    if lines:
        raise RuntimeError(f"remote returned unexpected refs while checking {ref}")
    return ref, "absent"


def _publish(root: Path, files: dict[str, bytes], storage: dict[str, str]) -> tuple[str, str]:
    remote, branch = storage["remote"], storage["branch"]
    _identity(root)
    errors = runtime.validate_project(root)
    if errors:
        raise ValueError("project validation failed before publish:\n" + "\n".join(errors))
    ref, _ = _remote_ref(root, remote, branch)
    _run(root, "add", "--all")
    _run(root, "commit", "--no-gpg-sign", "-m", f"Initialize project {files_project_id(files)}")
    commit = _text(root, "rev-parse", "HEAD")
    # The push has no force option and names exactly the selected branch ref.
    _run(root, "push", "--porcelain", "--no-follow-tags", remote,
         f"refs/heads/{branch}:{ref}")
    # Explicit refspecs avoid consulting the remote's symbolic/default branch.
    _run(root, "fetch", "--no-tags", "--no-recurse-submodules", remote,
         f"{ref}:refs/remotes/{remote}/{branch}")
    verified = _text(root, "rev-parse", f"refs/remotes/{remote}/{branch}")
    if verified != commit:
        raise RuntimeError(f"remote ref verification differs from candidate: {verified} != {commit}")
    local_tree = _text(root, "rev-parse", f"{commit}^{{tree}}")
    remote_tree = _text(root, "rev-parse", f"{verified}^{{tree}}")
    if local_tree != remote_tree:
        raise RuntimeError("fetched remote tree does not match the initialized project content")
    _run(root, "branch", f"--set-upstream-to={remote}/{branch}", branch)
    if _run(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout:
        raise RuntimeError("project root is not clean after remote verification")
    return commit, verified


def files_project_id(files: dict[str, bytes]) -> str:
    return store.project(files)["id"]


def init_project(destination: str | os.PathLike[str], config: dict[str, Any], context: str,
                 *, publish: bool = False, main_workspace_context: str | None = None,
                 local_binding: dict[str, Any] | None = None) -> dict[str, Any]:
    """Prepare a new project workspace and optionally publish its first commit.

    The destination is left in place on publication failures for inspection and
    recovery. No work item, code worktree, Aone object, or main-workspace file is
    created or modified.
    """
    requested = Path(destination).expanduser().absolute()
    try:
        config, context, local_binding = _validate_config(
            config, context, main_workspace_context, local_binding)
        target = _destination(destination)
        files = _render(config, context, main_workspace_context, local_binding)
        _prepare_candidate(files)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise _fail("input_validation", requested, exc) from exc

    created = False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.mkdir()
            created = True
        _write_files(target, files)
        _configure_git(target, config["storage"])
        errors = runtime.validate_project(target)
        if errors:
            raise ValueError("project validation failed:\n" + "\n".join(errors))
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        raise _fail("local_prepare", target, exc) from exc

    result: dict[str, Any] = {
        "status": "prepared",
        "destination": str(target),
        "project_id": config["id"],
        "project_name": config["name"],
        "remote": config["storage"]["remote"],
        "branch": config["storage"]["branch"],
        "ref": "refs/heads/" + config["storage"]["branch"],
        "validated": True,
        "published": False,
        "local_files_retained": True,
        "aone": "configured_only; no live synchronization was performed",
        "created_destination": created,
    }
    if not publish:
        return result
    commit: str | None = None
    try:
        commit, verified = _publish(target, files, config["storage"])
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        head = _run(target, "rev-parse", "--verify", "HEAD", check=False)
        if head.returncode == 0:
            commit = head.stdout.decode("utf-8").strip()
        result.update(status="failed", stage="publish", error=str(exc),
                      published=False if commit is None else None,
                      publication_state="not_started" if commit is None else "unknown",
                      local_files_retained=True, commit=commit)
        raise ProjectInitError(str(exc), result) from exc
    result.update(status="published", published=True, commit=commit,
                  verified_remote_commit=verified, clean=True, upstream=f"{config['storage']['remote']}/{config['storage']['branch']}")
    return result


__all__ = ["ProjectInitError", "init_project"]

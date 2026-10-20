"""Fixed Markdown editing workflow; machine state never comes from document syntax.

The only editable inputs are the Markdown files returned by begin(). Signed local
manifests retain optimistic guards and publication intents across retries.
"""

import copy
import difflib
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import socket
import sys
from datetime import datetime, timezone

try:
    import project_runtime as runtime
    import project_store as store
    import project_retention as retention
    from workitem_ids import allocate_ids
except ImportError:  # package entrypoint
    from . import project_runtime as runtime, project_store as store, project_retention as retention
    from .workitem_ids import allocate_ids

ProjectError = runtime.ProjectError
OPERATIONS = {
    "create": {"title", "slug", "parent", "repository", "kind", "depends_on", "delivery_required"},
    "fix": {"title", "slug", "fixes", "parent", "repository", "delivery_required"},
    "requirement-update": set(), "design-update": {"author_session", "contract_unchanged"},
    "decision-record": {"approval_source"},
    "design-review": {"reviewer_session", "review_file"},
    "design-reuse": set(),
    "development-start": {"author_session", "base_ref", "branch", "worktree", "skip_design_review", "approval_source"},
    "development-finish": {"result", "provenance", "reviewer_session", "review_file"},
    "delivery-record": {"kind", "reference", "commit", "provenance"},
    "context-update": set(), "log-record": set(),
    "cleanup-record": {"cleanup_status", "reference", "mode", "approval_source", "discard_development"},
    "kind-update": {"kind", "repository"},
    "rename": {"title"}, "dependency-update": {"depends_on"}, "archive": {"archived"},
}
METADATA_OPERATIONS = {"requirement-update", "decision-record", "context-update", "log-record",
                       "rename", "dependency-update", "archive", "cleanup-record", "kind-update"}
CODE_PREPARATION_OPERATIONS = {"design-update", "design-review", "development-start"}
TICKET = re.compile(r"[0-9a-f]{32}\Z")


def _hash(content):
    if content is None:
        return None
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ProjectError(label + " must be a nonempty string")
    return value


def _local(root, *parts):
    current = Path(root)
    for part in (".project-local", *parts):
        current = current / part
        if current.is_symlink():
            raise ProjectError("local workflow state cannot use symlinks")
        current.mkdir(mode=0o700, exist_ok=True)
        if not current.is_dir():
            raise ProjectError("local workflow state must be a directory")
    return current


def _key(root):
    directory = _local(root)
    path = directory / "workflow.key"
    if path.is_symlink():
        raise ProjectError("workflow key cannot use a symlink")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_bytes()
    value = secrets.token_bytes(32)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)
    return value


def _canonical(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _save(root, directory, manifest):
    payload = dict(manifest)
    payload["signature"] = hmac.new(_key(root), _canonical(manifest), hashlib.sha256).hexdigest()
    path = directory / "manifest.yaml"
    if path.is_symlink():
        raise ProjectError("manifest cannot use a symlink")
    temporary = directory / ".manifest.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(store.dump_yaml(payload))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load(root, ticket):
    if not isinstance(ticket, str) or not TICKET.fullmatch(ticket):
        raise ProjectError("ticket must be the opaque ID returned by begin")
    directory = _local(root, "edits") / ticket
    runtime._no_links(root, directory.relative_to(root).as_posix())
    return directory, _load_manifest(root, directory)


def _load_manifest(root, directory):
    """Read a program-signed local checkpoint within the project."""
    runtime._no_links(root, directory.relative_to(root).as_posix())
    path = directory / "manifest.yaml"
    if not path.is_file():
        raise ProjectError("unknown local workflow checkpoint")
    payload = store.load_yaml(path.read_bytes(), str(path))
    signature = payload.pop("signature", None)
    expected = hmac.new(_key(root), _canonical(payload), hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise ProjectError("workflow manifest was modified outside the program")
    return payload


def _session():
    session = os.environ.get("CODEX_THREAD_ID") or os.environ.get("PROJECT_SESSION_ID")
    if not session:
        raise ProjectError("CODEX_THREAD_ID or PROJECT_SESSION_ID is required for workflow identity")
    return session


def _identity(root, *, item=None, create=True):
    session = _session()
    directory = _local(root, "identities") if create else root / ".project-local/identities"
    path = directory / (_hash(session) + ".yaml")
    runtime._no_links(root, path.relative_to(root).as_posix())
    if path.exists():
        identity = store.load_yaml(path.read_bytes(), str(path))
        if identity.get("session") != session:
            raise ProjectError("invalid stored workflow identity")
        token = identity.get("claims", {}).get(item, identity["token"])
        return {"machine": identity["machine"], "session": session, "token": token}
    if not create:
        return {"session": session, "token": None, "machine": socket.gethostname()}
    identity = {"session": session, "token": secrets.token_hex(32), "machine": socket.gethostname()}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(store.dump_yaml(identity))
    return identity


def _snapshot(root):
    runtime.refresh_project(root)
    files = runtime._working_files(root)
    if not store.is_v2(files):
        raise ProjectError("fixed workflow requires migration to schema version 2")
    errors = runtime._validate_files(root, files)
    if errors:
        raise ProjectError("invalid project snapshot:\n" + "\n".join(errors))
    return files


def _publish(root, writes, identity, message, checks, callback):
    checks = dict(checks)
    for path in writes:
        checks.setdefault(path, None)
    checks.setdefault(".project/graph.yaml", None)
    if callback is None:
        try:
            from project import publish_changes as callback
        except ImportError:
            from .project import publish_changes as callback
    return callback(root, writes, identity, message, checks=checks)


def _resolve(items, selector):
    _text(selector, "work item selector")
    if selector in items:
        return selector
    matches = [identifier for identifier in items if identifier.split("-", 1)[0] == selector]
    if len(matches) != 1:
        raise ProjectError("work item selector is unknown or ambiguous: " + selector)
    return matches[0]


def _documents(item):
    prefix = "workitems/" + item["id"] + "/"
    defaults = {"requirement": "requirement.md", "context": "context.md",
                "decision": "decision.md", "logs": "logs.md"}
    defaults.update(item.get("documents") or {})
    resolved = {}
    for role, path in defaults.items():
        relative = runtime._relative_path(path)
        if relative is None or not path.endswith(".md"):
            raise ProjectError("item documents must be relative Markdown paths")
        resolved[role] = prefix + path
        runtime._managed_path(resolved[role])
    return resolved


def _design(item):
    return item.setdefault("design", {"file": "spec.md", "version": 0, "state": "draft"})


def _spec(item):
    path = _design(item)["file"]
    if runtime._relative_path(path) is None or not path.endswith(".md"):
        raise ProjectError("design must be an item-relative Markdown path")
    return "workitems/" + item["id"] + "/" + path


def _ancestors(items, identifier):
    found, queue = set(), list(items[identifier].get("depends_on", []))
    while queue:
        current = queue.pop()
        if current in found:
            continue
        found.add(current)
        if current not in items:
            raise ProjectError("unknown dependency: " + current)
        queue.extend(items[current].get("depends_on", []))
    return found


def _open_fixes(items, identifier):
    upstream = _ancestors(items, identifier)
    return sorted(key for key, item in items.items() if key != identifier and item.get("fixes") in upstream
                  and item.get("delivery", {}).get("status") != "delivered")


def _blocked(items, identifier, *, speculative=False):
    item = items[identifier]
    if ((item.get("workflow") or {}).get("lifecycle") or {}).get("replacement_pending"):
        raise ProjectError("checkpoint blocked: replacement generation must be prepared")
    predevelopment = _autonomy_module()._predevelopment()
    if not speculative and (predevelopment.state(item) or {}).get("phase") in {"preparing", "baseline", "speculative", "reconciling"}:
        raise ProjectError("checkpoint blocked: predevelopment requires formal convergence")
    pinned = predevelopment.pins(item) if speculative else {}
    pending = [key for key in item.get("depends_on", [])
               if key not in pinned and (items[key].get("delivery", {}).get("status") != "delivered" or items[key].get("status") == "cancelled")]
    fixes = _open_fixes(items, identifier)
    if (items[identifier].get("workflow") or {}).get("autonomy"):
        pending.extend(key for key in item.get("depends_on", [])
                       if key not in pinned and ((items[key].get("workflow") or {}).get("autonomy", {}).get("acceptance") or {}).get("status") != "accepted" and key not in pending)
    if pending or fixes:
        raise ProjectError("checkpoint blocked: undelivered dependencies=" + ",".join(pending) +
                           "; open upstream fixes=" + ",".join(fixes))


def _approval_binding(files, item):
    return {"requirement_sha256": _hash(files.get(_documents(item)["requirement"])),
            "spec_sha256": _hash(files.get(_spec(item))), "version": _design(item)["version"]}


def _design_authors(item):
    """Approval registration is provenance, not authorship of the contract."""
    workflow = item.get("workflow") or {}
    return {value for value in [item.get("design", {}).get("author_session"),
            *workflow.get("design_authors", []),
            *(workflow.get("autonomy") or {}).get("design_authors", [])] if value}


def _code_authors(item):
    state = item.get("workflow") or {}
    return {value for value in [(item.get("development") or {}).get("author_session"),
            *state.get("code_authors", []), *(state.get("autonomy") or {}).get("code_authors", [])] if value}


def _review_ready(files, item, actor=None):
    approval = _design(item).get("approval")
    allowed = {"draft", "review-pending", "implementable"}
    if (not isinstance(approval, dict) or not approval.get("source") or
            _design(item).get("state") not in allowed or
            any(approval.get(key) != value for key, value in _approval_binding(files, item).items())):
        raise ProjectError("design review requires recorded current user approval")
    if actor and actor in _design_authors(item):
        raise ProjectError("independent design reviewer must not have authored or revised the design")


def skill_instructions(operation):
    """Original skill inputs are routing instructions, not project-owned prose."""
    if operation != "design-review":
        return []
    directory = Path(__file__).resolve().parents[2] / "review-design"
    return [str(directory / "SKILL.md"), str(directory / "references/project-mode.md")]


def gates(files, item, actor=None):
    """Diagnostic operation gates reuse the authoritative checkpoint predicates.

    Host identity, ownership and live source checks still run at begin/finish.
    """
    result = {}
    predicates = {"design-review": lambda: _review_ready(files, item, actor),
                  "development-start": lambda: (_blocked(store.items(files), item["id"]), _approved(files, item))}
    for operation, predicate in predicates.items():
        reasons = []
        try:
            predicate()
        except (ProjectError, store.StoreError, KeyError, ValueError) as exc:
            reasons.append(str(exc))
        result[operation] = {"eligible": not reasons, "blockers": reasons,
                             "requires_begin": True}
    approval = _design(item).get("approval") or {}
    approved = bool(approval.get("source") and all(approval.get(k) == v for k, v in _approval_binding(files, item).items()))
    return {"operations": result, "approval": "current" if approved else "missing_or_stale",
            "handoff": "independent_review" if approved else "author_present_contract_for_user_decision",
            "contract": _approval_binding(files, item),
            "skill_instruction_paths": skill_instructions("design-review")}


def _binding(files, item, base):
    documents = _documents(item)
    design = _design(item)
    return {"requirement_sha256": _hash(files.get(documents["requirement"])),
            "spec_sha256": _hash(files.get(_spec(item))),
            "version": design["version"], "base_commit": base,
            "dependency_sha256": _dependency_digest(files, item)}


def _design_reuse():
    try:
        import project_design_reuse
    except ImportError:
        from . import project_design_reuse
    return project_design_reuse


def _approved(files, item, *, missing_root=None):
    if _design_reuse().pending(files, item):
        raise ProjectError("independent contract confirmation is required before implementation")
    actual_base = (item.get("development") or {}).get("base_commit")
    waiver = (item.get("workflow") or {}).get("design_waiver")
    if isinstance(waiver, dict):
        binding = _binding(files, item, actual_base)
        if (waiver.get("kind") == "user_design_review_waiver" and waiver.get("source") and
                waiver.get("item") == item["id"] and
                all(waiver.get(key) == value for key, value in binding.items())):
            return
    design = _design(item)
    approval, review = design.get("approval"), design.get("review")
    reused = isinstance(review, dict) and _design_reuse().current(files, item, review, missing_root=missing_root)
    if not isinstance(approval, dict) or not isinstance(review, dict):
        raise ProjectError("current user approval and independent design review are required")
    if (design.get("state") != "implementable" or review.get("result") != "pass" or
            any(approval.get(key) != value for key, value in _approval_binding(files, item).items()) or
            (not reused and any(review.get(key) != value for key, value in _binding(files, item, actual_base).items())) or
            review.get("session") in _design_authors(item) or
            not review.get("provenance") or item.get("needs_review") or
            not (reused or _autonomy_module().review_inputs_current(files, item, review, missing_root=missing_root))):
        raise ProjectError("design approval or independent review is stale or incomplete")


def _implementation_approved(files, item, *, missing_root=None):
    development = item.get("development") or {}
    review = development.get("review") or {}
    if item.get("kind") == "aggregate":
        return
    if (item.get("design", {}).get("review", {}).get("result") == "fail" or
            (item.get("workflow") or {}).get("design_review_failure")):
        raise ProjectError("unresolved independent design findings block implementation acceptance")
    if _autonomous(item):
        _approved(files, item, missing_root=missing_root)
    if (review.get("result") != "pass" or not review.get("provenance") or
            not review.get("session") or review.get("session") in _code_authors(item) or
            review.get("code_snapshot") != development.get("reviewed_snapshot") or
            not _autonomy_module().review_inputs_current(files, item, review, missing_root=missing_root) or
            any(review.get(key) != value for key, value in _binding(files, item, development.get("base_commit")).items())):
        raise ProjectError("delivery requires a current independent implementation review")


def _base(item):
    return (item.get("development") or {}).get("base_commit")


def _read_payload(root, files, item, operation):
    documents = _documents(item)
    selected = {"AGENTS.md", ".project/project-instructions.md", ".project/main-workspace.md", ".project/business-instructions.md", ".project/context.md",
                documents["requirement"], documents["context"]}
    if operation in {"requirement-update", "design-update", "decision-record", "design-review", "design-reuse",
                     "development-start", "development-finish", "delivery-record"}:
        selected.add(_spec(item))
    if operation in {"design-update", "decision-record", "design-review", "design-reuse", "development-start", "development-finish"}:
        selected.add(documents["decision"])
    result = [{"path": str(Path(root) / path), "content": files[path].decode("utf-8")}
              for path in sorted(selected) if path in files]
    items = store.items(files)
    extra_items = set(item.get("depends_on", [])) if operation in {"design-update", "design-review", "design-reuse", "development-start", "development-finish"} else set()
    pinned = _autonomy_module()._predevelopment().pins(item)
    if extra_items:
        extra_items.update(pinned)
    if operation == "fix":
        extra_items.add(item["fixes"])
    for identifier in sorted(extra_items):
        upstream = items[identifier]
        if identifier in pinned:
            captured = pinned[identifier]
            path = captured["report"]
            if path not in files or _hash(files[path]) != captured["artifact_sha256"]:
                raise ProjectError("frozen prerequisite contract is missing or changed: " + identifier)
            paths = {path}
        else:
            paths = {_documents(upstream)["requirement"], _spec(upstream)}
        if operation == "fix":
            paths.add(_documents(upstream)["context"])
        for path in sorted(paths):
            if path in files and str(Path(root) / path) not in {entry["path"] for entry in result}:
                result.append({"path": str(Path(root) / path), "content": files[path].decode("utf-8")})
    allow_missing = (operation in {"cleanup-record", "kind-update"} or
                     operation in METADATA_OPERATIONS and item.get("cleanup") == "done")
    instruction_options = {"allow_missing_development": True} if allow_missing else {}
    for path in _development_module().instruction_files(root, item, store.project(files), **instruction_options):
        path = Path(path)
        if str(path) not in {entry["path"] for entry in result}:
            result.append({"path": str(path), "content": path.read_text(encoding="utf-8")})
    return result


def _drafts(operation, item, files):
    documents = _documents(item)
    if operation in {"create", "fix"}:
        return {"requirement.md": (documents["requirement"], "# " + item["title"] + "\n\n## 目标\n\n## 范围\n\n## 验收条件\n\n## 交付结果\n"),
                "context.md": (documents["context"], "# 当前上下文\n\n")}
    if operation in {"requirement-update", "context-update", "design-update"}:
        target = {"requirement-update": documents["requirement"], "context-update": documents["context"],
                  "design-update": _spec(item)}[operation]
        template = files.get(target, b"# Design\n\n").decode("utf-8")
        return {Path(target).name: (target, template)}
    if operation in {"decision-record", "log-record"}:
        target = documents["decision" if operation == "decision-record" else "logs"]
        return {Path(target).name: (target, files.get(target, b"").decode("utf-8"))}
    if operation in {"design-review", "design-reuse", "development-finish", "delivery-record"}:
        drafts = {"report.md": (None, "# " + operation + "\n\n")}
        if operation == "design-review":
            drafts["spec.md"] = (_spec(item), files[_spec(item)].decode("utf-8"))
        return drafts
    return {}


def _options(operation, options):
    options = copy.deepcopy(options or {})
    if not isinstance(options, dict) or set(options) - OPERATIONS[operation]:
        raise ProjectError("unsupported options for " + operation)
    if operation in {"create", "fix"}:
        for key in ("title", "slug"):
            _text(options.get(key), key)
    if operation in {"design-review", "development-finish"}:
        if "result" in options and options["result"] not in {"pass", "fail"}:
            raise ProjectError("review result must be pass or fail")
        if "provenance" in options:
            _text(options["provenance"], "review provenance")
    if operation == "design-review" and {"reviewer_session", "review_file"}.intersection(options):
        _text(options.get("reviewer_session"), "actual independent design reviewer session")
    if "author_session" in options:
        _text(options["author_session"], "actual source/design author")
    if "contract_unchanged" in options and type(options["contract_unchanged"]) is not bool:
        raise ProjectError("contract_unchanged must be an explicit boolean")
    if operation == "decision-record" and "approval_source" in options:
        _text(options["approval_source"], "actual user approval source")
    if operation == "delivery-record":
        _text(options.get("provenance"), "delivery provenance")
        for key in ("kind", "reference"):
            values = options.get(key, [])
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, list):
                raise ProjectError(key + " must be repeated text options")
            for value in values:
                _text(value, key)
            options[key] = values
        if len(options["kind"]) != len(options["reference"]):
            raise ProjectError("delivery kind/reference options must have equal counts")
        if "commit" in options:
            _text(options["commit"], "commit")
    if operation == "development-finish":
        _text(options.get("reviewer_session"), "independent reviewer session")
    if operation == "development-start":
        if "skip_design_review" in options and type(options["skip_design_review"]) is not bool:
            raise ProjectError("skip_design_review must be an explicit boolean")
        if options.get("skip_design_review"):
            _text(options.get("approval_source"), "explicit user design-review waiver source")
        elif "approval_source" in options:
            raise ProjectError("approval_source requires explicit skip_design_review")
    if operation == "cleanup-record" and "discard_development" in options:
        if type(options["discard_development"]) is not bool:
            raise ProjectError("discard_development must be an explicit boolean")
        if options["discard_development"]:
            _text(options.get("reference"), "cleanup reference")
            _text(options.get("approval_source"), "explicit user development discard approval source")
            if options.get("cleanup_status") != "done" or options.get("mode", "verify") != "verify":
                raise ProjectError("discard_development requires cleanup_status done and mode verify")
    return options


def _validate_discard(root, files, item, options):
    if not options.get("discard_development"):
        return
    if item.get("kind") != "development" or not item.get("development"):
        raise ProjectError("discard_development requires recorded development on a development item")
    if item.get("status") == "done" or item.get("delivery", {}).get("status") == "delivered":
        raise ProjectError("delivered development cannot be discarded")
    location = _development_module().worktree_location(root, item, store.project(files))
    if Path(location).exists() or Path(location).is_symlink():
        raise ProjectError("cleanup is not complete: recorded code worktree still exists")
    return _development_module().reservation_for_discard(root, item, store.project(files))


def _new_item(items, options, operation):
    parent = options.get("parent")
    if parent is not None:
        parent = _resolve(items, parent)
    identifier = allocate_ids(items, [options["slug"]], parent)[0]
    fixes = _resolve(items, options.get("fixes")) if operation == "fix" else None
    if fixes and items[fixes].get("delivery", {}).get("status") != "delivered":
        raise ProjectError("fix creates a separate work item only for a delivered item")
    repository = options.get("repository", items[fixes].get("repository") if fixes else None)
    item = {"id": identifier, "title": options["title"], "kind": options.get("kind", "development"),
            "status": "new", "archived": False, "depends_on": [_resolve(items, value) for value in options.get("depends_on", [])],
            "split_from": parent, "repository": repository, "owner": None, "development": None,
            "delivery": {"required": options.get("delivery_required", ["merged"]),
                         "status": "pending", "evidence": []}, "cleanup": "not_applicable"}
    if fixes:
        item["fixes"] = fixes
        item["depends_on"] = [fixes]
    item["documents"] = {"requirement": "requirement.md", "context": "context.md", "decision": "decision.md", "logs": "logs.md"}
    _design(item)
    return item


def _ownership(item, identity):
    claim = _ownership_module().claim_token(item)
    if ((claim is not None and claim != identity["token"]) or
            not _ownership_module().authorized(item, identity)):
        raise ProjectError("work item has another control claim; use explicit takeover")


def _ownership_module():
    try:
        import project_ownership
    except ImportError:
        from . import project_ownership
    return project_ownership


def _development_module():
    try:
        import project_development
    except ImportError:
        from . import project_development
    return project_development


def _code_snapshot(root, item, project):
    development = _development_module()
    location = development.worktree_location(root, item, project)
    return development.snapshot(location)


def _checks(files, item, operation):
    items = store.items(files)
    items.setdefault(item["id"], item)
    upstream = _ancestors(items, item["id"])
    related = upstream | {item["id"]} | {key for key, value in items.items() if value.get("fixes") in upstream}
    selected = {store.project_path(files), ".project/graph.yaml", "AGENTS.md", ".project/context.md",
                ".project/project-instructions.md", ".project/business-instructions.md", ".project/main-workspace.md"}
    for key in related:
        selected.update({store.item_path(files, key), ".project/state/" + key + ".yaml", store.receipt_path(files, key)})
        if key == item["id"]:
            selected.update(path for path in files if path.startswith("workitems/" + key + "/"))
        else:
            selected.update({_documents(items[key])["requirement"], _spec(items[key])})
    if any(((value.get("workflow") or {}).get("lifecycle") or {}).get("policy") for value in items.values()):
        selected.update(path for path in files if path.startswith(".project/state/") or path.endswith("/metadata.yaml"))
    return {path: _hash(files.get(path)) for path in sorted(selected)}


def _autonomy_module():
    try:
        import project_autonomy
    except ImportError:
        from . import project_autonomy
    return project_autonomy




def _actor(item, identity, operation, options):
    actor = options.get("author_session", identity["session"])
    if operation in {"design-review", "development-finish"} and options.get("reviewer_session"):
        actor = options["reviewer_session"]
        if actor == identity["session"]:
            raise ProjectError("reviewer must be independent from the registering session")
    return actor


def _autonomous(item):
    return bool((item.get("workflow", {}).get("autonomy") or {}).get("authorization"))


def _begin(root, operation, selector=None, *, options=None, publish=None):
    """Refresh, claim the item and return only relevant prose and fixed edit paths."""
    if operation not in OPERATIONS:
        raise ProjectError("unknown fixed workflow operation")
    options = _options(operation, options)
    root = runtime.find_project(root)
    files = _snapshot(root)
    items = store.items(files)
    item = _new_item(items, options, operation) if operation in {"create", "fix"} else copy.deepcopy(items[_resolve(items, selector)])
    identifier = item["id"]
    identity = _identity(root, item=identifier)
    actor = _actor(item, identity, operation, options)
    if item.get("archived") and operation != "archive":
        raise ProjectError("archived work item cannot be edited")
    if item.get("status") == "done" and operation not in {"context-update", "log-record", "archive", "rename", "cleanup-record"}:
        raise ProjectError("delivered history cannot reopen; create a separate fix work item")
    _ownership(item, identity)
    if operation == "development-start" and options.get("skip_design_review") and _design_reuse().pending(files, item):
        raise ProjectError("independent contract confirmation cannot be waived")
    if operation in {"development-start", "development-finish", "delivery-record"}:
        _blocked(items, identifier, speculative=_autonomous(item) and operation != "delivery-record")
        if operation == "development-start" and options.get("skip_design_review"):
            _text(files.get(_documents(item)["requirement"], b"").decode("utf-8"), "requirement contract")
        elif operation == "delivery-record":
            _implementation_approved(files, item)
        elif operation != "development-finish" or item.get("status") != "awaiting_delivery" or _autonomous(item):
            _approved(files, item)
    if operation == "design-reuse":
        _design_reuse().ready(item, identity)
    if operation == "design-review":
        _review_ready(files, item, actor)
    if operation == "development-finish":
        if not item.get("development") or item.get("status") not in {"developing", "awaiting_delivery"}:
            raise ProjectError("development review requires active development")
        if options["reviewer_session"] in _code_authors(item) | {identity["session"]}:
            raise ProjectError("implementation reviewer must use a different session")
    review_source = None
    if options.get("review_file"):
        source = Path(options["review_file"]).absolute()
        for component in (source, *source.parents):
            if component.is_symlink():
                raise ProjectError("review source cannot use symlinks")
        if not source.is_file():
            raise ProjectError("review source must be an actual report file")
        review_source = {"path": str(source), "sha256": _hash(source.read_bytes())}
    if operation == "cleanup-record":
        _validate_discard(root, files, item, options)
    if operation in METADATA_OPERATIONS:
        # These checkpoints never provision code. Reject unreadable instructions
        # before publishing an ownership claim that cannot yield an edit.
        _read_payload(root, files, item, operation)
    ticket = secrets.token_hex(16)
    directory = _local(root, "edits", ticket)
    manifest = {"ticket": ticket, "operation": operation, "item": item, "identity": identity,
                "options": options, "created_at": _now(), "base_commit": _base(item), "state": "context-pending"}
    if review_source:
        manifest["review_source"] = review_source
    _save(root, directory, manifest)
    # Claims are published before the agent sees an editable file. New IDs remain
    # optimistic reservations until finish; concurrent creation is rejected there.
    if operation not in {"create", "fix"} and item.get("owner") is None:
        item["owner"] = identity
        writes = store.write_item(files, item)
        manifest.update(state="claim-pending", claim_writes=writes, checks=_checks(files, item, operation))
        _save(root, directory, manifest)
        try:
            result = _publish(root, writes, identity, "Claim " + identifier, manifest["checks"], publish)
        except (ProjectError, store.StoreError, OSError, ValueError) as exc:
            result = _failure(exc)
            result.update(ticket=ticket, next_command=_resume_command(root, ticket))
            return result
        if result.get("status") == "blocked":
            return {**result, "ticket": ticket, "action_code": result.get("code", "publication_blocked")}
        if result.get("status") not in {"published", "no_op"}:
            manifest["state"] = "claim-pending"
            manifest["claim_writes"] = writes
            manifest["checks"] = _checks(files, item, operation)
            _save(root, directory, manifest)
            return {"status": "partial", "ticket": ticket}
        return _continue_context(root, directory, manifest, None, publish)
    return _continue_context(root, directory, manifest, files, publish)


def _continue_context(root, directory, manifest, files, publish):
    manifest["state"] = "context-pending"
    _save(root, directory, manifest)
    try:
        if files is None:
            files = _snapshot(root)
        return _prepare_context(root, directory, manifest, files, publish)
    except (ProjectError, store.StoreError, OSError, UnicodeError, ValueError) as exc:
        result = _failure(exc)
        result["ticket"] = manifest["ticket"]
        # known-limit: inputs can change after metadata preflight. Retain its
        # ticket for an explicitly requested recovery, not automatic continuation;
        # a unified failure lifecycle needs a separate cancel/release contract.
        if manifest["operation"] not in METADATA_OPERATIONS:
            result["next_command"] = _resume_command(root, manifest["ticket"])
        return result


def _prepare_context(root, directory, manifest, files, publish):
    operation, options, identity = manifest["operation"], manifest["options"], manifest["identity"]
    identifier = manifest["item"]["id"]
    item = store.item(files, identifier) if operation not in {"create", "fix"} else manifest["item"]
    _ownership(item, identity)
    manifest["item"] = item
    if operation in CODE_PREPARATION_OPERATIONS and item.get("repository"):
        development = dict(item.get("development") or {})
        development.update(_development_module().prepare(root, item, store.project(files), options=options, publish_branch=not _autonomous(item)))
        if development != item.get("development"):
            item["development"] = development
            item.setdefault("workflow", {}).pop("development_discard_record", None)
            item["cleanup"] = "pending"
            writes = store.write_item(files, item)
            writes.update(retention.prune_records(store.apply_writes(files, writes), [identifier]))
            checks = _checks(files, item, operation)
            manifest.update(state="context-publication-pending", context_writes=writes,
                            context_message="Prepare code context " + identifier, checks=checks)
            _save(root, directory, manifest)
            result = _publish(root, writes, identity, manifest["context_message"], checks, publish)
            if result.get("status") == "blocked":
                return {**result, "ticket": manifest["ticket"], "action_code": result.get("code", "publication_blocked")}
            if result.get("status") not in {"published", "no_op"}:
                return {"status": "partial", "ticket": manifest["ticket"]}
            files = _snapshot(root)
            item = store.item(files, identifier)
            manifest["item"] = item
            manifest.pop("context_writes", None)
            manifest.pop("context_message", None)
        manifest["base_commit"] = _base(item)
    if operation in {"development-finish", "design-reuse"} and item.get("development"):
        manifest["code_snapshot"] = _code_snapshot(root, item, store.project(files))
    return _open_edit(root, directory, manifest, files)


def _code_context(root, item, project, captured=None):
    development = item.get("development")
    if not development:
        return None
    result = {"repository": item["repository"], "worktree": str(_development_module().worktree_location(root, item, project)),
              "branch": development["branch"], "base_commit": development["base_commit"]}
    if captured is not None:
        result["snapshot"] = captured
    return result


def _open_edit(root, directory, manifest, files):
    item = manifest["item"]
    operation = manifest["operation"]
    review_source = manifest.get("review_source")
    read = _read_payload(root, files, item, operation)
    manifest["read"] = read
    manifest["read_hashes"] = (_autonomy_module()._read_hashes(root, files, item, "design-review", read=read)
                               if operation in {"design-review", "design-reuse", "development-start", "development-finish"} else
                               {entry["path"]: _hash(Path(entry["path"]).read_bytes()) for entry in read})
    if operation == "design-reuse":
        _design_reuse().ready(item, manifest["identity"])
        manifest["reuse_target"] = _design_reuse().target(root, files, item)
        manifest["read_hashes"] = manifest["reuse_target"]["read_hashes"]
    manifest["state"] = "editing"
    manifest["checks"] = _checks(files, item, operation)
    manifest["checks"].setdefault(".project/graph.yaml", None)
    manifest["drafts"] = {}
    editable = []
    for name, (target, template) in _drafts(operation, item, files).items():
        path = directory / name
        if name == "report.md" and review_source:
            template = (review_source["body"] if "body" in review_source else
                        Path(review_source["path"]).read_text(encoding="utf-8"))
        path.write_text(template, encoding="utf-8")
        manifest["drafts"][name] = {"target": target, "initial_sha256": _hash(template)}
        editable.append({"path": str(path), "template": template})
    _save(root, directory, manifest)
    result = {"status": "editing", "ticket": manifest["ticket"], "read": read,
              "editable": editable, "finish_command": _finish_command(root, manifest["ticket"])}
    approved_contract = ((item.get("workflow") or {}).get("autonomy") or {}).get("approved_contract")
    if approved_contract and operation in {"design-review", "design-update", "development-start", "development-finish"}:
        result["approved_contract"] = copy.deepcopy(approved_contract)
    prerequisites = _autonomy_module()._predevelopment().pins(item)
    if prerequisites:
        result["prerequisites"] = copy.deepcopy(prerequisites)
    lifecycle = (item.get("workflow") or {}).get("lifecycle") or {}
    if lifecycle.get("generations"):
        result["retained_sources"] = copy.deepcopy(lifecycle["generations"])
    code_context = _code_context(root, item, store.project(files), manifest.get("code_snapshot"))
    if code_context:
        result["code_context"] = code_context
    if operation == "design-review" and item.get("workflow", {}).get("design_basis"):
        result["design_basis"] = copy.deepcopy(item["workflow"]["design_basis"])
    if operation == "design-reuse":
        result["design_basis"] = copy.deepcopy(_design_reuse().ready(item, manifest["identity"]))
        result["current_target"] = copy.deepcopy(manifest["reuse_target"])
    if operation in {"design-review", "design-reuse", "development-finish"}:
        result["finish_options"] = "--result pass|fail --provenance SOURCE"
        if operation == "design-review" and _design_reuse().pending(files, item):
            result["finish_options"] += " --contract-unchanged (required for pass)"
        if operation == "design-review":
            result["mechanical_correction_options"] = "--mechanical-correction --contract-unchanged (only for uniquely determined contract-preserving candidate corrections)"
        result["skill_instruction_paths"] = skill_instructions(operation)
    all_items = store.items(files)
    result["dependencies"] = [{"id": key, "title": all_items[key]["title"], "status": all_items[key]["status"],
                               "delivery": all_items[key]["delivery"]["status"]}
                              for key in item.get("depends_on", [])]
    return result


def _finish_command(root, ticket):
    return shlex.quote(sys.executable) + " " + shlex.quote(str(Path(__file__).with_name("project.py"))) + " --root " + shlex.quote(str(root)) + " finish " + ticket


def _begin_command(root, manifest):
    args = [sys.executable, str(Path(__file__).with_name("project.py")), "--root", str(root), "begin", manifest["operation"]]
    if manifest["operation"] not in {"create", "fix"}:
        args.append(manifest["item"]["id"])
    for key, value in manifest["options"].items():
        flag = "--" + key.replace("_", "-")
        if isinstance(value, bool):
            args.append(flag if value else "--no-" + key.replace("_", "-"))
        else:
            for entry in value if isinstance(value, list) else [value]:
                args.extend([flag, str(entry)])
    return shlex.join(args)


def _stale(root, manifest, message):
    result = {"status": "stale", "ticket": manifest["ticket"], "message": message}
    sensitive = {"approval_source", "skip_design_review", "discard_development", "result", "provenance", "review_file", "reviewer_session"}
    if (manifest["operation"] in {"design-review", "design-reuse", "development-finish"} or
            sensitive.intersection(manifest["options"]) or manifest.get("review_source")):
        result.update(status="blocked", code="stale_evidence", action_code="stale_evidence",
                      message=message + " Start a new operation with fresh authorization or review evidence.")
    else:
        result["next_command"] = _begin_command(root, manifest)
    return result


def _validate_edits(directory, manifest):
    expected = {"manifest.yaml", *manifest.get("drafts", {})}
    for path in directory.iterdir():
        if path.name not in expected or path.is_symlink() or not path.is_file():
            raise ProjectError("unexpected file or symlink in edit directory: " + path.name)
    if {path.name for path in directory.iterdir()} != expected:
        raise ProjectError("an expected workflow draft is missing")
    return {name: (directory / name).read_text(encoding="utf-8") for name in manifest.get("drafts", {})}


def _dependency_digest(files, item):
    items = store.items(files)
    upstream = _ancestors(items, item["id"])
    records = {key: {"status": items[key].get("status"), "delivery": items[key].get("delivery"),
                     "requirement": _hash(files.get(_documents(items[key])["requirement"])),
                     "spec": _hash(files.get(_spec(items[key])))} for key in sorted(upstream)}
    for key in records:
        captured = _autonomy_module()._predevelopment().frozen_dependency(item, key)
        if captured:
            records[key] = {"snapshot": captured}
    fixes = {key: {"fixes": value["fixes"], "status": value.get("status"), "delivery": value.get("delivery")}
             for key, value in items.items() if value.get("fixes") in upstream and key != item["id"]}
    return _hash(_canonical({"upstream": records, "fixes": fixes}))


def _bump_graph(files, writes):
    path = ".project/graph.yaml"
    graph = store.load_yaml(files[path], path) if path in files else {"revision": 0}
    writes[path] = store.dump_yaml({"revision": graph["revision"] + 1})


def _report(root, manifest, item, files, writes, kind, content):
    record_id = manifest["ticket"]
    base = "workitems/" + item["id"] + "/records/" + record_id
    report = base + ".md"
    writes[report] = content
    record = {"id": record_id, "kind": kind, "item": item["id"], "report": report,
              "session": manifest["identity"]["session"], "created_at": manifest["created_at"],
              "provenance": manifest["options"].get("provenance"),
              **_binding(files, item, manifest["base_commit"])}
    writes[base + ".yaml"] = store.dump_yaml(record)
    return record


def _invalidate_implementation(item):
    autonomy = (item.get("workflow") or {}).get("autonomy")
    if autonomy:
        autonomy.pop("acceptance", None)
        autonomy.pop("implementation", None)
    if item.get("status") == "awaiting_delivery":
        item["status"] = "in_progress"
    development = item.get("development")
    if isinstance(development, dict):
        development.pop("review", None)
        development.pop("reviewed_snapshot", None)
    if isinstance(item.get("workflow"), dict):
        item["workflow"].pop("design_waiver", None)


def _prepare_finish(root, manifest, files, drafts):
    operation, options = manifest["operation"], manifest["options"]
    identity = manifest["identity"]
    items = store.items(files)
    item = copy.deepcopy(manifest["item"] if operation in {"create", "fix"} else items[manifest["item"]["id"]])
    identifier = item["id"]
    actor = _actor(item, identity, operation, options)
    approval = _design(item).get("approval")
    if isinstance(approval, dict):
        approval.pop("record", None)
    if operation in {"create", "fix"} and identifier in items:
        raise ProjectError("allocated work item ID was published by another session; begin again")
    _ownership(item, identity)
    if operation == "development-start" and options.get("skip_design_review") and _design_reuse().pending(files, item):
        raise ProjectError("independent contract confirmation cannot be waived")
    if operation in {"development-start", "development-finish", "delivery-record"}:
        _blocked(items, identifier, speculative=_autonomous(item) and operation != "delivery-record")
        if operation == "development-start" and options.get("skip_design_review"):
            _text(files.get(_documents(item)["requirement"], b"").decode("utf-8"), "requirement contract")
        elif operation == "delivery-record":
            _implementation_approved(files, item)
        elif operation != "development-finish" or item.get("status") != "awaiting_delivery" or _autonomous(item):
            _approved(files, item)
    documents = _documents(item)
    writes = {}
    if operation in {"requirement-update", "design-update", "decision-record", "dependency-update", "context-update"}:
        _design_reuse().capture(root, files, item)
    if operation in {"create", "fix"}:
        try:
            from project_migration import item_entry
        except ImportError:
            from .project_migration import item_entry
        writes["workitems/" + identifier + "/AGENTS.md"] = item_entry(identifier)
        writes[documents["decision"]] = "# 当前决策\n\n"
        writes[documents["logs"]] = "# 当前知识\n\n"
    for name, text in drafts.items():
        target = manifest["drafts"][name]["target"]
        if target:
            writes[target] = text
    if operation == "requirement-update":
        if _hash(writes[documents["requirement"]]) != _hash(files.get(documents["requirement"])):
            _invalidate_implementation(item)
            authors = item.setdefault("workflow", {}).setdefault("design_authors", [])
            if actor not in authors:
                authors.append(actor)
            design = _design(item)
            design["state"] = "draft"
            design.pop("approval", None)
            design.pop("review", None)
    elif operation == "design-update":
        pending_revision = _design_reuse().pending(files, item)
        design = _design(item)
        if _hash(writes[_spec(item)]) != _hash(files.get(_spec(item))):
            _invalidate_implementation(item)
            authors = item.setdefault("workflow", {}).setdefault("design_authors", [])
            for author in (design.get("author_session"), actor):
                if author and author not in authors:
                    authors.append(author)
            design["version"] += 1
            design["author_session"] = actor
            design["state"] = "draft"
            design.pop("approval", None)
            design.pop("review", None)
            if options.get("contract_unchanged"):
                if not _autonomous(item):
                    raise ProjectError("contract-preserving revision requires scoped advancement authorization")
                original = copy.deepcopy(approval)
                if not original:
                    raise ProjectError("contract-internal revision requires the original user approval")
                prospective = store.apply_writes(files, writes)
                derived = {**_approval_binding(prospective, item), "kind": "derived_revision",
                           "source": original["source"], "session": actor,
                           "original_user_approval": original.get("original_user_approval", original),
                           "revision": manifest["ticket"]}
                design["approval"] = derived
                design["state"] = "review-pending"
                item.setdefault("workflow", {}).setdefault("design_authors", []).append(actor)
            elif pending_revision:
                # Candidate repair retains only the original comparison mandate;
                # an independent unchanged-contract pass is still required.
                prospective = store.apply_writes(files, writes)
                design["approval"] = {**approval, **_approval_binding(prospective, item)}
                design["state"] = "review-pending"
    elif operation == "decision-record":
        _text(writes[documents["decision"]], "decision body")
        if "approval_source" in options:
            design = _design(item)
            if not files.get(_spec(item)) or design["version"] < 1:
                raise ProjectError("approval requires an existing versioned design")
            design["approval"] = {**_approval_binding(files, item),
                                  "kind": "user", "source": options["approval_source"],
                                  "session": identity["session"], "recorded_by": identity["session"]}
            design["state"] = "review-pending"
            design.pop("review", None)
    elif operation == "design-reuse":
        if options.get("result") not in {"pass", "fail"}:
            raise ProjectError("finish assessment requires an explicit result pass or fail")
        _text(options.get("provenance"), "assessment provenance")
        _text(drafts["report.md"], "assessment report")
        _design_reuse().finish(root, manifest, files, item, writes, drafts["report.md"])
    elif operation == "design-review":
        if options.get("result") not in {"pass", "fail"}:
            raise ProjectError("finish review requires an explicit result pass or fail")
        _text(options.get("provenance"), "review provenance")
        _text(drafts["report.md"], "review report")
        pending_confirmation = _design_reuse().pending(files, item)
        mechanical = options.get("mechanical_correction") is True
        changed = _hash(drafts["spec.md"]) != _hash(files.get(_spec(item)))
        if changed and not mechanical:
            raise ProjectError("design review candidate changes require explicit mechanical_correction or a separate design revision")
        if mechanical and (not changed or options["result"] != "pass" or options.get("contract_unchanged") is not True):
            raise ProjectError("mechanical correction requires a changed candidate, pass and contract_unchanged confirmation")
        if options.get("contract_unchanged") and (not (pending_confirmation or mechanical) or options["result"] != "pass"):
            raise ProjectError("contract_unchanged is only valid for a passing independent pending-contract confirmation")
        if pending_confirmation and options["result"] == "pass" and options.get("contract_unchanged") is not True:
            raise ProjectError("pending approval requires independent contract_unchanged confirmation")
        design = _design(item)
        approval = design.get("approval")
        _review_ready(files, item, actor)
        # The approval baseline is the design's baseline, not the subsequent
        # management commit that recorded approval or claimed this edit.
        manifest["base_commit"] = _base(item)
        review_files = files
        original_binding = _binding(files, item, manifest["base_commit"])
        if mechanical:
            design["version"] += 1
            review_files = store.apply_writes(files, {_spec(item): drafts["spec.md"]})
            original_approval = copy.deepcopy(approval)
            design["approval"] = {**_approval_binding(review_files, item), "kind": "derived_mechanical",
                "source": approval["source"], "original_user_approval": approval.get("original_user_approval", original_approval),
                "review": manifest["ticket"]}
            approval = design["approval"]
        record = _report(root, manifest, item, review_files, writes, operation, drafts["report.md"])
        if mechanical:
            record["mechanical_correction"] = {"original_binding": original_binding,
                "candidate_sha256": _hash(drafts["spec.md"]), "contract_unchanged": True,
                "diff": "".join(difflib.unified_diff(files[_spec(item)].decode("utf-8").splitlines(keepends=True),
                    drafts["spec.md"].splitlines(keepends=True), fromfile="original/spec.md", tofile="candidate/spec.md"))}

        record["result"] = options["result"]
        if pending_confirmation and options["result"] == "pass":
            record["contract_unchanged"] = True
            design["approval"] = {**approval, "kind": "derived_confirmation", "review": record["id"]}
            authorization = (item.get("workflow", {}).get("autonomy") or {}).get("authorization")
            if authorization:
                authorization.update(requirement_sha256=approval["requirement_sha256"],
                                     decision_sha256=_hash(files.get(documents["decision"])),
                                     design_confirmation=record["id"])
        record["read_hashes"] = copy.deepcopy(manifest["read_hashes"])
        if mechanical:
            record["read_hashes"][str(Path(root) / _spec(item))] = _hash(drafts["spec.md"])
        if options.get("reviewer_session"):
            record.update(session=actor, recorded_by=identity["session"])
        if manifest.get("review_source"):
            record["source"] = copy.deepcopy(manifest["review_source"])
        writes["workitems/" + identifier + "/records/" + manifest["ticket"] + ".yaml"] = store.dump_yaml(record)
        if any(approval.get(key) != value for key, value in _approval_binding(review_files, item).items()):
            raise ProjectError("design approval is stale")
        design["review"] = record
        design["state"] = "implementable" if options["result"] == "pass" else "draft"
        item.pop("needs_review", None)
        if record["result"] == "pass":
            item.setdefault("workflow", {}).pop("design_review_failure", None)
            reviewed_read = copy.deepcopy(manifest.get("read"))
            if mechanical and reviewed_read is not None:
                for row in reviewed_read:
                    if row["path"] == str(Path(root) / _spec(item)):
                        row["content"] = drafts["spec.md"]
            _design_reuse().capture(root, review_files, item, reviewed=True, read=reviewed_read, read_hashes=record["read_hashes"])
        elif pending_confirmation:
            # Preserve the original approved comparison input across the repair;
            # this known failure disables reuse until independent re-review.
            item.setdefault("workflow", {})["design_review_failure"] = copy.deepcopy(record)
        else:
            item.setdefault("workflow", {}).pop("design_basis", None)
            item["workflow"].pop("design_reuse", None)
    elif operation == "development-start":
        if options.get("skip_design_review"):
            waiver = {"id": manifest["ticket"], "kind": "user_design_review_waiver", "item": identifier,
                      "source": options["approval_source"], "session": identity["session"],
                      "created_at": manifest["created_at"], **_binding(files, item, manifest["base_commit"])}
            base = "workitems/" + identifier + "/records/" + manifest["ticket"]
            writes[base + ".yaml"] = store.dump_yaml(waiver)
            writes[base + ".md"] = "# User-authorized design review waiver\n\n" + options["approval_source"] + "\n"
            item.setdefault("workflow", {})["design_waiver"] = waiver
        else:
            _approved(files, item)
        if item.get("status") != "developing":
            item["development"] = _development_module().prepare(root, item, store.project(files), options=options, publish_branch=not _autonomous(item))
        item["development"]["author_session"] = actor
        authors = item.setdefault("workflow", {}).setdefault("code_authors", [])
        if actor not in authors:
            authors.append(actor)
        item.setdefault("workflow", {}).pop("development_discard_record", None)
        item["status"] = "developing"
        item["owner"] = identity
        item["cleanup"] = "pending"
        if _autonomous(item):
            state = item["workflow"]["autonomy"]
            state.pop("implementation", None)
            state.pop("acceptance", None)
            state["implementation_basis"] = {"binding": _autonomy_module()._binding(root, files, item, code=False),
                                                "read_hashes": copy.deepcopy(manifest["read_hashes"])}
    elif operation == "development-finish":
        development = item.get("development") or {}
        if options.get("result") not in {"pass", "fail"}:
            raise ProjectError("finish review requires an explicit result pass or fail")
        _text(options.get("provenance"), "review provenance")
        if options["reviewer_session"] in _code_authors(item) | {identity["session"]}:
            raise ProjectError("implementation review must be independent")
        current = _code_snapshot(root, item, store.project(files))
        if current != manifest.get("code_snapshot"):
            raise ProjectError("code snapshot changed during implementation review; begin review again")
        record = _report(root, manifest, item, files, writes, operation, drafts["report.md"])
        record.update(result=options["result"], code_snapshot=current, session=options["reviewer_session"],
                      recorded_by=identity["session"], read_hashes=copy.deepcopy(manifest["read_hashes"]))
        writes["workitems/" + identifier + "/records/" + manifest["ticket"] + ".yaml"] = store.dump_yaml(record)
        development["review"] = record
        development["reviewed_snapshot"] = current
        if options["result"] == "pass":
            item["status"] = "awaiting_delivery"
            item["owner"] = None
            pre = _autonomy_module()._predevelopment().state(item) or {}
            if pre.get("phase") == "reconciling":
                if not pre.get("rebased"):
                    raise ProjectError("formal code review requires completed convergence")
                pre["phase"] = "formal"
    elif operation == "delivery-record":
        if ((item.get("workflow") or {}).get("autonomy") or {}).get("authorization") and not _autonomy_module()._acceptance_valid(root, files, item):
            raise ProjectError("delivery requires current explicit user acceptance")
        _implementation_approved(files, item)
        if item["kind"] == "development":
            review = (item.get("development") or {}).get("review") or {}
            if review.get("result") != "pass" or review.get("session") == item["development"].get("author_session"):
                raise ProjectError("delivery requires a current independent implementation review")
            verification = _development_module().verify_merged(root, item, store.project(files), evidence={"commit": options.get("commit"), "references": options["reference"]})
            if verification.get("verified") is not True:
                raise ProjectError("delivery merge ancestry could not be verified")
            evidence = [{"kind": kind, "reference": reference} for kind, reference
                        in zip(options["kind"], options["reference"])]
            evidence.append({"kind": verification["kind"], "reference": verification["reference"]})
        else:
            evidence = [{"kind": kind, "reference": reference} for kind, reference
                        in zip(options["kind"], options["reference"])]
        if not set(item["delivery"]["required"]).issubset({record["kind"] for record in evidence}):
            raise ProjectError("delivery is missing required evidence kinds")
        record = _report(root, manifest, item, files, writes, operation, drafts["report.md"])
        record["evidence"] = evidence
        writes["workitems/" + identifier + "/records/" + manifest["ticket"] + ".yaml"] = store.dump_yaml(record)
        item["delivery"].update(status="delivered", evidence=evidence, record=record["id"])
        item["status"], item["owner"] = "done", None
    elif operation == "log-record":
        _text(writes[documents["logs"]], "log body")
    elif operation == "cleanup-record":
        reservation = _validate_discard(root, files, item, options)
        status = options.get("cleanup_status")
        if status not in {"pending", "done", "not_applicable"}:
            raise ProjectError("cleanup_status must be pending, done or not_applicable")
        _text(options.get("reference"), "cleanup reference")
        mode = options.get("mode", "verify")
        if mode not in {"verify", "manual", "skipped"}:
            raise ProjectError("cleanup mode must be verify, manual or skipped")
        if mode != "verify":
            _text(options.get("approval_source"), "explicit user cleanup disposition source")
        if status == "done" and item.get("development"):
            location = _development_module().worktree_location(root, item, store.project(files))
            if Path(location).exists() or Path(location).is_symlink():
                raise ProjectError("cleanup is not complete: recorded code worktree still exists")
        if mode != "verify" and status != "not_applicable":
            raise ProjectError("manual/skipped cleanup only records not_applicable with explicit user disposition")
        if status == "not_applicable" and item.get("development") and mode == "verify":
            raise ProjectError("recorded code development requires cleanup verification or explicit user disposition")
        item["cleanup"] = status
        base = "workitems/" + identifier + "/records/" + manifest["ticket"]
        record = {"id": manifest["ticket"], "kind": "cleanup", "item": identifier, "status": status, "mode": mode,
                  "reference": options["reference"], "session": identity["session"], "created_at": manifest["created_at"]}
        if mode != "verify" or options.get("discard_development"):
            record["approval_source"] = options["approval_source"]
        if options.get("discard_development"):
            record["development_snapshot"] = copy.deepcopy(item["development"])
            if reservation is not None:
                record["reservation_snapshot"] = reservation
            item.setdefault("workflow", {})["development_discard_record"] = record["id"]
            _invalidate_implementation(item)
            item["development"] = None
            if item.get("status") != "cancelled":
                item["status"] = "in_progress"
            design = _design(item)
            design.pop("review", None)
            approval = design.get("approval")
            valid_approval = (isinstance(approval, dict) and
                              all(approval.get(key) == value for key, value in _approval_binding(files, item).items()))
            if not valid_approval:
                design.pop("approval", None)
            design["state"] = "review-pending" if valid_approval else "draft"
        writes[base + ".yaml"] = store.dump_yaml(record)
        writes[base + ".md"] = "# Cleanup disposition\n\n" + options["reference"] + "\n"
        item.setdefault("workflow", {})["cleanup_record"] = record["id"]
    elif operation == "kind-update":
        kind = options.get("kind")
        if kind not in {"development", "aggregate"}:
            raise ProjectError("kind must be development or aggregate")
        if kind != item["kind"]:
            if item["status"] in {"developing", "awaiting_delivery"}:
                raise ProjectError("active code development cannot change kind")
            if kind == "aggregate" and item.get("development"):
                if item.get("cleanup") != "done":
                    raise ProjectError("recorded code development must complete verified cleanup before becoming aggregate")
                location = _development_module().worktree_location(root, item, store.project(files))
                if Path(location).exists() or Path(location).is_symlink():
                    raise ProjectError("recorded code worktree still exists; kind change must retain its development location")
            item["kind"] = kind
            if kind == "aggregate":
                item["repository"], item["development"] = None, None
            else:
                item["repository"] = _text(options.get("repository"), "repository")
    elif operation == "rename":
        item["title"] = _text(options.get("title"), "title")
    elif operation == "dependency-update":
        dependencies = options.get("depends_on")
        if not isinstance(dependencies, list):
            raise ProjectError("depends_on must be a list of selectors")
        resolved = [_resolve(items, value) for value in dependencies]
        if resolved != item.get("depends_on", []):
            _invalidate_implementation(item)
            item["depends_on"] = resolved
            item["needs_review"] = True
            _design(item)["state"] = "draft"
            _design(item).pop("approval", None)
            _design(item).pop("review", None)
    elif operation == "archive":
        if type(options.get("archived")) is not bool:
            raise ProjectError("archived must be an explicit boolean")
        item["archived"] = options["archived"]
    if operation not in {"development-start", "development-finish"} and item.get("status") != "developing":
        item["owner"] = None
    _autonomy_module().release_execution_state(item)
    writes.update(store.write_item(files, item))
    if operation in {"create", "fix", "dependency-update"}:
        _bump_graph(files, writes)
    writes.update(_autonomy_module()._predevelopment()._lifecycle().reconcile(files, writes))
    prospective = store.apply_writes(files, writes)
    writes.update(retention.prune_records(prospective, [identifier]))
    prospective = store.apply_writes(files, writes)
    errors = runtime._validate_files(root, prospective)
    if errors:
        raise ProjectError("workflow would produce invalid project state:\n" + "\n".join(errors))
    return {path: value for path, value in writes.items() if _hash(value) != _hash(files.get(path))}


def _compact_finished(root, directory, manifest):
    for name in manifest.get("drafts", {}):
        (directory / name).unlink(missing_ok=True)
    tombstone = {key: manifest[key] for key in ("ticket", "operation", "identity", "created_at", "state")}
    tombstone["item"] = {"id": manifest["item"]["id"]}
    if manifest != tombstone:
        _save(root, directory, tombstone)
    return tombstone


def _finish(root, ticket, *, options=None, publish=None):
    """Validate fixed drafts and publish the retained intent without stale writes."""
    root = runtime.find_project(root)
    directory, manifest = _load(root, ticket)
    if _identity(root, item=manifest["item"]["id"]) != manifest["identity"]:
        raise ProjectError("edit ticket belongs to another session")
    if manifest["state"] == "finished":
        manifest = _compact_finished(root, directory, manifest)
        result = {"status": "no_op", "ticket": ticket, "item": manifest["item"]["id"]}
        if manifest["operation"] == "development-start":
            files = runtime._working_files(root)
            result["code_context"] = _code_context(root, store.item(files, manifest["item"]["id"]), store.project(files))
        return result
    if options:
        if manifest["operation"] not in {"design-review", "design-reuse", "development-finish"} or set(options) - ({"result", "provenance", "contract_unchanged", "mechanical_correction"} if manifest["operation"] == "design-review" else {"result", "provenance"}):
            raise ProjectError("finish accepts typed result/provenance only for design-review, design-reuse or development-finish")
        merged = {**manifest["options"], **options}
        if merged.get("result") not in {"pass", "fail"}:
            raise ProjectError("review result must be pass or fail")
        _text(merged.get("provenance"), "review provenance")
        for flag in ("contract_unchanged", "mechanical_correction"):
            if flag in merged and type(merged[flag]) is not bool:
                raise ProjectError(flag + " must be an explicit boolean")
        if manifest["state"] != "editing" and merged != manifest["options"]:
            raise ProjectError("published review intent cannot change result or provenance")
        manifest["options"] = merged
    drafts = _validate_edits(directory, manifest)
    source = manifest.get("review_source")
    if source and manifest["state"] not in {"claim-pending", "context-pending", "context-publication-pending"}:
        if "body" in source:
            source_current = _hash(source["body"]) == source["sha256"]
        else:
            path = Path(source["path"])
            source_current = (not any(component.is_symlink() for component in (path, *path.parents))
                              and path.is_file() and _hash(path.read_bytes()) == source["sha256"])
        if not source_current or _hash(drafts["report.md"]) != source["sha256"]:
            return _stale(root, manifest, "Independent review artifact changed; draft is retained.")
    files = _snapshot(root)
    if manifest["state"] == "context-pending":
        return _continue_context(root, directory, manifest, files, publish)
    if manifest["state"] in {"claim-pending", "context-publication-pending"}:
        context_publication = manifest["state"] == "context-publication-pending"
        writes = manifest["context_writes" if context_publication else "claim_writes"]
        message = manifest["context_message"] if context_publication else "Claim " + manifest["item"]["id"]
        current_item = store.item(files, manifest["item"]["id"])
        _ownership(current_item, manifest["identity"])
        for path, expected in manifest["checks"].items():
            current_hash = _hash(files.get(path))
            if current_hash != expected and (path not in writes or current_hash != _hash(writes[path])):
                if path != store.receipt_path(files, current_item["id"]):
                    return _stale(root, manifest, "Preparation recovery inputs changed; intent is retained.")
        result = _publish(root, writes, manifest["identity"], message,
                          _checks(files, current_item, manifest["operation"]), publish)
        if result.get("status") in {"partial", "blocked"}:
            return {**result, "ticket": ticket, "action_code": result.get("code", "retry_finish")}
        if result.get("status") not in {"published", "no_op"}:
            raise ProjectError("publisher returned an invalid workflow status")
        files = _snapshot(root)
        manifest["item"] = store.item(files, manifest["item"]["id"])
        manifest["base_commit"] = _base(manifest["item"])
        manifest.pop("claim_writes", None)
        if context_publication:
            manifest.pop("context_writes", None)
            manifest.pop("context_message", None)
            return _open_edit(root, directory, manifest, files)
        if manifest["operation"] == "development-finish":
            manifest["code_snapshot"] = _code_snapshot(root, manifest["item"], store.project(files))
        return _continue_context(root, directory, manifest, files, publish)
    if manifest["operation"] == "design-reuse":
        reuse_item = store.item(files, manifest["item"]["id"])
        _design_reuse().ready(reuse_item, manifest["identity"])
        if manifest.get("code_snapshot") is not None and _code_snapshot(root, reuse_item, store.project(files)) != manifest["code_snapshot"]:
            return _stale(root, manifest, "Assessment source snapshot changed; draft is retained.")
        if manifest["state"] == "prepared":
            try:
                _autonomy_module()._validate_reads(manifest)
            except ProjectError:
                return _stale(root, manifest, "Assessment read inputs changed during publication recovery.")
    recovering = manifest["state"] == "prepared"
    if manifest["state"] == "editing":
        for name, expected in manifest.get("read_hashes", {}).items():
            path = Path(name)
            if any(component.is_symlink() for component in (path, *path.parents)) or (
                    not path.exists() and expected is not None or path.exists() and (not path.is_file() or _hash(path.read_bytes()) != expected)):
                return _stale(root, manifest, "A required read source changed; draft is retained.")
        current = _checks(files, manifest["item"], manifest["operation"])
        if manifest["operation"] in {"development-start", "development-finish", "delivery-record"}:
            try:
                _blocked(store.items(files), manifest["item"]["id"], speculative=_autonomous(store.item(files, manifest["item"]["id"])) and manifest["operation"] != "delivery-record")
                if manifest["operation"] == "delivery-record":
                    _implementation_approved(files, store.item(files, manifest["item"]["id"]))
                elif (manifest["operation"] != "development-finish" or store.item(files, manifest["item"]["id"]).get("status") != "awaiting_delivery") and not (manifest["operation"] == "development-start" and manifest["options"].get("skip_design_review")):
                    _approved(files, store.item(files, manifest["item"]["id"]))
            except ProjectError as exc:
                return {"status": "blocked", "action_code": "checkpoint_blocked", "ticket": ticket, "message": str(exc)}
        if current != manifest["checks"]:
            return _stale(root, manifest, "Project inputs changed; draft is retained.")
        try:
            writes = _prepare_finish(root, manifest, files, drafts)
        except ProjectError as exc:
            if "checkpoint blocked:" in str(exc):
                return {"status": "blocked", "ticket": ticket, "message": str(exc)}
            raise
        manifest["writes"] = writes
        manifest["draft_hashes"] = {name: _hash(value) for name, value in drafts.items()}
        manifest["state"] = "prepared"
        _save(root, directory, manifest)
    else:
        if {name: _hash(value) for name, value in drafts.items()} != manifest["draft_hashes"]:
            raise ProjectError("a partially published intent cannot be edited; retain it and begin a new operation")
        expected = dict(manifest["checks"])
        writes = manifest["writes"]
        identifier = manifest["item"]["id"]
        intended = store.apply_writes(files, writes)
        same_business = runtime._business_digest(files, identifier) == runtime._business_digest(intended, identifier)
        owner = store.item(files, identifier).get("owner")
        own_sync = owner is None or (owner.get("session"), owner.get("token")) == (manifest["identity"]["session"], manifest["identity"]["token"])
        scoped = _checks(files, manifest["item"], manifest["operation"])
        for path in set(scoped) | set(writes):
            value = files.get(path)
            sync_path = path == store.receipt_path(files, identifier) or path == ".project/state/" + identifier + ".yaml"
            if _hash(value) != expected.get(path) and (path not in writes or _hash(value) != _hash(writes[path])):
                if not (sync_path and same_business and own_sync):
                    return _stale(root, manifest, "Publication recovery inputs changed; intent is retained.")
        for path in set(expected) - set(files):
            if expected[path] is not None and (path not in writes or writes[path] is not None):
                return _stale(root, manifest, "Publication recovery input was removed.")
    publish_checks = _checks(files, manifest["item"], manifest["operation"]) if recovering else manifest["checks"]
    result = _publish(root, manifest["writes"], manifest["identity"],
                      manifest["operation"] + " " + manifest["item"]["id"], publish_checks, publish)
    status = result.get("status")
    if status in {"published", "no_op"}:
        manifest["state"] = "finished"
        manifest["publication"] = result
        _save(root, directory, manifest)
        _compact_finished(root, directory, manifest)
    elif status not in {"partial", "blocked"}:
        raise ProjectError("publisher returned an invalid workflow status")
    output = {"status": status, "ticket": ticket, "item": manifest["item"]["id"], "publication": result}
    if status == "blocked":
        output.update(code=result.get("code", "publication_blocked"), action_code=result.get("code", "publication_blocked"),
                      message=result.get("message", "Publication reconciliation requires resolution of the recorded conflict."))
    if manifest["operation"] == "development-start" and status in {"published", "no_op"}:
        intended = store.apply_writes(files, manifest["writes"])
        output["code_context"] = _code_context(root, store.item(intended, manifest["item"]["id"]), store.project(intended))
    if manifest["operation"] in {"design-update", "decision-record"} and status in {"published", "no_op"}:
        intended = store.apply_writes(files, manifest["writes"])
        output["workflow_gates"] = gates(intended, store.item(intended, manifest["item"]["id"]))
    return output


def _failure(error):
    message = str(error)
    rules = (("control claim", "control_claim_required"), ("owned", "owner_conflict"), ("another session", "session_conflict"),
             ("approval", "approval_required"), ("independent", "independent_review_required"),
             ("checkpoint blocked", "checkpoint_blocked"), ("snapshot changed", "code_changed"),
             ("symlink", "unsafe_path"), ("manifest", "invalid_ticket"),
             ("refresh", "refresh_required"), ("requires migration", "migration_required"))
    code = next((code for needle, code in rules if needle in message), "invalid_input")
    return {"status": "blocked", "action_code": code, "message": message}


def begin(root, operation, selector=None, *, options=None, publish=None):
    """Start one fixed edit and return prose, permitted paths and a finish command."""
    try:
        result = _begin(root, operation, selector, options=options, publish=publish)
        result.setdefault("action_code", {"editing": "edit_markdown", "partial": "retry_finish"}.get(result["status"], "inspect_status"))
        return _output(root, result)
    except (ProjectError, store.StoreError, OSError, UnicodeError, ValueError) as exc:
        result = _failure(exc)
        if operation == "design-review":
            result["skill_instruction_paths"] = skill_instructions(operation)
            if result["action_code"] == "approval_required":
                result["next_action"] = "author_present_contract_for_user_decision"
                result["required_fact"] = "actual user approval covering the complete current design"
        return _output(root, result)


def finish(root, ticket, *, options=None, publish=None):
    """Finish or resume the exact retained edit intent; preserve drafts on failure."""
    try:
        result = _finish(root, ticket, options=options, publish=publish)
        result.setdefault("action_code", {"published": "complete", "no_op": "complete", "partial": "retry_finish",
                                           "stale": "begin_again", "blocked": "resolve_blockers", "editing": "edit_markdown"}[result["status"]])
        return _output(root, result)
    except (ProjectError, store.StoreError, OSError, UnicodeError, ValueError) as exc:
        return _output(root, _failure(exc))


def _resume_command(root, ticket):
    return shlex.join([sys.executable, str(Path(__file__).with_name("project.py")), "--root", str(root), "resume", "--ticket", ticket])


def _output(root, result):
    result.setdefault("code", result.get("action_code", "invalid_input"))
    if result["status"] == "editing":
        result["status"] = "ready"
    elif result["status"] == "stale":
        result["status"] = "blocked"
        result["code"] = "stale_ticket"
    if result["status"] == "partial":
        result.pop("finish_command", None)
        result["next_command"] = _resume_command(root, result["ticket"])
    return result


def resume(root, ticket=None, *, publish=None):
    """Resume one retained program intent without accepting replacement content."""
    if ticket is None:
        try:
            root = runtime.find_project(root)
            candidates = []
            for directory in _local(root, "edits").iterdir():
                if TICKET.fullmatch(directory.name):
                    _, manifest = _load(root, directory.name)
                    identity = _identity(root, item=manifest["item"]["id"])
                    if manifest["state"] in {"prepared", "claim-pending", "context-pending", "context-publication-pending"} and manifest["identity"] == identity:
                        candidates.append((manifest["created_at"], directory.name))
            if not candidates:
                return {"status": "no_op", "code": "no_pending_ticket"}
            if len(candidates) != 1:
                return {"status": "blocked", "code": "ticket_required", "action_code": "ticket_required",
                        "message": "Multiple pending edits exist; use the ticket returned by the interrupted operation."}
            ticket = candidates[0][1]
        except (ProjectError, store.StoreError, OSError, ValueError) as exc:
            return _output(root, _failure(exc))
    return finish(root, ticket, publish=publish)

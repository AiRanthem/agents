"""Immutable prerequisite snapshots and isolated convergence for opt-in advancement.

Snapshot publication is create-only and resumable through its persisted identity.
Normal source branches, indexes and worktrees are never used for snapshot commits.
"""
import copy
import json
import os
from pathlib import Path
import re
import secrets
import socket
import tempfile

try:
    import project_runtime as runtime
    import project_store as store
    import project_workflow as workflow
    import project_development as development
except ImportError:
    from . import project_runtime as runtime, project_store as store, project_workflow as workflow, project_development as development

ProjectError = runtime.ProjectError
WRITERS = {"baseline", "rebase"}
PHASES = {"preparing", "baseline", "speculative", "reconciling", "formal"}


def _matches(pattern, value):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _autonomy():
    return workflow._autonomy_module()


def state(item):
    return (item.get("workflow") or {}).get("autonomy", {}).get("predevelopment")


def pins(item):
    current = state(item) or {}
    return current.get("inputs", {}) if current.get("phase") in {"preparing", "baseline", "speculative"} else {}


def identity(item):
    current = state(item)
    if not current:
        return None
    return {key: current.get(key) for key in ("phase", "generation", "inputs", "formal_base", "rebase")}


def frozen_dependency(item, identifier):
    captured = pins(item).get(identifier)
    if not captured:
        return None
    return {key: captured[key] for key in ("id", "item", "commit", "tree", "binding", "artifact_sha256")}


def _latest(item):
    current = (item.get("workflow") or {}).get("autonomy", {})
    captured = current.get("snapshots", {}).get(current.get("latest_snapshot"))
    return captured if captured and _lifecycle().snapshot_offered(item, captured) else None


def _lifecycle():
    try:
        import project_lifecycle
    except ImportError:
        from . import project_lifecycle
    return project_lifecycle


def _normal_blocks(root, files, item):
    return _autonomy()._dependency_blocks(root, files, item, formal=True)


def _guard_configuration(files, item):
    current = state(item)
    if current and current["phase"] != "formal" and current["project_sha256"] != workflow._hash(files[store.project_path(files)]):
        raise ProjectError("predevelopment project configuration changed; preserve the original generation")


def _candidate(root, files, item, coordinator):
    captured = _latest(item)
    if captured:
        current = workflow._approval_binding(files, item)
        return captured if (captured["binding"]["project_sha256"] == workflow._hash(files[store.project_path(files)]) and
                            all(captured["binding"].get(key) == value for key, value in current.items())) else None
    authorization = (item.get("workflow") or {}).get("autonomy", {}).get("authorization", {})
    if (not workflow._ownership_module().authorized(item, workflow._identity(root, item=item["id"], create=False)) or not authorization.get("predevelop") or
            item.get("kind") != "development" or item.get("status") != "awaiting_delivery"):
        return None
    try:
        workflow._implementation_approved(files, item)
        if workflow._code_snapshot(root, item, store.project(files))["tree"] != item["development"]["reviewed_snapshot"]["tree"]:
            return None
    except (ProjectError, OSError):
        return None
    return {"status": "required"}


def schedule(root, files, item, coordinator, *, reviewed=False):
    """Return an extra stage/action, or None to use the ordinary stage loop."""
    current = state(item)
    authorization = (item.get("workflow") or {}).get("autonomy", {}).get("authorization", {})
    if current and current["phase"] != "formal":
        if current["project_sha256"] != workflow._hash(files[store.project_path(files)]):
            return {"state": "blocked", "reasons": ["predevelopment_project_changed"]}
        blocks = _autonomy()._dependency_blocks(root, files, item)
        if blocks:
            return {"state": "blocked", "reasons": blocks}
        if current["phase"] == "preparing":
            return {"state": "ready", "next_action": "prepare"}
        if current["phase"] == "baseline":
            return {"state": "ready", "next_role": "baseline"}
        if current["phase"] == "reconciling" and not current.get("rebased"):
            return {"state": "ready", "next_role": "rebase"}
        if current["phase"] == "speculative" and reviewed:
            if not _normal_blocks(root, files, item):
                return {"state": "ready", "next_action": "prepare"}
            return {"state": "awaiting_predecessor_delivery", "predevelopment": True}
        return None
    if current or not authorization.get("predevelop"):
        return None
    blocks = _normal_blocks(root, files, item)
    if not blocks:
        return None
    if any(value.startswith("open_fix:") for value in blocks):
        return None
    records = store.items(files)
    for identifier in sorted(workflow._ancestors(records, item["id"]) - {item["id"]}):
        upstream = records[identifier]
        if upstream.get("delivery", {}).get("status") == "delivered" and _autonomy()._acceptance_valid(root, files, upstream):
            continue
        if not _candidate(root, files, upstream, coordinator):
            return None
    if item.get("status") == "developing":
        return {"state": "blocked", "reasons": ["existing_development_in_progress"]}
    return {"state": "ready", "next_action": "prepare"}


def _save(root, files, item, identity, message, publish, extra=None):
    return _autonomy()._publish(root, files, [item], identity, message, publish, extra=extra)


def _settled(result):
    return result.get("status") in {"published", "no_op"}


def _record_writes(captured, body=None):
    base = "workitems/" + captured["item"] + "/records/" + captured["id"]
    writes = {base + ".yaml": store.dump_yaml(captured)}
    if body is not None:
        writes[base + ".md"] = body
    return writes


def snapshot(root, selector, *, publish=None):
    root, files = _autonomy()._files(root)
    item = store.item(files, workflow._resolve(store.items(files), selector))
    owner = workflow._identity(root, item=item["id"])
    _autonomy()._owned(item, owner)
    _guard_configuration(files, item)
    authorization = _autonomy()._state(item).get("authorization", {})
    prior_authorization = (state(item) or {}).get("authorization_source")
    captures = _autonomy()._state(item).setdefault("snapshots", {})
    pending = [value for value in captures.values() if value["status"] != "published"]
    if not authorization.get("predevelop") and not prior_authorization and not pending:
        raise ProjectError("snapshot publication requires explicit predevelopment authorization for this item")
    if len(pending) > 1:
        raise ProjectError("ambiguous pending snapshot; preserve existing publication intents")
    project = store.project(files)
    location = development.worktree_location(root, item, project)
    configuration = development._configuration(location, development._repository(item, project))
    development._existing_record(root, item, project, location, configuration)
    if pending:
        captured = pending[0]
        if captured["binding"]["project_sha256"] != workflow._hash(files[store.project_path(files)]):
            raise ProjectError("snapshot project configuration changed; preserve the original intent")
    else:
        if item.get("status") != "awaiting_delivery":
            raise ProjectError("snapshot requires completed development awaiting acceptance")
        workflow._implementation_approved(files, item)
        actual = development.snapshot(location)
        if actual["tree"] != item["development"]["reviewed_snapshot"]["tree"]:
            raise ProjectError("snapshot source differs from the independently reviewed tree")
        binding = _autonomy()._binding(root, files, item)
        for captured in reversed(list(captures.values())):
            if captured["binding"] == binding and _lifecycle().snapshot_offered(item, captured):
                return {"status": "no_op", "snapshot": captured}
        _lifecycle().capacity(item, snapshot=True)
        record_id = secrets.token_hex(16)
        branch = "snapshots/" + project["id"] + "/" + item["id"] + "/" + record_id
        remote_ref = development._published_ref(location, configuration["publish_remote"], branch, development._repository(item, project))
        paths = [workflow._documents(item)["requirement"], workflow._spec(item), workflow._documents(item)["decision"]]
        body = "# Frozen prerequisite: " + item["id"] + "\n\n" + "\n\n".join(
            "## " + name + "\n\n" + files.get(name, b"").decode("utf-8") for name in paths)
        captured = {"id": record_id, "item": item["id"], "kind": "predevelopment-snapshot",
            "report": "workitems/" + item["id"] + "/records/" + record_id + ".md",
            "artifact_sha256": workflow._hash(body), "status": "planned", "binding": binding,
            "repository": item["repository"], "branch": branch, "ref": remote_ref,
            "url": configuration["publish_url"], "head": actual["head"], "tree": actual["tree"],
            "created_at": workflow._now(), "recorded_by": owner["session"]}
        captured["authorization_source"] = prior_authorization or authorization["source"]
        captured["prerequisites"] = {key: value["id"] for key, value in pins(item).items()}
        captures[record_id] = captured
        saved = _save(root, files, item, owner, "Plan frozen snapshot " + item["id"], publish, _record_writes(captured, body))
        if not _settled(saved):
            return saved
        root, files = _autonomy()._files(root)
        item = store.item(files, item["id"])
        captured = _autonomy()._state(item)["snapshots"][record_id]
    local_ref = "refs/heads/" + captured["branch"]
    if captured["status"] == "planned":
        existing = development._git(location, "rev-parse", "--verify", local_ref, check=False)
        if existing.returncode == 0:
            commit = existing.stdout.decode().strip()
            if (development._text(location, "rev-parse", commit + "^{tree}") != captured["tree"] or
                    development._text(location, "rev-parse", commit + "^") != captured["head"] or
                    captured["id"] not in development._text(location, "log", "-1", "--format=%B", commit)):
                raise ProjectError("snapshot branch differs from its persisted intent")
        else:
            commit = development._text(location, "commit-tree", captured["tree"], "-p", captured["head"],
                "-m", "Predevelopment snapshot " + captured["id"] + " for " + item["id"])
            development._git(location, "update-ref", local_ref, commit, "0" * len(commit))
        captured.update(commit=commit, status="committed")
        saved = _save(root, files, item, owner, "Bind frozen snapshot " + item["id"], publish, _record_writes(captured))
        if not _settled(saved):
            return saved
        root, files = _autonomy()._files(root)
        item = store.item(files, item["id"])
        captured = _autonomy()._state(item)["snapshots"][captured["id"]]
    remote = development._remote_head(location, captured["url"], captured["ref"])
    if remote is not None and remote != captured["commit"]:
        raise ProjectError("immutable snapshot remote ref changed; overwriting is forbidden")
    if remote is None:
        # known-limit: plain create plus verification excludes protocol participants;
        # a hostile direct ref writer needs server-enforced create-only protection.
        development._git(location, "push", captured["url"], captured["commit"] + ":" + captured["ref"])
    if development._remote_head(location, captured["url"], captured["ref"]) != captured["commit"]:
        raise ProjectError("snapshot publication is uncertain; resume the same snapshot intent")
    captured["status"] = "published"
    _autonomy()._state(item)["latest_snapshot"] = captured["id"]
    saved = _save(root, files, item, owner, "Publish frozen snapshot " + item["id"], publish, _record_writes(captured))
    return {**saved, "snapshot": captured} if _settled(saved) else saved


def _fetch(checkout, captured):
    if development._remote_head(checkout, captured["url"], captured["ref"]) != captured["commit"]:
        raise ProjectError("frozen prerequisite remote identity changed")
    target = "refs/project-snapshots/" + captured["id"]
    development._git(checkout, "fetch", "--no-tags", captured["url"], captured["ref"] + ":" + target)
    if development._text(checkout, "rev-parse", target + "^{commit}") != captured["commit"]:
        raise ProjectError("fetched prerequisite does not match its pinned snapshot")


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
    checkout = development._checkout(root, _lifecycle().replacement_item(item), project, repo, {})
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
    root, files = _autonomy()._files(root)
    item = store.item(files, workflow._resolve(store.items(files), selector))
    owner = workflow._identity(root, item=item["id"])
    _autonomy()._owned(item, owner)
    _guard_configuration(files, item)
    current = state(item)
    if current and current["phase"] != "formal":
        if current["phase"] not in {"preparing", "speculative"}:
            return {"status": "no_op"}
        readiness = (schedule(root, files, item, owner["session"]) if
                     ((item.get("workflow") or {}).get("lifecycle") or {}).get("replacement_pending") else
                     _autonomy()._next(root, files, item, owner["session"]))
        if readiness["state"] != "ready" or readiness.get("next_action") != "prepare":
            raise ProjectError("predevelopment preparation is not ready: " + str(readiness))
    if current and current["phase"] == "speculative":
        if _normal_blocks(root, files, item):
            raise ProjectError("formal convergence requires actual accepted prerequisite delivery")
        own = snapshot(root, item["id"], publish=publish)
        if not _settled(own):
            return own
        root, files = _autonomy()._files(root)
        item = store.item(files, item["id"])
        current = state(item)
        location = development.worktree_location(root, item, store.project(files))
        configuration = development._configuration(location, development._repository(item, store.project(files)))
        target = development._base(location, configuration, development._identity(store.project(files), item))
        _lifecycle().capacity(item, retiring=True)
        workflow._design_reuse().capture(root, files, item)
        current["retained_developments"].append(copy.deepcopy(item["development"]))
        current.update(phase="reconciling", rebase={"generation": secrets.token_hex(16),
            "source": own["snapshot"], "old_base": item["development"]["base_commit"], "target": target})
        workflow._invalidate_implementation(item)
        item["design"].pop("review", None)
        return _save(root, files, item, owner, "Begin formal convergence " + item["id"], publish)
    if not current:
        _lifecycle().capacity(item)
        readiness = schedule(root, files, item, owner["session"])
        if not readiness or readiness.get("next_action") != "prepare":
            raise ProjectError("predevelopment preparation is not ready")
        captured = {}
        records = store.items(files)
        queue = [(identifier, None) for identifier in item.get("depends_on", [])]
        # A descendant must consume the same transitive versions as the frozen
        # parent. Mixing a parent's A0 with a newer A1 recreates a moving baseline.
        while queue:
            identifier, pinned_id = queue.pop(0)
            upstream = records[identifier]
            if pinned_id is None and upstream.get("delivery", {}).get("status") == "delivered" and _autonomy()._acceptance_valid(root, files, upstream):
                queue.extend((key, None) for key in upstream.get("depends_on", []))
                continue
            value = (_autonomy()._state(upstream).get("snapshots", {}).get(pinned_id) if pinned_id else _latest(upstream))
            if value and not pinned_id and any(value["binding"].get(key) != expected for key, expected in workflow._approval_binding(files, upstream).items()):
                value = None
            if pinned_id and not value:
                raise ProjectError("transitive frozen prerequisite is missing: " + identifier)
            if value and not _lifecycle().snapshot_available(upstream, value):
                raise ProjectError("frozen prerequisite is released or being collected: " + identifier)
            if not value:
                outcome = snapshot(root, identifier, publish=publish)
                if not _settled(outcome):
                    return outcome
                value = outcome["snapshot"]
                root, files = _autonomy()._files(root)
                item = store.item(files, item["id"])
                records = store.items(files)
            if identifier in captured:
                if captured[identifier]["id"] != value["id"]:
                    raise ProjectError("prerequisite snapshots pin conflicting versions: " + identifier)
                continue
            captured[identifier] = copy.deepcopy(value)
            queue.extend(value.get("prerequisites", {}).items())
            queue.extend((key, None) for key in upstream.get("depends_on", []) if key not in value.get("prerequisites", {}))
        project = store.project(files)
        repo = development._repository(item, project)
        checkout = development._checkout(root, _lifecycle().replacement_item(item), project, repo, {})
        configuration = development._configuration(checkout, repo)
        formal_base = development._base(checkout, configuration, development._identity(project, item))
        current = {"phase": "preparing", "generation": secrets.token_hex(16), "inputs": captured,
                   "formal_base": formal_base,
                   "authorization_source": _autonomy()._state(item)["authorization"]["source"],
                   "project_sha256": workflow._hash(files[store.project_path(files)]),
                   "retained_developments": [copy.deepcopy(item["development"])] if item.get("development") else []}
        _autonomy()._state(item)["predevelopment"] = current
        saved = _save(root, files, item, owner, "Plan predevelopment baseline " + item["id"], publish)
        if not _settled(saved):
            return saved
        root, files = _autonomy()._files(root)
        item = store.item(files, item["id"])
        current = state(item)
    if current["phase"] != "preparing":
        return {"status": "no_op"}
    project = store.project(files)
    repo = development._repository(item, project)
    checkout = development._checkout(root, _lifecycle().replacement_item(item), project, repo, {})
    if (item.get("development") and _lifecycle().replacement_item(item) is item and not development.snapshot(checkout)["clean"] and
            not _lifecycle().source_preserved(root, files, item)):
        raise ProjectError("existing development is dirty; preserve it before changing the baseline")
    same = [value for value in current["inputs"].values() if value["repository"] == item["repository"]]
    for value in same:
        _fetch(checkout, value)
    # Delivered dependencies live on the formal base, which may have advanced
    # independently of every frozen prerequisite. Pin it for this generation too.
    start = current["formal_base"]
    for value in same:
        if development._git(checkout, "merge-base", "--is-ancestor", start, value["commit"], check=False).returncode == 0:
            start = value["commit"]
    workflow._design_reuse().capture(root, files, item)
    item["development"] = _new_worktree(root, files, item, current["generation"], start, "predev")
    complete = all(development._git(checkout, "merge-base", "--is-ancestor", value["commit"], start, check=False).returncode == 0 for value in same)
    current["phase"] = "speculative" if complete else "baseline"
    current["baseline"] = start
    workflow._invalidate_implementation(item)
    item["design"].pop("review", None)
    item["status"], item["owner"], item["cleanup"] = "in_progress", None, "pending"
    return _save(root, files, item, owner, "Prepare predevelopment baseline " + item["id"], publish)


def prepare_writer(root, files, item, role, *, author_session):
    """Prepare the authorized generation and retain source authorship."""
    current = state(item)
    if role == "rebase":
        plan = current["rebase"]
        old = item["development"]
        # Repeated preparation reuses the same adopted generation.
        if old.get("predevelopment_generation") != plan["generation"]:
            project = store.project(files)
            checkout = development._checkout(root, item, project, development._repository(item, project), {})
            _fetch(checkout, plan["source"])
            descriptor = _new_worktree(root, files, item, plan["generation"], plan["source"]["commit"], "formal")
            descriptor["base_commit"] = plan["old_base"]
            descriptor["predevelopment_generation"] = plan["generation"]
            item["development"] = descriptor
    _validate_generation(root, files, item)
    item["status"] = "developing"
    item["development"]["author_session"] = author_session
    authors = item.setdefault("workflow", {}).setdefault("code_authors", [])
    if author_session not in authors:
        authors.append(author_session)


def writer_context(item, role):
    current = state(item)
    if role == "baseline":
        return {"operation": "integrate-prerequisites", "commits": [current["formal_base"],
                *[value["commit"] for value in current["inputs"].values()
                  if value["repository"] == item["repository"]]], "baseline": current["baseline"]}
    if role == "rebase":
        return {"operation": "rebase", **copy.deepcopy(current["rebase"])}
    return None


def _validate_generation(root, files, item, *, base=None):
    """Git transforms may only write their own still-unpublished generation."""
    project = store.project(files)
    location = development.worktree_location(root, item, project)
    candidate = copy.deepcopy(item)
    if base is not None:
        candidate["development"]["base_commit"] = base
    configuration = development._configuration(location, development._repository(item, project))
    development._existing_record(root, candidate, project, location, configuration)
    if (item["development"].get("branch_published") is not False or
            development._remote_head(location, configuration["publish_url"], item["development"]["publish_ref"]) is not None):
        raise ProjectError("Git transformation requires its own unpublished generation branch")
    return location


def complete_writer(root, files, item, role):
    current = state(item)
    location = _validate_generation(root, files, item, base=current["rebase"]["target"] if role == "rebase" else None)
    if development._git(location, "rev-parse", "--verify", "REBASE_HEAD", check=False).returncode == 0:
        raise ProjectError("rebase is still in progress")
    actual = development.snapshot(location)
    if role == "baseline":
        if not actual["clean"]:
            raise ProjectError("baseline integration must finish as a clean committed baseline")
        if development._git(location, "merge-base", "--is-ancestor", current["formal_base"], "HEAD", check=False).returncode:
            raise ProjectError("baseline omits the pinned formal base")
        for value in current["inputs"].values():
            if value["repository"] == item["repository"] and development._git(location, "merge-base", "--is-ancestor", value["commit"], "HEAD", check=False).returncode:
                raise ProjectError("baseline omits a frozen prerequisite")
        target = actual["head"]
        current.update(phase="speculative", baseline=target)
        item["status"], item["owner"] = "in_progress", None
    else:
        target = current["rebase"]["target"]
        already_reset = actual["head"] == target
        if not actual["clean"] and not already_reset:
            raise ProjectError("rebase must finish clean before exposing its result for review")
        if development._git(location, "merge-base", "--is-ancestor", target, "HEAD", check=False).returncode:
            raise ProjectError("converged work is not based on the formal target")
        if development._git(location, "merge-base", "--is-ancestor", current["rebase"]["source"]["commit"], "HEAD", check=False).returncode == 0:
            raise ProjectError("rebase retained the speculative source snapshot instead of replaying own changes")
        # This is the isolated unpublished convergence branch. The original source
        # and immutable snapshot retain recovery; expose own work as dirty for acceptance.
        development._git(location, "reset", "--mixed", target)
        current["rebased"] = True
    item["development"]["base_commit"] = target
    development._git(location, "config", "branch." + item["development"]["branch"] + ".project-base-commit", target)
    workflow._invalidate_implementation(item)
    item["design"].pop("review", None)


def validate(item):
    captured = (item.get("workflow") or {}).get("autonomy", {}).get("snapshots", {})
    if not isinstance(captured, dict):
        raise ProjectError("snapshots must be an object")
    for key, value in captured.items():
        if (not isinstance(value, dict) or value.get("id") != key or not isinstance(key, str) or not workflow.TICKET.fullmatch(key) or
                value.get("item") != item["id"] or value.get("kind") != "predevelopment-snapshot" or
                value.get("status") not in {"planned", "committed", "published"}):
            raise ProjectError("invalid snapshot identity or state")
        for field in ("tree", "head") + (("commit",) if value["status"] != "planned" else ()):
            if not isinstance(value.get(field), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value[field]):
                raise ProjectError("invalid snapshot Git identity")
        for field in ("url", "ref", "branch", "report", "repository", "artifact_sha256", "authorization_source"):
            workflow._text(value.get(field), "snapshot " + field)
        if (value["report"] != "workitems/" + item["id"] + "/records/" + key + ".md" or
                not re.fullmatch(r"[0-9a-f]{64}", value["artifact_sha256"]) or
                not isinstance(value.get("binding"), dict) or
                not _matches(r"[0-9a-f]{64}", value.get("binding", {}).get("project_sha256")) or
                not value["ref"].startswith("refs/heads/") or
                not isinstance(value.get("prerequisites"), dict) or any(
                    not runtime._nonempty(dependency) or not _matches(workflow.TICKET.pattern, record_id)
                    for dependency, record_id in value.get("prerequisites", {}).items())):
            raise ProjectError("invalid frozen snapshot evidence or authorization")
    latest = (item.get("workflow") or {}).get("autonomy", {}).get("latest_snapshot")
    if latest is not None and (not isinstance(latest, str) or latest not in captured or captured[latest]["status"] != "published"):
        raise ProjectError("latest snapshot must reference a published immutable snapshot")
    current = state(item)
    if current is None:
        return
    if (not isinstance(current, dict) or not isinstance(current.get("phase"), str) or current.get("phase") not in PHASES or
            not isinstance(current.get("inputs"), dict) or not current.get("inputs") or
            item["id"] in current["inputs"] or not _matches(workflow.TICKET.pattern, current.get("generation")) or
            not _matches(r"[0-9a-f]{40}|[0-9a-f]{64}", current.get("formal_base")) or
            not runtime._nonempty(current.get("authorization_source")) or not _matches(r"[0-9a-f]{64}", current.get("project_sha256")) or
            not isinstance(current.get("retained_developments"), list) or any(not isinstance(record, dict) for record in current.get("retained_developments", []))):
        raise ProjectError("invalid predevelopment phase or pinned prerequisites")
    for identifier, value in current["inputs"].items():
        if (not isinstance(value, dict) or value.get("item") != identifier or value.get("status") != "published" or
                not value.get("commit") or not isinstance(value.get("id"), str)):
            raise ProjectError("predevelopment requires published same-item prerequisite snapshots")
        # Validate each pinned record with the same shape as its upstream root.
        validate({"id": identifier, "workflow": {"autonomy": {"snapshots": {value["id"]: value}}}})
        if any(current["inputs"].get(key, {}).get("id") != record_id for key, record_id in value["prerequisites"].items()):
            raise ProjectError("pinned prerequisite closure omits or changes an inherited snapshot")
    if current["phase"] in {"reconciling", "formal"}:
        plan = current.get("rebase") or {}
        if (not isinstance(plan, dict) or not _matches(workflow.TICKET.pattern, plan.get("generation")) or
                any(not _matches(r"[0-9a-f]{40}|[0-9a-f]{64}", plan.get(key)) for key in ("old_base", "target")) or
                not isinstance(plan.get("source"), dict) or plan["source"] != captured.get(plan["source"].get("id"))):
            raise ProjectError("invalid formal convergence plan")
        if current["phase"] == "formal" and (current.get("rebased") is not True or
                (item.get("development") or {}).get("base_commit") != plan["target"]):
            raise ProjectError("formal predevelopment requires completed rebase on its recorded target")

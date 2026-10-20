"""Explicit control-claim transfer; conversation identities remain audit evidence.

known-limit: claim tokens fence project publication. The advancing agent owns
host jobs and source write coordination, including isolation when an old host is
unreachable; project state does not attest that arbitrary processes stopped.
"""
import copy
from pathlib import Path
import secrets
import shlex
import sys

try:
    import project_runtime as runtime
    import project_store as store
    import project_workflow as workflow
except ImportError:
    from . import project_runtime as runtime, project_store as store, project_workflow as workflow

ProjectError = runtime.ProjectError


def claim_token(item):
    state = item.get("workflow") or {}
    return ((item.get("owner") or {}).get("token") or
            (state.get("autonomy", {}).get("authorization") or {}).get("claim_token") or
            (state.get("lifecycle", {}).get("handoff") or {}).get("claim_token"))


def authorized(item, identity):
    authorization = (item.get("workflow", {}).get("autonomy") or {}).get("authorization") or {}
    if not authorization:
        handoff = (item.get("workflow", {}).get("lifecycle") or {}).get("handoff")
        return not handoff or handoff_authorized(handoff, identity)
    if authorization.get("claim_token"):
        return authorization["claim_token"] == identity.get("token")
    # Existing schema-v2 authorizations have no claim token. The first explicit
    # authorization/transfer binds one; until then retain their original guard.
    return authorization.get("coordinator") == identity.get("session")


def handoff_authorized(handoff, identity):
    return (handoff["claim_token"] == identity.get("token") if handoff.get("claim_token") else
            handoff["to"] == identity.get("session"))


def _event(event):
    required = {"id", "source", "from", "to", "coordinator", "created_at"}
    if not isinstance(event, dict) or not required <= set(event) or set(event) - required - {"attempt", "writers_stopped_source"} or not workflow.TICKET.fullmatch(str(event.get("id", ""))):
        raise ProjectError("invalid control-transfer event")
    for key in ("source", "created_at"):
        workflow._text(event[key], "control-transfer " + key)
    target = event["to"]
    if not isinstance(target, dict) or set(target) != {"machine", "session", "token"}:
        raise ProjectError("control transfer requires its actual target identity")
    for value in target.values():
        workflow._text(value, "control-transfer target")
    if event.get("attempt") is not None and not workflow.TICKET.fullmatch(str(event.get("attempt"))):
        raise ProjectError("control transfer requires an exact attempt identity")
    if event.get("writers_stopped_source") is not None:
        workflow._text(event.get("writers_stopped_source"), "actual stopped-writer evidence")
    return target


def validate(item):
    events = item.get("workflow", {}).get("control_transfers", {})
    if not isinstance(events, dict):
        raise ProjectError("control transfers must be an object")
    for key, event in events.items():
        _event(event)
        if key != event["id"]:
            raise ProjectError("control transfer identity differs from its audit key")


def transferred(item, event):
    """The complete allowed state change, also checked at the publication boundary."""
    target = _event(event)
    result = copy.deepcopy(item)
    state = result.setdefault("workflow", {}).setdefault("autonomy", {})
    authorization = state.get("authorization") or {}
    if event["from"] != item.get("owner") or event["coordinator"] != authorization.get("coordinator"):
        raise ProjectError("control transfer no longer matches the current claim")
    workflow._autonomy_module().release_execution_state(result)
    result["owner"] = copy.deepcopy(target)
    if authorization:
        authorization.update(coordinator=target["session"], claim_token=target["token"])
    lifecycle = result["workflow"].get("lifecycle") or {}
    if lifecycle.get("handoff"):
        lifecycle["handoff"].update(to=target["session"], claim_token=target["token"])
    result["workflow"].setdefault("control_transfers", {})[event["id"]] = copy.deepcopy(event)
    return result


def _writes(files, item):
    writes = store.write_item(files, item)
    receipt = store.receipt(files, item["id"])
    if receipt and receipt.get("state") == "verified":
        receipt = copy.deepcopy(receipt)
        receipt["content_sha256"] = runtime._business_digest(store.apply_writes(files, writes), item["id"])
        writes.update(store.write_receipt(files, item["id"], receipt))
    return writes


def validate_transfer(bundle, current, prospective):
    marker = bundle.get("ownership_transfer")
    if not isinstance(marker, dict) or set(marker) != {"item", "id"} or not store.is_v2(current):
        raise ProjectError("invalid ownership-transfer publication")
    identifier = marker["item"]
    before, after = store.item(current, identifier), store.item(prospective, identifier)
    event = (after.get("workflow", {}).get("control_transfers") or {}).get(marker["id"])
    expected = transferred(before, event)
    if expected != after or event["to"]["session"] != bundle["session"] or event["to"]["token"] != bundle["token"]:
        raise ProjectError("control transfer must preserve the exact contract, source and evidence")
    writes = _writes(current, expected)
    if any(name not in writes or value != writes[name] for name, value in bundle["writes"].items()):
        raise ProjectError("control transfer cannot publish unrelated changes")
    return identifier


def _save_identity(root, identifier, identity):
    path = root / ".project-local/identities" / (workflow._hash(identity["session"]) + ".yaml")
    runtime._no_links(root, path.relative_to(root).as_posix())
    saved = store.load_yaml(path.read_bytes(), str(path))
    if saved["session"] != identity["session"]:
        raise ProjectError("control identity belongs to another conversation")
    saved.setdefault("claims", {})[identifier] = identity["token"]
    runtime._write_journal(path, saved)


def _rotate_identity(root, identifier):
    # A conversation can receive control repeatedly. Never revive its earlier
    # token: an old signed ticket or publication must remain fenced after A-B-A.
    # Persist before publishing so exact journal recovery also survives a crash.
    with runtime._project_lock(root):
        identity = workflow._identity(root, item=identifier)
        identity["token"] = secrets.token_hex(32)
        _save_identity(root, identifier, identity)
        return identity


def _finish_transfer(root, item, identity, continuation, result):
    try:
        with runtime._project_lock(root):
            current = store.item(runtime._working_files(root), item["id"])
            if claim_token(current) != identity["token"] or not authorized(current, identity):
                raise ProjectError("control claim changed before local identity recording")
            _save_identity(root, item["id"], identity)
    except (ProjectError, OSError) as error:
        return {**result, "status": "blocked", "code": "takeover_local_identity_pending", "error": str(error),
                "next_command": continuation, "continuation_command": continuation}
    return result


def _pending(root, identifier):
    """Expose exact immutable recovery commands, independent of a live conversation."""
    try:
        import project
    except ImportError:
        from . import project
    runtime._no_links(root, ".project-local/publish")
    pending = []
    for journal in sorted((root / ".project-local/publish").glob("*/journal.json")):
        runtime._no_links(root, journal.relative_to(root).as_posix())
        if runtime.publication_disposition(runtime.read_json(journal)) in {"published", "rejected_before_push"}:
            continue
        bundle_path = journal.parent / "bundle.json"
        runtime._no_links(root, bundle_path.relative_to(root).as_posix())
        bundle = runtime.read_json(bundle_path)
        if identifier not in project._affected_identifiers(bundle.get("writes", {})):
            continue
        pending.append((journal, bundle))
    if len(pending) > 1:
        return {"status": "blocked", "code": "takeover_publication_ambiguous", "journals": [str(path) for path, _ in pending]}
    if pending:
        journal, bundle = pending[0]
        identity_file = workflow._local(root, "control-recovery", journal.parent.name) / "identity.json"
        runtime._no_links(root, identity_file.relative_to(root).as_posix())
        runtime._write_journal(identity_file, {key: bundle[key] for key in ("session", "token")})
        command = [sys.executable, str(Path(__file__).with_name("project.py")), "--root", str(root),
                   "resume", "--identity-file", str(identity_file), "--journal", str(journal)]
        return {"status": "blocked", "code": "takeover_publication_pending", "journal": str(journal),
                "next_command": shlex.join(command)}
    return None


def takeover(root, selector, *, approval_source, publish=None):
    workflow._text(approval_source, "explicit user control-transfer authorization")
    root = runtime.find_project(root)
    files = workflow._snapshot(root)
    identifier = workflow._resolve(store.items(files), selector)
    item = store.item(files, identifier)
    command = [sys.executable, str(Path(__file__).with_name("project.py")), "--root", str(root),
               "takeover", identifier, "--approval-source", approval_source]
    continuation = shlex.join(command)
    pending = _pending(root, identifier)
    if pending:
        return {**pending, "continuation_command": continuation}
    receipt = store.receipt(files, identifier)
    if receipt and receipt.get("state") in {"pending", "unknown"}:
        owner = item.get("owner") or {}
        if not owner.get("token") or not owner.get("session"):
            raise ProjectError("unsettled project synchronization has no recoverable control identity")
        identity_file = workflow._local(root, "control-recovery", "sync-" + identifier) / "identity.json"
        runtime._no_links(root, identity_file.relative_to(root).as_posix())
        runtime._write_journal(identity_file, {key: owner[key] for key in ("session", "token")})
        recovery = [sys.executable, str(Path(__file__).with_name("project.py")), "--root", str(root),
                    "resume", "--identity-file", str(identity_file), "--item", identifier]
        return {"status": "blocked", "code": "takeover_sync_pending", "next_command": shlex.join(recovery),
                "continuation_command": continuation}
    if item.get("status") in {"done", "cancelled"} or item.get("archived"):
        raise ProjectError("inactive work item does not need a control claim")
    identity = workflow._identity(root, item=identifier)
    state = (item.get("workflow", {}).get("autonomy") or {})
    legacy = any(key in state for key in ("current", "executions", "next_role", "blocker"))
    if not legacy and (item.get("owner") or {}).get("token") == identity["token"] and authorized(item, identity):
        return _finish_transfer(root, item, identity, continuation, {"status": "no_op", "item": identifier})
    identity = _rotate_identity(root, identifier)
    event = {"id": secrets.token_hex(16), "source": approval_source, "from": copy.deepcopy(item.get("owner")),
             "to": copy.deepcopy(identity), "coordinator": state.get("authorization", {}).get("coordinator"),
             "created_at": workflow._now()}
    item = transferred(item, event)
    writes = _writes(files, item)
    checks = workflow._checks(files, item, "context-update")
    request = {**identity, "ownership_transfer": {"item": identifier, "id": event["id"]}}
    prospective = store.apply_writes(files, writes)
    bundle = {"session": identity["session"], "token": identity["token"], "writes": writes,
              "ownership_transfer": request["ownership_transfer"]}
    validate_transfer(bundle, files, prospective)
    errors = runtime._validate_files(root, prospective)
    if errors:
        raise ProjectError("invalid transferred project state: " + "; ".join(errors))
    result = workflow._publish(root, writes, request, "Take over work item " + identifier, checks, publish)
    response = {**result, "item": identifier, "transfer": event["id"], "next_action": "recompute_readiness"}
    if result.get("status") not in {"published", "no_op"}:
        response["continuation_command"] = continuation
        journal = (result.get("recovery") or {}).get("journal")
        identity_file = result.get("identity_file") or (result.get("recovery") or {}).get("identity_file")
        if journal and identity_file:
            response["next_command"] = shlex.join([sys.executable, str(Path(__file__).with_name("project.py")),
                "--root", str(root), "resume", "--identity-file", str(identity_file), "--journal", journal])
        return response
    return _finish_transfer(root, item, identity, continuation, response)

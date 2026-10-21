#!/usr/bin/env python3
"""One project command for bounded reads, guarded Git batches and Aone recovery."""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import shlex
import sys
import uuid

try:
    import project_context as context
    import project_operations as operations
    import project_runtime as runtime
    import project_store as store
    import project_identity
    from project_aone import AoneAdapter
    from project_init import ProjectInitError, init_project
except ImportError:  # package entrypoint
    from . import project_context as context, project_operations as operations, project_runtime as runtime, project_store as store, project_identity
    from .project_aone import AoneAdapter
    from .project_init import ProjectInitError, init_project


ProjectError = runtime.ProjectError


def _text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _hash(value):
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _json_input(path):
    if path == "-":
        return runtime._decode_json(sys.stdin.buffer.read(), "stdin request")
    return runtime.read_json(Path(path))


def _local_directory(root, *parts):
    current = root
    for part in (".project-local", *parts):
        current = current / part
        if current.is_symlink():
            raise ProjectError(f"local state cannot use a symlink: {current}")
        current.mkdir(mode=0o700, exist_ok=True)
    return current


def _save_identity(root, request):
    directory = _local_directory(root, "requests", uuid.uuid4().hex)
    path = directory / "identity.json"
    runtime._write_journal(path, {key: request[key] for key in ("session", "token", "machine")})
    return path


def _error_details(error):
    message = str(error)
    result = {"error": message}
    if isinstance(error, runtime.ProjectPermissionError):
        result.update(code="host_permission_required", permission_path=error.path,
                      required_access="write", action="request_host_permission")
    marker = "retained bundle/journal: "
    if marker in message:
        directory = Path(message.rsplit(marker, 1)[1].strip())
        result["publication_recovery"] = {"action": "resume", "directory": str(directory),
                                          "journal": str(directory / "journal.json"),
                                          "bundle": str(directory / "bundle.json")}
    return result


def _publish(root, bundle):
    directory = _local_directory(root, "requests", uuid.uuid4().hex)
    path = directory / "bundle.json"
    runtime._write_journal(path, bundle)
    return runtime.publish(root, path)


def _affected_identifiers(writes):
    result = set()
    for name in writes:
        identifier = runtime._item_for_path(name)
        if identifier:
            result.add(identifier)
    return result


def _bundle(files, writes, request, message, identifiers, checks=None):
    guarded = {store.project_path(files): _hash(files[store.project_path(files)])}
    identifiers = set(identifiers) | _affected_identifiers(writes)
    for identifier in sorted(identifiers):
        prefix = f"workitems/{identifier}/"
        for path in files:
            if path.startswith(prefix):
                guarded[path] = _hash(files[path])
        for path in (store.item_path(files, identifier), store.receipt_path(files, identifier)):
            guarded[path] = _hash(files.get(path))
        if store.is_v2(files):
            name = f".project/state/{identifier}.yaml"
            guarded[name] = _hash(files.get(name))
    for path in writes:
        guarded[path] = _hash(files.get(path))
    # Caller checks bind the edit to its original read, never to this later read.
    if checks is not None:
        guarded.update(checks)
    result = {"checks": guarded, "writes": writes, "session": request["session"],
              "token": request["token"], "message": message}
    if "ownership_transfer" in request:
        result["ownership_transfer"] = request["ownership_transfer"]
    return result


def _sync_files(root, identifiers):
    # State and receipt authority must be included for both physical formats.
    paths = [".project"]
    paths.extend(f"workitems/{identifier}" for identifier in identifiers)
    return runtime._working_files(root, paths=tuple(paths))


def _record(files, identifier):
    return store.item(files, identifier)


def _receipt(files, identifier):
    return store.receipt(files, identifier)


def _recovery(request, identifiers, identity_file=None):
    result = {"action": "resume", "session": request["session"], "items": identifiers}
    if identity_file:
        result["identity_file"] = str(identity_file)
    else:
        result["token"] = request["token"]
    return result


def _sync_conflict(message):
    return any(marker in message for marker in ("drift", "mismatch", "without recreating", "reconcil", "conflict",
                                                "unsupported", "differs", "does not have", "no pending/unknown",
                                                "requires installed"))


def _sync(root, identifiers, request, adapter, source_commit=None, identity_file=None, project_record=None):
    """Batch write-ahead plans, then batch verified receipts; never retry a write."""
    # known-limit: interruption can leave an unsent create journaled as unknown.
    # It then needs reconciliation; avoiding that requires server idempotency or
    # a separate per-item checkpoint, rather than guessing that no write occurred.
    files = _sync_files(root, identifiers)
    if store.project(files) != project_record:
        raise ProjectError("project configuration changed while synchronizing; reconcile before resume")
    plans, failures, writes = {}, [], {}
    for identifier in identifiers:
        try:
            item, receipt = _record(files, identifier), _receipt(files, identifier)
            owner = item.get("owner")
            if not owner or owner.get("session") != request["session"] or owner.get("token") != request["token"]:
                raise ProjectError(f"item {identifier} does not have this session/token's sync owner")
            if not receipt or receipt.get("state") not in {"pending", "unknown"}:
                raise ProjectError(f"item {identifier} has no pending/unknown sync intent")
            if receipt["content_sha256"] != runtime._business_digest(files, identifier):
                raise ProjectError(f"item {identifier} business digest differs from its durable intent")
            if source_commit is not None:
                receipt["git_source_commit"] = source_commit
            elif receipt.get("git_source_commit") is None and receipt["state"] == "pending":
                # The first pending checkpoint cannot contain its own commit ID.
                # A stopped coordinator recovers that ID from this receipt's last change.
                receipt["git_source_commit"] = runtime._git_text(
                    root, "log", "-1", "--format=%H", "--", store.receipt_path(files, identifier))
            writes.update(store.write_receipt(files, identifier, receipt))
            plan = adapter.prepare_sync(item, files, receipt)
            # Do not recursively embed previous journals in future operation plans.
            durable_plan = {key: value for key, value in plan.items() if key != "receipt"}
            receipt.update(state="unknown", operation=durable_plan)
            writes.update(store.write_receipt(files, identifier, receipt))
            plans[identifier] = plan
        except (ProjectError, OSError, ValueError) as exc:
            failures.append({"item": identifier, "stage": "prepare_sync", "error": str(exc)})
    checkpoint = None
    writes = {path: value for path, value in writes.items() if value.encode("utf-8") != files.get(path)}
    if writes:
        # Every possible mutation is durable on the authoritative remote first.
        checkpoint = _publish(root, _bundle(files, writes, request, "Prepare Aone operations", plans))
    verified = {}
    for identifier, plan in plans.items():
        try:
            receipt = adapter.execute(plan)
            if (receipt.get("state") != "verified" or
                    receipt.get("intent_id") != plan["receipt"]["intent_id"] or
                    receipt.get("content_sha256") != plan["receipt"]["content_sha256"]):
                raise ProjectError("adapter did not verify the intended business revision")
            verified[identifier] = receipt
        except (ProjectError, OSError, ValueError) as exc:
            failures.append({"item": identifier, "stage": "execute", "error": str(exc)})
    if verified:
        files = _sync_files(root, identifiers)
        if store.project(files) != project_record:
            raise ProjectError("project configuration changed while synchronizing; retain unknown outcomes")
        writes = {}
        for identifier, receipt in verified.items():
            item = _record(files, identifier)
            durable = _receipt(files, identifier)
            if (not durable or durable.get("intent_id") != receipt["intent_id"] or
                    runtime._business_digest(files, identifier) != receipt["content_sha256"]):
                raise ProjectError(f"item {identifier} changed while synchronizing; retain unknown intent")
            item["owner"] = copy.deepcopy(receipt.get("release_owner"))
            writes.update(store.write_item(files, item))
            writes.update(store.write_receipt(files, identifier, receipt))
        checkpoint = _publish(root, _bundle(files, writes, request, "Verify Aone synchronization", verified))
    blocked = store.is_v2(files) and any(_sync_conflict(failure["error"]) for failure in failures)
    result = {"status": "blocked" if blocked else "partial" if failures else "published",
              "synchronized": sorted(verified), "failures": failures}
    if blocked:
        result.update(code="sync_conflict", action="blocked")
    if checkpoint:
        result.update({key: checkpoint[key] for key in ("commit", "verified_remote_commit", "journal")})
    if failures and not blocked:
        result["recovery"] = _recovery(request, [failure["item"] for failure in failures], identity_file)
    return result


def publish_changes(root, writes, identity, message, checks=None, *, adapter_factory=AoneAdapter):
    """Publish physical writes through the existing guarded Git/Aone coordinator.

    An unresolved receipt is immutable until resume reconciles it. Backend writes
    follow a remote write-ahead checkpoint and their readback is published before
    the original owner is restored.
    """
    root = runtime.find_project(root)
    if not isinstance(identity, dict) or any(not runtime._nonempty(identity.get(key))
                                             for key in ("session", "token", "machine")):
        raise ProjectError("publication identity requires session, token and machine")
    if not isinstance(writes, dict) or any(value is not None and not isinstance(value, str)
                                          for value in writes.values()):
        raise ProjectError("publication writes must map physical paths to text or null")
    if not runtime._nonempty(message):
        raise ProjectError("publication message must be nonempty")
    files = runtime._working_files(root)
    identifiers = sorted(_affected_identifiers(writes))
    pending = [identifier for identifier in identifiers
               if (receipt := _receipt(files, identifier)) and receipt.get("state") in {"pending", "unknown"}]
    if pending:
        intended = store.apply_writes(files, writes)
        same_intent = all(_receipt(files, identifier)["content_sha256"] ==
                          runtime._business_digest(intended, identifier) and
                          (_record(files, identifier).get("owner") or {}).get("session") == identity["session"] and
                          (_record(files, identifier).get("owner") or {}).get("token") == identity["token"]
                          for identifier in pending)
        # A fixed ticket may finish the exact retained intent after interruption.
        # New business content must wait until the original intent is reconciled.
        same_intent = same_intent and all(
            _record(intended, identifier).get("owner") == _receipt(files, identifier).get("release_owner")
            for identifier in pending)
        same_intent = same_intent and all(
            runtime._item_for_path(name) in pending or
            (value.encode("utf-8") if value is not None else None) == files.get(name)
            for name, value in writes.items())
        if same_intent and store.project(intended) == store.project(files):
            for name, expected in (checks or {}).items():
                if name not in writes and _hash(files.get(name)) != expected:
                    raise ProjectError("byte check conflict: " + name)
            result = resume(root, identity["session"], identity["token"], pending,
                            adapter_factory=adapter_factory)
            result["items"] = identifiers
            return result
        return {"status": "partial", "code": "sync_unresolved", "action": "resume",
                "recovery": _recovery(identity, pending)}
    # Check the original read even for no-op input; a stale successful no-op would
    # allow a ticket to finish without validating what its author actually saw.
    if checks is not None:
        for name, expected in checks.items():
            if _hash(files.get(name)) != expected:
                raise ProjectError("byte check conflict: " + name)
    changes = {name: value for name, value in writes.items()
               if (value.encode("utf-8") if value is not None else None) != files.get(name)}
    if not changes:
        return {"status": "no_op", "items": identifiers}
    prospective = store.apply_writes(files, changes)
    config = store.project(prospective)
    sync_ids, adapter = [], None
    if config.get("backends", {}).get("aone") is not None and identifiers and "ownership_transfer" not in identity:
        adapter = adapter_factory(config)
        for identifier in identifiers:
            if store.item_path(prospective, identifier) not in prospective:
                raise ProjectError("backend-synchronized workitems cannot be deleted")
            old = _receipt(files, identifier)
            # Reuse the immutable source revision when comparing the actual
            # managed projection. Context/log content and owner-only changes do
            # not force a new Git link or a meaningless backend mutation.
            unchanged = bool(old and old.get("state") == "verified" and
                             isinstance(old.get("baseline_fields"), dict) and
                             adapter.desired(_record(prospective, identifier), prospective,
                                             old.get("git_source_commit")) == old["baseline_fields"])
            if unchanged:
                digest = runtime._business_digest(prospective, identifier)
                if old["content_sha256"] != digest:
                    receipt = copy.deepcopy(old)
                    receipt["content_sha256"] = digest
                    changes.update(store.write_receipt(prospective, identifier, receipt))
                continue
            item = _record(prospective, identifier)
            owner = item.get("owner")
            if owner and (owner.get("session"), owner.get("token")) != (identity["session"], identity["token"]):
                raise ProjectError(f"item {identifier} is owned by another session/token")
            receipt = copy.deepcopy(old) if old else {}
            receipt.update(intent_id=uuid.uuid4().hex,
                           content_sha256=runtime._business_digest(prospective, identifier), state="pending",
                           external_id=receipt.get("external_id"), baseline_fields=receipt.get("baseline_fields"),
                           git_source_commit=None, checked_at=None, release_owner=copy.deepcopy(owner))
            receipt.pop("operation", None)
            item["owner"] = {key: identity[key] for key in ("machine", "session", "token")}
            changes.update(store.write_item(prospective, item))
            changes.update(store.write_receipt(prospective, identifier, receipt))
            sync_ids.append(identifier)
    if sync_ids:
        adapter.preflight()
    identity_file = _save_identity(root, identity)
    stage = "business_publish"
    try:
        publication = _publish(root, _bundle(files, changes, identity, message, identifiers, checks))
        if not sync_ids:
            return {"status": "published", "items": identifiers, "identity_file": str(identity_file), **publication}
        stage = "synchronize"
        result = _sync(root, sync_ids, identity, adapter, publication["commit"], identity_file, config)
        result.update(items=identifiers, identity_file=str(identity_file))
        return result
    except (ProjectError, OSError, ValueError) as exc:
        details = _error_details(exc)
        recovery = _recovery(identity, sync_ids, identity_file)
        if stage == "business_publish" and details.get("publication_recovery"):
            recovery["journal"] = details["publication_recovery"]["journal"]
        return {"status": "partial", "code": "publication_incomplete", "action": "resume",
                "stage": stage, **details, "recovery": recovery}


def apply(root, request, *, dry_run=False, adapter_factory=AoneAdapter):
    root = runtime.find_project(root)
    if not isinstance(request, dict):
        raise ProjectError("request must be an object")
    request = copy.deepcopy(request)
    request["session"] = request.get("session") or project_identity.current_session()
    if not runtime._nonempty(request["session"]):
        raise ProjectError("request.session is required when the execution session is unavailable")
    if request.get("token") is None:
        request["token"] = uuid.uuid4().hex
    request["machine"] = request.get("machine") or socket.gethostname()
    if store.is_v2(runtime._working_files(root, paths=(".project",))):
        raise ProjectError("v2 requires begin/finish; handwritten apply requests are not accepted")
    prepared = operations.prepare(root, request)
    summary_keys = ("changes", "items", "required_actions", "aliases", "item_summaries", "dependency_effects")
    summary = {key: prepared[key] for key in summary_keys}
    if dry_run:
        return {"status": "dry_run", **summary}
    if prepared["bundle"] is None:
        entries = [{"id": record["id"], "metadata": record}
                   for path, value in prepared["files"].items()
                   if path.startswith("workitems/") and path.endswith("/item.json")
                   for record in [runtime._decode_json(value, path)]]
        pending = set()
        for operation in request["operations"]:
            selector = operation.get("item")
            if selector:
                identifier = context._resolve_item(entries, selector)["id"]
            elif operation.get("op") == "document" and operation.get("path"):
                identifier = runtime._item_for_path(operation["path"])
            else:
                identifier = None
            receipt = _receipt(prepared["files"], identifier) if identifier else None
            if receipt and receipt["state"] in {"pending", "unknown"}:
                pending.add(identifier)
        if pending:
            return {"status": "partial", **summary,
                    "error": "The requested business content is unchanged but its backend intent is unresolved",
                    "recovery": _recovery(request, sorted(pending))}
        return {"status": "no_op", **summary}
    bundle = copy.deepcopy(prepared["bundle"])
    project = runtime._decode_json(prepared["files"][".project/project.json"], ".project/project.json")
    if project.get("backends", {}).get("aone") is None:
        owned = any((_record(prepared["files"], identifier).get("owner") or {}).get("token") == request["token"]
                    for identifier in prepared["items"])
        identity_file = _save_identity(root, request) if owned else None
        try:
            result = {"status": "published", **summary, **_publish(root, bundle)}
        except (ProjectError, OSError, ValueError) as exc:
            result = {"status": "failed", **summary, **_error_details(exc)}
        if identity_file:
            result["identity_file"] = str(identity_file)
        return result
    identifiers = []
    for identifier in prepared["items"]:
        sync = prepared["sync_context"][identifier]
        old = sync["receipt"]
        if old and old["state"] in {"pending", "unknown"}:
            raise ProjectError(f"item {identifier} has unresolved {old['state']} sync; use resume before apply")
        if not sync["business_changed"] and old and old["state"] == "verified":
            continue
        identifiers.append(identifier)
        path = f"workitems/{identifier}/item.json"
        item = runtime._decode_json(prepared["files"][path], path)
        receipt = copy.deepcopy(old) if old else {}
        receipt.update(intent_id=uuid.uuid4().hex, content_sha256=prepared["business_digests"][identifier],
                       state="pending", external_id=receipt.get("external_id"),
                       baseline_fields=receipt.get("baseline_fields"), git_source_commit=None,
                       checked_at=None, release_owner=copy.deepcopy(item.get("owner")))
        receipt.pop("operation", None)
        item["owner"] = {key: request[key] for key in ("machine", "session", "token")}
        bundle["writes"][path] = _text(item)
        bundle["writes"][f".project/sync/{identifier}.json"] = _text(receipt)
    adapter = adapter_factory(project) if identifiers else None
    if adapter:
        adapter.preflight()
    identity_file = _save_identity(root, request) if identifiers else None
    stage = "business_publish"
    try:
        publication = _publish(root, bundle)
        stage = "synchronize"
        if not identifiers:
            return {"status": "published", **summary, **publication}
        result = _sync(root, identifiers, request, adapter, publication["commit"], identity_file, project)
        result.update(summary)
        result["identity_file"] = str(identity_file)
        return result
    except (ProjectError, OSError, ValueError) as exc:
        recovery = _recovery(request, identifiers, identity_file) if stage == "synchronize" else {
            "action": "inspect_publication", "identity_file": str(identity_file) if identity_file else None}
        return {"status": "partial", "stage": stage, **summary, **_error_details(exc),
                "recovery": recovery,
                "notice": "Inspect the retained Git publication journal before resuming an ambiguous publication."}


def resume(root, session, token, selectors=None, *, adapter_factory=AoneAdapter):
    root = runtime.find_project(root)
    if not runtime._nonempty(session) or not runtime._nonempty(token):
        raise ProjectError("resume requires the original nonempty session and token")
    recovered = runtime.resume_publication(root, session=session, token=token)
    if recovered.get("status") not in {"no_op", "published"}:
        return recovered
    runtime.refresh_project(root)
    snapshot = runtime._working_files(root)
    entries = [{"id": identifier, "metadata": record} for identifier, record in store.items(snapshot).items()]
    if selectors:
        selected = [context._resolve_item(entries, selector) for selector in selectors]
    else:
        selected = [entry for entry in entries if (entry["metadata"].get("owner") or {}).get("session") == session
                    and (entry["metadata"].get("owner") or {}).get("token") == token]
    identifiers = []
    for entry in selected:
        identifier, owner = entry["id"], entry["metadata"].get("owner")
        if not owner or owner.get("session") != session or owner.get("token") != token:
            raise ProjectError(f"item {identifier} is owned by another session/token")
        receipt = _receipt(_sync_files(root, [identifier]), identifier)
        if receipt and receipt.get("state") in {"pending", "unknown"}:
            identifiers.append(identifier)
        elif selectors:
            raise ProjectError(f"item {identifier} has no pending/unknown sync intent")
    identifiers = sorted(set(identifiers))
    if not identifiers:
        return ({**recovered, "synchronized": []} if recovered.get("status") == "published" else
                {"status": "no_op", "synchronized": []})
    project = store.project(snapshot)
    if project.get("backends", {}).get("aone") is None:
        raise ProjectError("pending synchronization cannot resume with Aone disabled")
    request = {"session": session, "token": token}
    try:
        adapter = adapter_factory(project)
        adapter.preflight()
        return _sync(root, identifiers, request, adapter, project_record=project)
    except (ProjectError, OSError, ValueError) as exc:
        if store.is_v2(snapshot) and _sync_conflict(str(exc)):
            return {"status": "blocked", "code": "sync_conflict", "action": "blocked", **_error_details(exc)}
        return {"status": "partial", **_error_details(exc),
                "code": "synchronization_incomplete", "action": "resume",
                "recovery": _recovery(request, identifiers)}


def _query(args):
    documents = getattr(args, "documents", None)
    source = vars(args).copy()
    source["path"] = args.root
    result = context.command(argparse.Namespace(**source))
    if args.command == "show" and documents is not None:
        root = runtime.find_project(args.root)
        permitted = {Path(path).relative_to(f"workitems/{result['metadata']['id']}").as_posix(): path
                     for path in result["body_paths"]}
        names = sorted(permitted) if not documents else documents
        output = {}
        for name in names:
            if name not in permitted:
                raise ProjectError(f"unknown selected document: {name}")
            path = permitted[name]
            data = context._read_bytes(root, root / path)
            output[path] = {"sha256": _hash(data), "text": data.decode("utf-8")}
        result["documents"] = output
    if args.command == "list":
        result["results"] = [_item_summary(record) for record in result["results"]]
    elif args.command == "show":
        root = runtime.find_project(args.root)
        files = runtime._working_files(root)
        if store.is_v2(files):
            result["workflow_gates"] = _module("project_workflow").gates(
                files, result["metadata"], project_identity.current_session())
        result["readiness_scope"] = "dependency_delivery_and_open_fixes"
        result["metadata"] = _item_summary(result["metadata"])
    return _redact(result)


def _item_summary(record):
    result = {key: record[key] for key in ("id", "title", "kind", "status", "archived", "repository", "depends_on")
              if key in record}
    for key, allowed in {"design": ("state", "version"), "delivery": ("status", "required"),
                         "owner": ("session", "machine"), "development": ("branch", "worktree")}.items():
        value = record.get(key)
        if isinstance(value, dict):
            result[key] = {name: value[name] for name in allowed if name in value}
    return result


def _progress_item(record):
    """Compact progress facts, including predevelopment markers omitted from status summaries."""
    result = _item_summary(record)
    development = record.get("development") or {}
    review = development.get("review") if isinstance(development, dict) else None
    if isinstance(review, dict) and review.get("result"):
        result.setdefault("development", {})["review_result"] = review["result"]
    autonomy = ((record.get("workflow") or {}).get("autonomy") or {})
    acceptance = autonomy.get("acceptance") or {}
    if acceptance.get("status"):
        result["acceptance"] = acceptance["status"]
    authorization = autonomy.get("authorization") or {}
    if authorization.get("predevelop"):
        result["predevelop"] = True
        if authorization.get("source"):
            result["authorization_source"] = authorization["source"]
    pre = autonomy.get("predevelopment")
    latest = (autonomy.get("snapshots") or {}).get(autonomy.get("latest_snapshot"))
    if isinstance(pre, dict) or isinstance(latest, dict):
        marker = {}
        if isinstance(pre, dict):
            marker.update({key: pre[key] for key in ("phase", "generation", "formal_base", "baseline") if pre.get(key) is not None})
            pins = {name: {"id": value.get("id"), "commit": value.get("commit")}
                    for name, value in (pre.get("inputs") or {}).items() if isinstance(value, dict)}
            retained = [{"worktree": row.get("worktree"), "branch": row.get("branch")}
                        for row in pre.get("retained_developments") or [] if isinstance(row, dict)]
            if pins:
                marker["pins"] = pins
            if retained:
                marker["retained"] = retained
        if isinstance(latest, dict):
            marker["snapshot"] = {"id": latest.get("id"), "status": latest.get("status"),
                                  "commit": latest.get("commit"), "prerequisites": latest.get("prerequisites") or {}}
        result["predevelopment"] = marker
    return result


def _migration_output(root, result, output):
    if output:
        root = runtime.find_project(root)
        target = Path(output)
        if not target.is_absolute():
            target = root / target
        try:
            relative = target.relative_to(root / ".project-local")
        except ValueError as exc:
            raise ProjectError("migration output must be inside .project-local/") from exc
        if len(relative.parts) < 2 or relative.parts[0] != "reports" or any(part in {"..", "."} for part in relative.parts):
            raise ProjectError("migration output must be a normalized file under .project-local/reports/")
        directory = _local_directory(root, *relative.parts[:-1])
        target = directory / relative.name
        if target.is_symlink():
            raise ProjectError("migration output cannot use a symlink")
        runtime._write_journal(target, result)
    summary = {key: value for key, value in result.items() if key not in {"writes", "checks"}}
    writes = result.get("writes", {})
    summary["changed_files"] = len(writes)
    summary["paths"] = sorted(writes)[:50]
    if len(writes) > 50:
        summary["more_paths"] = len(writes) - 50
    if output:
        summary["details_file"] = str(target)
    return summary


def _redact(value):
    if isinstance(value, dict):
        return {key: ({k: _redact(v) for k, v in child.items() if k != "token"}
                      if key == "owner" and isinstance(child, dict) else _redact(child))
                for key, child in value.items()}
    if isinstance(value, list):
        return [_redact(child) for child in value]
    return value


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ProjectError(message)


def _module(name):
    import importlib
    return importlib.import_module((__package__ + "." if __package__ else "") + name)


def _begin_options(args):
    excluded = {"command", "root", "host", "operation", "selector"}
    options = {key: value for key, value in vars(args).items()
               if key not in excluded and value is not None}
    if args.operation == "fix" and args.selector:
        if options.get("fixes") and options["fixes"] != args.selector:
            raise ProjectError("fix target selector conflicts with --fixes")
        options["fixes"] = args.selector
    if args.operation in {"create", "fix", "kind-update"} and "kind" in options:
        if len(options["kind"]) != 1:
            raise ProjectError("this operation requires a single --kind")
        options["kind"] = options["kind"][0]
    if args.operation == "cleanup-record" and "reference" in options:
        if len(options["reference"]) != 1:
            raise ProjectError("cleanup requires one --reference")
        options["reference"] = options["reference"][0]
    return options


def _init_config(args):
    if args.config:
        return _json_input(args.config)
    for key in ("id", "name", "storage_url", "storage_branch"):
        if not getattr(args, key):
            raise ProjectError("init requires --" + key.replace("_", "-"))
    config = {"schema_version": 2, "id": args.id, "name": args.name,
              "storage": {"remote": args.storage_remote, "url": args.storage_url, "branch": args.storage_branch},
              "repositories": [], "backends": {"aone": None}}
    if args.repository_id or args.repository_url or args.repository_base_ref:
        if not args.repository_id or not args.repository_url or not args.repository_base_ref:
            raise ProjectError("repository configuration requires --repository-id, --repository-url and --repository-base-ref")
        config["repositories"] = [{"id": args.repository_id, "url": args.repository_url,
                                   "base_ref": args.repository_base_ref}]
    if args.main_workspace_id:
        if not args.main_workspace_name:
            raise ProjectError("associated workspace requires --main-workspace-name")
        config["main_workspace"] = {"id": args.main_workspace_id, "name": args.main_workspace_name,
                                    "repository": None}
        if args.main_workspace_url:
            if not args.main_workspace_ref:
                raise ProjectError("associated workspace repository requires --main-workspace-ref")
            config["main_workspace"]["repository"] = {"url": args.main_workspace_url, "ref": args.main_workspace_ref}
    if args.worktrees_base or args.worktrees_path:
        if not args.worktrees_base or not args.worktrees_path:
            raise ProjectError("worktree layout requires --worktrees-base and --worktrees-path")
        config["worktrees"] = {"base": args.worktrees_base, "path": args.worktrees_path}
    if args.aone_space:
        if not args.aone_type or not args.aone_category:
            raise ProjectError("Aone profile requires --aone-type and --aone-category")
        mapping = {}
        for entry in args.aone_status or []:
            key, separator, value = entry.partition("=")
            if not separator or key not in runtime.STATUSES or not value or key in mapping:
                raise ProjectError("--aone-status requires one unique LOCAL=REMOTE mapping per local status")
            mapping[key] = value
        if set(mapping) != runtime.STATUSES:
            raise ProjectError("--aone-status must cover every local status")
        config["backends"]["aone"] = {"space_id": args.aone_space, "type": args.aone_type,
                                      "category": args.aone_category, "status_map": mapping}
    return config


def parser():
    p = _Parser(description=__doc__)
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--status", action="append")
    listing.add_argument("--query")
    listing.add_argument("--limit", type=context._positive_int, default=50)
    listing.add_argument("--offset", type=context._nonnegative_int, default=0)
    show = sub.add_parser("show")
    show.add_argument("item")
    show.add_argument("--documents", nargs="*", metavar="RELATIVE_DOCUMENT")
    role = sub.add_parser("context")
    role.add_argument("item")
    role.add_argument("--role", choices=context.ROLES, required=True)
    search = sub.add_parser("search-evidence")
    search.add_argument("query")
    search.add_argument("--repository")
    search.add_argument("--limit", type=context._positive_int, default=50)
    search.add_argument("--offset", type=context._nonnegative_int, default=0)
    knowledge_show = sub.add_parser("knowledge-show")
    knowledge_show.add_argument("identifier")
    for name in ("knowledge-update", "knowledge-remove"):
        knowledge = sub.add_parser(name)
        knowledge.add_argument("identifier")
        knowledge.add_argument("--expect-metadata-sha256", required=True)
        knowledge.add_argument("--expect-body-sha256", required=True)
        if name == "knowledge-update":
            knowledge.add_argument("--body-file", required=True)
            for field in ("repository", "topic", "summary", "scope"):
                knowledge.add_argument("--" + field)
            knowledge.add_argument("--kind", choices=("fact", "inference", "search", "verification"))
            inputs = knowledge.add_mutually_exclusive_group()
            inputs.add_argument("--input", dest="inputs", action="append", metavar="KEY=VALUE")
            inputs.add_argument("--clear-inputs", action="store_true")
            sources = knowledge.add_mutually_exclusive_group()
            sources.add_argument("--source", dest="sources", action="append", metavar="PATH")
            sources.add_argument("--clear-sources", action="store_true")
            knowledge.add_argument("--source-revision", action="append", metavar="PATH=REVISION")
            knowledge.add_argument("--source-sha256", action="append", metavar="PATH=SHA256")
    autonomy = sub.add_parser("autonomy")
    advancing = autonomy.add_subparsers(dest="autonomy_action", required=True)
    for action in ("status", "authorize"):
        command = advancing.add_parser(action)
        selected = command.add_mutually_exclusive_group(required=True)
        selected.add_argument("--all", dest="all_items", action="store_true")
        selected.add_argument("--tree")
        selected.add_argument("--item", dest="items", action="append")
        if action == "authorize":
            command.add_argument("--approval-source", required=True)
            command.add_argument("--skip-design-review", action="store_true")
            command.add_argument("--predevelop", action="store_true")
    for action in ("complete", "begin-transform", "accept", "snapshot", "prepare"):
        command = advancing.add_parser(action)
        command.add_argument("item")
        if action in {"complete", "begin-transform"}:
            command.add_argument("--role", choices=("baseline", "rebase") if action == "begin-transform" else ("implementation", "fix", "baseline", "rebase"), required=True)
        if action == "complete":
            command.add_argument("--report-file", required=True)
            command.add_argument("--provenance", required=True)
        if action == "begin-transform":
            command.add_argument("--author-session", required=True)
        if action == "accept":
            command.add_argument("--approval-source", required=True)
    takeover = sub.add_parser("takeover")
    takeover.add_argument("item")
    takeover.add_argument("--approval-source", required=True)
    lifecycle = sub.add_parser("lifecycle")
    lifecycle_actions = lifecycle.add_subparsers(dest="lifecycle_action", required=True)
    lifecycle_status = lifecycle_actions.add_parser("status")
    lifecycle_status.add_argument("item", nargs="?")
    for action in ("policy", "handoff", "replan", "prepare", "adopt", "dispose", "release", "plan", "collect"):
        command = lifecycle_actions.add_parser(action)
        command.add_argument("item")
        if action in {"policy", "handoff", "replan"}:
            command.add_argument("--approval-source", required=True)
        if action == "policy":
            command.add_argument("--grace-days", type=int, default=7)
            command.add_argument("--max-retained", type=int, default=2)
            command.add_argument("--max-snapshots", type=int, default=20)
        if action in {"replan", "handoff"}:
            command.add_argument("--mode", choices=("manual", "autonomous"), default="autonomous", required=action == "handoff")
            command.add_argument("--coordinator-session")
        if action == "adopt":
            command.add_argument("--worktree", required=True)
        if action == "dispose":
            command.add_argument("--generation", required=True)
            command.add_argument("--disposition", choices=("migrated", "discarded"), required=True)
            command.add_argument("--approval-source")
        if action in {"dispose", "release"}:
            command.add_argument("--reference", required=True)
        if action == "release":
            command.add_argument("--snapshot", required=True)
        if action == "collect":
            command.add_argument("--intent", required=True)
            command.add_argument("--confirm", required=True)
    sub.add_parser("refresh")
    sub.add_parser("status")
    sub.add_parser("progress")
    sub.add_parser("removal-plan")
    remove = sub.add_parser("remove")
    remove.add_argument("--manifest", required=True)
    remove.add_argument("--confirm", required=True)
    begin = sub.add_parser("begin")
    begin.add_argument("operation")
    begin.add_argument("selector", nargs="?")
    for name in ("title", "slug", "parent", "repository", "approval-source", "result", "provenance",
                 "reviewer-session", "review-file", "branch", "author-session",
                 "base-ref", "commit", "worktree", "fixes", "cleanup-status", "mode"):
        begin.add_argument("--" + name)
    begin.add_argument("--skip-design-review", action="store_true", default=None)
    begin.add_argument("--contract-unchanged", action="store_true", default=None)
    begin.add_argument("--discard-development", action="store_true", default=None)
    begin.add_argument("--kind", action="append")
    begin.add_argument("--reference", action="append")
    begin.add_argument("--delivery-required", action="append")
    begin.add_argument("--archived", action=argparse.BooleanOptionalAction, default=None)
    begin.add_argument("--depends-on", action="append")
    finish = sub.add_parser("finish")
    finish.add_argument("ticket")
    finish.add_argument("--result", choices=("pass", "fail"))
    finish.add_argument("--provenance")
    finish.add_argument("--contract-unchanged", action="store_true", default=None)
    finish.add_argument("--mechanical-correction", action="store_true", default=None)
    migration = sub.add_parser("migrate")
    migration.add_argument("--dry-run", action="store_true")
    migration.add_argument("--instructions-file")
    migration.add_argument("--output", help="Optional detailed result path inside .project-local/reports/")
    change = sub.add_parser("apply")
    change.add_argument("--request", required=True, help="JSON file, or - for stdin")
    change.add_argument("--dry-run", action="store_true")
    recovery = sub.add_parser("resume")
    recovery.add_argument("--session")
    recovery.add_argument("--token")
    recovery.add_argument("--identity-file")
    recovery.add_argument("--journal")
    recovery.add_argument("--ticket")
    recovery.add_argument("--item", action="append")
    initialize = sub.add_parser("init")
    initialize.add_argument("path")
    initialize.add_argument("--config", help="Legacy diagnostic configuration input")
    for name in ("id", "name", "storage-url", "storage-branch", "aone-space", "aone-type", "aone-category",
                 "repository-id", "repository-url", "repository-base-ref", "main-workspace-id", "main-workspace-name",
                 "main-workspace-url", "main-workspace-ref", "main-workspace-root", "worktrees-base", "worktrees-path"):
        initialize.add_argument("--" + name)
    initialize.add_argument("--storage-remote", default="origin")
    initialize.add_argument("--aone-status", action="append", metavar="LOCAL=REMOTE")
    initialize.add_argument("--context-file", required=True)
    initialize.add_argument("--main-workspace-context-file")
    initialize.add_argument("--local-binding-file")
    initialize.add_argument("--publish", action="store_true")
    return p


def _progress(root):
    return _status(root, _progress_item)


def _status(root, summarize=_item_summary):
    refreshed = runtime.refresh_project(root)
    root = runtime.find_project(root)
    files = runtime._working_files(root)
    items = store.items(files)
    pending, identities = [], set()
    for identifier, item in items.items():
        receipt = store.receipt(files, identifier)
        if receipt and receipt.get("state") in {"pending", "unknown"}:
            owner = item.get("owner") or {}
            pending.append({"item": identifier, "state": receipt["state"], "session": owner.get("session")})
            identities.add((owner.get("session"), owner.get("token")))
    publications, rejected = [], []
    runtime._no_links(root, ".project-local/publish")
    for path in sorted((root / ".project-local/publish").glob("*/journal.json")):
        runtime._no_links(root, path.relative_to(root).as_posix())
        state = runtime.read_json(path)
        disposition = runtime.publication_disposition(state)
        if disposition == "published":
            continue
        bundle_path = path.with_name("bundle.json")
        runtime._no_links(root, bundle_path.relative_to(root).as_posix())
        bundle = runtime.read_json(bundle_path)
        if disposition == "rejected_before_push":
            rejected.append({"journal": str(path), "state": state["state"],
                             "code": "publication_rejected_before_push"})
            continue
        identities.add((bundle.get("session"), bundle.get("token")))
        publications.append({"journal": str(path), "state": state.get("state"), "session": bundle.get("session")})
    result = _redact({"status": "ready", "project": store.project(files),
                      "items": [summarize(record) for record in items.values()],
                      "pending_sync": pending, "pending_publications": publications,
                      "rejected_publications": rejected, **refreshed})
    if not identities:
        return result
    result.update(status="blocked", code="recovery_identity_ambiguous", action="blocked")
    if len(identities) != 1:
        return result
    if len(publications) > 1:
        result["code"] = "publication_journal_ambiguous"
        return result
    session, token = next(iter(identities))
    current = project_identity.current_session()
    if not session or not token or (session != current and session != "project-migration"):
        result["code"] = "recovery_owned_by_another_session"
        return result
    runtime._no_links(root, ".project-local/requests")
    for path in sorted((root / ".project-local/requests").glob("*/identity.json")):
        runtime._no_links(root, path.relative_to(root).as_posix())
        identity = runtime.read_json(path)
        if (identity.get("session"), identity.get("token")) == (session, token):
            result.update(status="partial", code="recovery_available", action="resume",
                          recovery={"action": "resume", "identity_file": str(path)})
            return result
    result["code"] = "recovery_identity_missing"
    return result


def _public_result(result, args):
    """Keep command results bounded and expose one program-selected next action."""
    result = dict(result)
    original = result.get("status")
    if getattr(args, "command", None) == "remove" and original == "partial":
        result.update(status="blocked", code="partial_removal", next_command=None)
        return result
    if original in {"failed", "stale", "begin_again"}:
        result["status"] = "blocked"
        result.setdefault("code", result.get("action_code", original))
    elif original in {"editing", "prepared", "dry_run", "refreshed", "awaiting_confirmation"}:
        result["status"] = "ready"
    elif original == "removed":
        result["status"] = "published"
        result["outcome"] = "removed"
    elif original is None:
        result["status"] = "ready"
    if original in {"stale", "begin_again"}:
        result["next_command"] = result.get("begin_command")
        result["action"] = "blocked"
    if result.get("status") == "partial":
        recovery = result.get("recovery") or (result.get("publication") or {}).get("recovery") or {}
        command = [sys.executable, str(Path(__file__).resolve()), "--root", str(Path(args.root).resolve()), "resume"]
        if result.get("ticket"):
            command += ["--ticket", result["ticket"]]
        elif recovery.get("identity_file"):
            command += ["--identity-file", recovery["identity_file"]]
        elif recovery.get("session") and recovery.get("token"):
            command += ["--session", recovery["session"], "--token", recovery["token"]]
        if recovery.get("journal"):
            command += ["--journal", recovery["journal"]]
        result["next_command"] = shlex.join(command)
        result["action"] = "resume"
        result.pop("finish_command", None)
    if result.get("status") in {"partial", "blocked"}:
        result.setdefault("code", result.get("action_code", "project_operation_blocked"))
        result.setdefault("action", "blocked")
    return result


def main(argv=None, *, session=project_identity.UNSET, command_prefix=None):
    session_token = project_identity.select(session)
    try:
        args = parser().parse_args(argv)
        if args.command == "autonomy":
            autonomy = _module("project_autonomy")
            action = args.autonomy_action
            if action in {"status", "authorize"}:
                options = {key: getattr(args, key) for key in ("all_items", "tree", "items")}
                if action == "authorize":
                    options.update(approval_source=args.approval_source, skip_design_review=args.skip_design_review, predevelop=args.predevelop, publish=publish_changes)
                result = getattr(autonomy, action)(args.root, **options)
            elif action == "begin-transform":
                result = autonomy.begin_transform(args.root, args.item, role=args.role, author_session=args.author_session, publish=publish_changes)
            elif action == "complete":
                result = autonomy.complete(args.root, args.item, role=args.role, report_file=args.report_file, provenance=args.provenance, publish=publish_changes)
            elif action == "accept":
                result = autonomy.accept(args.root, args.item, approval_source=args.approval_source, publish=publish_changes)
            elif action in {"snapshot", "prepare"}:
                result = getattr(_module("project_predevelopment"), action)(args.root, args.item, publish=publish_changes)
        elif args.command == "takeover":
            result = _module("project_ownership").takeover(args.root, args.item,
                approval_source=args.approval_source, publish=publish_changes)
        elif args.command == "lifecycle":
            lifecycle = _module("project_lifecycle")
            action = args.lifecycle_action
            fields = {"policy": ("approval_source", "grace_days", "max_retained", "max_snapshots"),
                      "replan": ("approval_source", "mode", "coordinator_session"),
                      "handoff": ("approval_source", "mode", "coordinator_session"),
                      "dispose": ("generation", "disposition", "reference", "approval_source"),
                      "adopt": ("worktree",),
                      "release": ("snapshot", "reference"), "collect": ("intent", "confirm")}
            options = {key: getattr(args, key) for key in fields.get(action, ())}
            if action != "status":
                options["publish"] = publish_changes
            result = getattr(lifecycle, action)(args.root, args.item, **options)
        elif args.command == "begin":
            result = _module("project_workflow").begin(args.root, args.operation, args.selector,
                                                       options=_begin_options(args), publish=publish_changes)
        elif args.command == "finish":
            result = _module("project_workflow").finish(args.root, args.ticket,
                        options={key: value for key, value in {"result": args.result, "provenance": args.provenance, "contract_unchanged": args.contract_unchanged, "mechanical_correction": args.mechanical_correction}.items()
                                 if value is not None}, publish=publish_changes)
        elif args.command == "removal-plan":
            result = _module("project_removal").removal_plan(args.root)
        elif args.command == "remove":
            result = _module("project_removal").remove(args.root, args.manifest, args.confirm)
        elif args.command == "migrate":
            result = _module("project_migration").migrate(args.root, dry_run=args.dry_run, publish=publish_changes,
                                                                  instructions_file=args.instructions_file)
            result = _migration_output(args.root, result, args.output)
        elif args.command == "status":
            result = _status(args.root)
        elif args.command == "progress":
            result = _progress(args.root)
        elif args.command == "knowledge-show":
            result = _module("project_knowledge").show(args.root, args.identifier)
        elif args.command in {"knowledge-update", "knowledge-remove"}:
            knowledge = _module("project_knowledge")
            options = {"expected_metadata": args.expect_metadata_sha256, "expected_body": args.expect_body_sha256,
                       "publish": publish_changes}
            if args.command == "knowledge-update":
                fields = ("repository", "topic", "summary", "scope", "kind", "inputs", "sources", "clear_inputs", "clear_sources",
                          "source_revision", "source_sha256")
                options.update(body_file=args.body_file, options={key: getattr(args, key) for key in fields})
                result = knowledge.update(args.root, args.identifier, **options)
            else:
                result = knowledge.remove(args.root, args.identifier, **options)
        elif args.command == "apply":
            result = {"status": "blocked", "code": "handwritten_apply_disabled", "action": "blocked",
                      "message": "JSON apply requests are disabled. Use migrate for a legacy project, then begin/finish."}
        elif args.command == "resume":
            if args.ticket:
                result = _module("project_workflow").resume(args.root, args.ticket, publish=publish_changes)
            elif not any((args.identity_file, args.session, args.token, args.journal, args.item)):
                workflow = _module("project_workflow")
                result = workflow.resume(args.root, publish=publish_changes)
                if result.get("status") == "no_op":
                    identity = workflow._identity(runtime.find_project(args.root))
                    result = resume(args.root, identity["session"], identity["token"])
            else:
                identity = _json_input(args.identity_file) if args.identity_file else {}
                if not args.identity_file and not args.session and not args.token:
                    identity = _module("project_workflow")._identity(runtime.find_project(args.root))
                session, token = args.session or identity.get("session"), args.token or identity.get("token")
                if args.journal:
                    result = runtime.resume_publication(args.root, session=session, token=token, journal=args.journal)
                else:
                    result = resume(args.root, session, token, args.item)
        elif args.command == "refresh":
            result = {"status": "refreshed", **runtime.refresh_project(args.root)}
        elif args.command == "init":
            result = init_project(args.path, _init_config(args), Path(args.context_file).read_text(encoding="utf-8"),
                                  publish=args.publish,
                                  main_workspace_context=Path(args.main_workspace_context_file).read_text(encoding="utf-8") if args.main_workspace_context_file else None,
                                  local_binding=(_json_input(args.local_binding_file) if args.local_binding_file else
                                                 {"id": args.main_workspace_id, "root": args.main_workspace_root}
                                                 if args.main_workspace_root else None))
        else:
            result = _query(args)
    except ProjectInitError as exc:
        result = exc.result
    except (ProjectError, context.ContextError, OSError, ValueError) as exc:
        result = {"status": "failed", **_error_details(exc)}
    finally:
        project_identity.reset(session_token)
    result = _public_result(result, args if "args" in locals() else argparse.Namespace(root="."))
    result = project_identity.bind_commands(result, command_prefix)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if result.get("status") in {"partial", "blocked"} else 0


if __name__ == "__main__":
    raise SystemExit(main())

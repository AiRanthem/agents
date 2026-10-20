"""Coordinator-owned advancement using the ordinary guarded project workflow.

known-limit: host receipts are captured by the trusted coordinator, not signed by
an execution service. Structural checks prevent cross-item/stage/attempt reuse;
they cannot authenticate a dishonest coordinator. A future host adapter can verify
service-signed receipts here without changing worker or workflow contracts.
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
ROLES = ("design-review", "implementation", "code-review", "fix", "design-revision", "baseline", "rebase")
OPERATIONS = {"design-review": "design-review", "implementation": "development-start",
              "code-review": "development-finish", "design-revision": "design-update"}


def _state(item):
    return item.setdefault("workflow", {}).setdefault("autonomy", {})


def _predevelopment():
    try:
        import project_predevelopment
    except ImportError:
        from . import project_predevelopment
    return project_predevelopment


def _files(root):
    root = runtime.find_project(root)
    return root, workflow._snapshot(root)


def _binding(root, files, item, *, code=True):
    result = workflow._binding(files, item, workflow._base(item))
    result["project_sha256"] = workflow._hash(files[store.project_path(files)])
    result["decision_sha256"] = workflow._hash(files.get(workflow._documents(item)["decision"]))
    sources = ((item.get("workflow") or {}).get("lifecycle") or {}).get("generations")
    if sources:
        result["retained_sources_sha256"] = workflow._hash(workflow._canonical(sources))
    if _predevelopment().state(item):
        result["predevelopment_sha256"] = workflow._hash(workflow._canonical(_predevelopment().identity(item)))
    if code and item.get("development"):
        result["code_snapshot"] = workflow._code_snapshot(root, item, store.project(files))
    return result


def _payload(root, files, item, role):
    read = workflow._read_payload(root, files, item, OPERATIONS.get(role, "development-finish"))
    decision = workflow._documents(item)["decision"]
    if decision in files and str(root / decision) not in {entry["path"] for entry in read}:
        read.append({"path": str(root / decision), "content": files[decision].decode("utf-8")})
    return read


def _read_hashes(root, files, item, role, *, read=None):
    if read is None:
        read = _payload(root, files, item, role)
    hashes = {entry["path"]: workflow._hash(Path(entry["path"]).read_bytes()) for entry in read}
    candidates = {root / name for name in (".project/project-instructions.md", ".project/main-workspace.md",
                                          ".project/business-instructions.md", ".project/context.md")}
    candidates.add(root / workflow._documents(item)["decision"])
    anchors = {root} | {Path(entry["path"]).parent for entry in read if Path(entry["path"]).name == "AGENTS.md"}
    if item.get("development"):
        anchors.add(workflow._development_module().worktree_location(root, item, store.project(files)))
    for anchor in anchors:
        candidates.update(directory / "AGENTS.md" for directory in (anchor, *anchor.parents))
    for path in candidates:
        if path.is_symlink():
            raise ProjectError("required read source cannot use a symlink: " + str(path))
        hashes.setdefault(str(path), workflow._hash(path.read_bytes()) if path.is_file() else None)
    if role in _predevelopment().WRITERS and item.get("development"):
        location = workflow._development_module().worktree_location(root, item, store.project(files))
        # These explicit Git transformation stages replace inherited source
        # instructions. Their immutable target/pin OIDs remain input-bound;
        # ancestor/project instructions stay guarded and final reviews reload them.
        hashes = {name: value for name, value in hashes.items() if not Path(name).is_relative_to(location)}
    return hashes


def _validate_reads(entry, *, revised_spec=None, missing_root=None):
    for name, expected in entry.get("read_hashes", {}).items():
        path = Path(name)
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ProjectError("execution required read source is stale: " + name)
        if missing_root is not None and path.is_relative_to(missing_root) and not path.exists():
            continue
        if not path.exists() and expected is None:
            continue
        if not path.is_file():
            raise ProjectError("execution required read source is stale: " + name)
        actual = workflow._hash(path.read_bytes())
        if actual != expected and not (revised_spec and name == revised_spec and actual == entry.get("candidate_sha256")):
            raise ProjectError("execution required read source is stale: " + name)


def review_inputs_current(files, item, review, *, missing_root=None):
    attempt = review.get("execution")
    if not attempt:
        basis = (item.get("workflow") or {}).get("design_basis") or {}
        guard = review if review.get("read_hashes") else basis if basis.get("review") == review else {}
        if not guard.get("read_hashes"):
            # Existing ordinary review records predate read guards; controlled
            # edits capture a still-current basis before replacing their inputs.
            return True
        try:
            _validate_reads(guard, missing_root=missing_root)
            return True
        except ProjectError:
            return False
    entry = _state(item).get("executions", {}).get(attempt)
    if (not entry or not entry.get("read_hashes") or
            entry.get("input_binding", {}).get("project_sha256") != workflow._hash(files[store.project_path(files)])):
        return False
    try:
        mechanical = review.get("mechanical_correction") or {}
        revised_spec = next((name for name in review.get("read_hashes", {}) if name.endswith("/workitems/" + item["id"] + "/spec.md")), None)
        if mechanical.get("candidate_sha256") != entry.get("candidate_sha256"):
            revised_spec = None
        _validate_reads(entry, missing_root=missing_root, revised_spec=revised_spec if mechanical else None)
        return True
    except ProjectError:
        return False


def _contract(files, item):
    return workflow._approval_binding(files, item)


def _approved_contract(files, item):
    approval = item.get("design", {}).get("approval") or {}
    return bool(approval.get("kind") != "derived_reuse_pending" and approval.get("source") and all(approval.get(k) == v for k, v in _contract(files, item).items()))


def scope(files, *, all_items=False, tree=None, items=None):
    records = store.items(files)
    if sum((bool(all_items), tree is not None, bool(items))) != 1:
        raise ProjectError("scope requires exactly one of --all, --tree or --item")
    if all_items:
        return sorted(records)
    if items:
        return sorted({workflow._resolve(records, selector) for selector in items})
    parent = workflow._resolve(records, tree)
    selected = {parent}
    while True:
        more = {key for key, value in records.items() if value.get("parent") in selected or value.get("split_from") in selected}
        if more <= selected:
            return sorted(selected)
        selected |= more


def _publish(root, files, records, identity, message, publish, *, extra=None):
    writes, checks = dict(extra or {}), {store.project_path(files): workflow._hash(files[store.project_path(files)])}
    for item in records:
        writes.update(store.write_item(files, item))
        checks.update(workflow._checks(files, item, "context-update"))
    writes.update(_predevelopment()._lifecycle().reconcile(files, writes))
    for name in writes:
        checks.setdefault(name, workflow._hash(files.get(name)))
    # Pin creation and lifecycle deletion marking serialize on the same state.
    # Include all items: a frozen transitive input need not remain in today's DAG.
    for name, content in files.items():
        if name.startswith(".project/state/") or name.endswith("/metadata.yaml"):
            checks.setdefault(name, workflow._hash(content))
    prospective = store.apply_writes(files, writes)
    errors = runtime._validate_files(root, prospective)
    if errors:
        raise ProjectError("invalid autonomy state: " + "; ".join(errors))
    return workflow._publish(root, writes, identity, message, checks, publish)


def _owned(item, identity):
    workflow._ownership(item, identity)
    authorization = _state(item).get("authorization") or {}
    if authorization.get("coordinator") != identity["session"]:
        raise ProjectError("autonomy authorization belongs to another coordinator; confirm old task ownership before recovery")


def _artifact_binding(root, files, item):
    binding = _binding(root, files, item, code=False)
    if item.get("development"):
        if item.get("status") == "done":
            snapshot = item["development"].get("reviewed_snapshot") or {}
        else:
            snapshot = workflow._code_snapshot(root, item, store.project(files))
        binding["code_tree"] = snapshot.get("tree")
    return binding


def _acceptance_valid(root, files, item):
    acceptance = _state(item).get("acceptance") or {}
    if acceptance.get("status") != "accepted" or not acceptance.get("source"):
        return False
    try:
        if item.get("kind") != "aggregate":
            _acceptance_review(root, files, item)
        return acceptance.get("binding") == _artifact_binding(root, files, item)
    except (ProjectError, store.StoreError, OSError):
        return False


def _dependency_blocks(root, files, item, *, formal=False):
    records = store.items(files)
    result = []
    for identifier in sorted(workflow._ancestors(records, item["id"]) - {item["id"]}):
        dependency = records[identifier]
        if not formal and identifier in _predevelopment().pins(item):
            continue
        if dependency.get("delivery", {}).get("status") != "delivered" or dependency.get("status") == "cancelled":
            result.append("undelivered:" + identifier)
        if not _acceptance_valid(root, files, dependency):
            result.append("unaccepted:" + identifier)
    result.extend("open_fix:" + key for key in workflow._open_fixes(records, item["id"]))
    return result


def _next(root, files, item, session):
    state = _state(item)
    result = {"id": item["id"], "next_role": None, "reasons": []}
    if item.get("status") == "done":
        result["state"] = "completed"
        return result
    if item.get("archived") or item.get("status") == "cancelled":
        result.update(state="blocked", reasons=["inactive"])
        return result
    if item.get("kind") == "aggregate":
        result.update(state="accepted_awaiting_delivery" if _acceptance_valid(root, files, item) else "blocked", reasons=[] if _acceptance_valid(root, files, item) else ["aggregate_manual_acceptance"])
        return result
    authorization = state.get("authorization") or {}
    if not authorization:
        result["reasons"].append("not_authorized")
    elif authorization.get("coordinator") != session:
        result["reasons"].append("unknown_owner_liveness")
    owner = item.get("owner") or {}
    if owner and owner.get("session") != session:
        result["reasons"].append("owned_by_another_session")
    current = state.get("current")
    if current:
        execution = state["executions"][current]
        result.update(state="running", attempt=current, role=execution["role"], worker_id=execution["worker_id"])
        return result
    if state.get("blocker"):
        result["reasons"].append(state["blocker"])
    assess_reuse = not result["reasons"] and workflow._design_reuse().needed(root, files, item, session)
    pending_confirmation = workflow._design_reuse().pending(files, item)
    if not assess_reuse and not pending_confirmation and not _approved_contract(files, item):
        result["reasons"].append("approved_initial_design_required")
    if not assess_reuse and not pending_confirmation and authorization and authorization.get("requirement_sha256") != _contract(files, item)["requirement_sha256"]:
        result["reasons"].append("authorization_contract_changed")
    if not assess_reuse and not pending_confirmation and authorization and authorization.get("decision_sha256") != workflow._hash(files.get(workflow._documents(item)["decision"])):
        result["reasons"].append("authorization_decision_changed")
    if not result["reasons"] and ((item.get("workflow") or {}).get("lifecycle") or {}).get("replacement_pending"):
        result.update(state="ready", next_action="lifecycle_prepare")
        return result
    if not result["reasons"]:
        extra = _predevelopment().schedule(root, files, item, session)
        if extra:
            result.update(extra)
            return result
    result["reasons"].extend(_dependency_blocks(root, files, item))
    if result["reasons"]:
        result["state"] = "blocked"
        return result
    try:
        _predevelopment()._lifecycle().capacity(item, runtime_cache=True)
    except ProjectError as exc:
        result.update(state="blocked", reasons=[str(exc)])
        return result
    if assess_reuse:
        result.update(state="ready", next_action="design_reuse_assessment")
        return result
    binding = _binding(root, files, item)
    development = item.get("development") or {}
    review = development.get("review") or {}
    reviewed = review.get("result") == "pass" and bool(review.get("code_snapshot")) and review["code_snapshot"].get("tree") == (binding.get("code_snapshot") or {}).get("tree")
    if reviewed:
        try:
            workflow._implementation_approved(files, item)
        except ProjectError:
            reviewed = False
    if reviewed:
        extra = _predevelopment().schedule(root, files, item, session, reviewed=True)
        if extra:
            result.update(extra)
            return result
        result["state"] = "accepted_awaiting_delivery" if _acceptance_valid(root, files, item) else "awaiting_acceptance"
        return result
    design_review_current = False
    try:
        workflow._approved(files, item)
        design_review_current = True
    except ProjectError:
        pass
    role = state.get("next_role")
    formal_review = ((_predevelopment().state(item) or {}).get("phase") in {"reconciling", "formal"} or
                     ((item.get("workflow") or {}).get("lifecycle") or {}).get("fresh_reviews_required"))
    if role == "design-revision":
        pass
    elif not design_review_current and (formal_review or not authorization.get("skip_design_review") or
            item.get("design", {}).get("approval", {}).get("kind") == "derived_revision"):
        role = "design-review"
    elif role in {"implementation", "fix"}:
        pass
    elif not development or item.get("status") not in {"developing", "awaiting_delivery"}:
        role = "implementation"
    elif review.get("result") == "fail":
        role = "fix"
    else:
        role = "code-review"
    result.update(state="ready", next_role=role)
    return result


def status(root, *, all_items=False, tree=None, items=None):
    root, files = _files(root)
    session = workflow._session()
    entries = []
    for key in scope(files, all_items=all_items, tree=tree, items=items):
        item = store.item(files, key)
        try:
            entry = _next(root, files, item, session)
        except (ProjectError, store.StoreError, OSError) as error:
            entry = {"id": key, "state": "blocked", "next_role": None,
                     "reasons": ["input_unavailable"], "error": str(error)}
        entries.append(entry)
    result = {"status": "ready", "items": entries}
    for state in ("ready", "blocked", "running", "awaiting_acceptance", "awaiting_predecessor_delivery", "accepted_awaiting_delivery", "completed"):
        result[state] = [entry["id"] for entry in entries if entry["state"] == state]
    result["round_finished"] = not result["ready"] and not result["running"]
    return result


def authorize(root, *, approval_source, all_items=False, tree=None, items=None, skip_design_review=False, predevelop=False, publish=None):
    workflow._text(approval_source, "explicit user advancement authorization source")
    root, files = _files(root)
    identity = workflow._identity(root)
    records, blocked = [], []
    selected = scope(files, all_items=all_items, tree=tree, items=items)
    for identifier in selected:
        item = store.item(files, identifier)
        state = _state(item)
        owner = item.get("owner") or {}
        handoff = ((item.get("workflow") or {}).get("lifecycle") or {}).get("handoff")
        if handoff and handoff["to"] != identity["session"]:
            blocked.append({"id": identifier, "reason": "recorded_coordinator_handoff"})
            continue
        if state.get("current") or (owner and owner.get("session") != identity["session"]) or (state.get("authorization") and state["authorization"]["coordinator"] != identity["session"]):
            blocked.append({"id": identifier, "reason": "unknown_owner_liveness"})
            continue
        workflow._ownership(item, identity)
        approval = item.get("design", {}).get("approval") or {}
        confirmed_contract = approval.get("kind") == "user"
        if approval.get("kind") in {"derived_reuse", "derived_mechanical", "derived_confirmation", "derived_revision"}:
            unwaived = copy.deepcopy(item)
            unwaived.setdefault("workflow", {}).pop("design_waiver", None)
            try:
                workflow._approved(files, unwaived)
                confirmed_contract = True
            except ProjectError:
                pass
        if _approved_contract(files, item) and confirmed_contract:
            basis = (item.get("workflow") or {}).get("design_basis") or {}
            original_read = {row["path"]: row["content"] for row in basis.get("read", [])} if approval.get("kind") != "user" else {}
            paths = {"requirement": workflow._documents(item)["requirement"], "spec": workflow._spec(item),
                     "decision": workflow._documents(item)["decision"]}
            state["approved_contract"] = {"approval": copy.deepcopy(basis.get("approval", approval) if original_read else approval),
                **{name: original_read.get(str(root / path), files.get(path, b"").decode("utf-8"))
                   for name, path in paths.items()}}
        state["authorization"] = {"source": approval_source, "coordinator": identity["session"],
                                  "scope": selected, "created_at": workflow._now(),
                                  "requirement_sha256": _contract(files, item)["requirement_sha256"],
                                  "decision_sha256": workflow._hash(files.get(workflow._documents(item)["decision"])),
                                  "skip_design_review": bool(skip_design_review)}
        state["authorization"]["predevelop"] = bool(predevelop)
        state.pop("blocker", None)
        records.append(item)
    publication = _publish(root, files, records, identity, "Authorize project advancement", publish) if records else {"status": "no_op"}
    return {**publication, "authorized": [item["id"] for item in records], "blocked_items": blocked}


def _receipt(value):
    if not isinstance(value, dict):
        raise ProjectError("host receipt must be an object")
    for field in ("host", "tool", "worker_id"):
        workflow._text(value.get(field), "host receipt " + field)
    if value.get("call_id") is not None:
        workflow._text(value["call_id"], "observable host call_id")
    if not isinstance(value.get("raw"), dict) or not value["raw"]:
        raise ProjectError("host receipt requires captured raw tool output")
    raw = value["raw"]
    for envelope in (raw, raw.get("result")):
        if isinstance(envelope, dict) and (envelope.get("isError") is True or envelope.get("error")):
            raise ProjectError("failed host tool calls cannot establish worker lifecycle evidence")
    def identities(node):
        found = []
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"worker_id", "agent_id", "agent_name", "task_name", "target"} and isinstance(child, str):
                    found.append(child)
                found.extend(identities(child))
        elif isinstance(node, list):
            for child in node:
                found.extend(identities(child))
        return found
    if value["worker_id"] not in identities(value["raw"]):
        raise ProjectError("captured native receipt must identify its actual worker")
    return copy.deepcopy(value)


def _provenance(receipt):
    return receipt.get("call_id") or "coordinator-capture-sha256:" + workflow._hash(workflow._canonical(receipt))


def _read_report(path):
    selected = Path(workflow._text(path, "report file")).absolute()
    if any(part.is_symlink() for part in (selected, *selected.parents)) or not selected.is_file():
        raise ProjectError("report/candidate must be an actual regular file without symlinks")
    content = selected.read_text(encoding="utf-8")
    workflow._text(content, "report/candidate body")
    return content


def execution(root, files, item, attempt, operation, *, require_result=False):
    state = _state(item)
    identity = workflow._identity(root)
    _owned(item, identity)
    entry = state.get("executions", {}).get(attempt)
    revision = entry and entry.get("role") == "design-review" and operation == "design-update" and (entry.get("result") or {}).get("outcome") == "revised"
    if not entry or state.get("current") != attempt or (OPERATIONS.get(entry.get("role")) != operation and not revision):
        raise ProjectError("execution does not match current item, role and attempt")
    if entry.get("input_binding") != _binding(root, files, item):
        raise ProjectError("execution input contract or dirty code snapshot is stale")
    _validate_reads(entry)
    blocks = _dependency_blocks(root, files, item)
    if blocks:
        raise ProjectError("checkpoint blocked: " + ",".join(blocks))
    if require_result and not entry.get("result"):
        raise ProjectError("execution has no captured host result")
    return entry


def dispatch(root, selector, *, role, receipt, publish=None):
    if role not in ROLES:
        raise ProjectError("unknown execution role")
    root, files = _files(root)
    identity = workflow._identity(root)
    identifier = workflow._resolve(store.items(files), selector)
    item = store.item(files, identifier)
    _owned(item, identity)
    readiness = _next(root, files, item, identity["session"])
    if readiness["state"] != "ready" or readiness["next_role"] != role:
        raise ProjectError("stage is not ready: " + str(readiness))
    captured = _receipt(receipt)
    authors = set(_state(item).get("code_authors", [])) if role == "code-review" else set(_state(item).get("design_authors", []))
    if role == "code-review":
        authors.add((item.get("development") or {}).get("author_session"))
    if role == "design-review":
        authors.update(workflow._design_authors(item))
    if role in {"design-review", "code-review"} and captured["worker_id"] in authors | {identity["session"]}:
        raise ProjectError("independent reviewer must not have authored or repaired the current artifact")
    attempt = secrets.token_hex(16)
    state = _state(item)
    state["current"] = attempt
    state.setdefault("executions", {})[attempt] = {"attempt": attempt, "item": identifier, "role": role,
        "worker_id": captured["worker_id"], "spawn": captured, "recorded_by": identity["session"],
        "created_at": workflow._now(), "input_binding": _binding(root, files, item),
        "read_hashes": _read_hashes(root, files, item, role)}
    if role in {"implementation", "fix", "baseline", "rebase"}:
        authors = state.setdefault("code_authors", [])
        if captured["worker_id"] not in authors:
            authors.append(captured["worker_id"])
    publication = _publish(root, files, [item], identity, "Dispatch " + role + " " + identifier, publish)
    if publication.get("status") not in {"published", "no_op"}:
        return _paused(root, identifier, attempt, publication)
    return _continue_dispatch(root, identifier, attempt, publish=publish)


def _continuation(root, identifier, attempt):
    return shlex.join([sys.executable, str(Path(__file__).with_name("project.py")), "--root", str(root),
                       "autonomy", "resume", identifier, "--attempt", attempt])


def _paused(root, identifier, attempt, result):
    return {**result, "attempt": attempt, "worker_paused": True,
            "continuation_command": _continuation(root, identifier, attempt)}


def _preparation_ticket(root, item, entry, identity, *, operation=None):
    if entry.get("workflow_ticket"):
        _, existing = workflow._load(root, entry["workflow_ticket"])
        if existing["operation"] == (operation or OPERATIONS[entry["role"]]):
            return entry["workflow_ticket"]
    matches = []
    for directory in workflow._local(root, "edits").iterdir():
        if workflow.TICKET.fullmatch(directory.name):
            _, manifest = workflow._load(root, directory.name)
            if (manifest["item"]["id"] == item["id"] and manifest["identity"] == identity and
                    manifest["operation"] == (operation or OPERATIONS[entry["role"]]) and
                    (manifest.get("execution") or manifest.get("options", {}).get("execution")) == entry["attempt"]):
                matches.append(directory.name)
    if len(matches) > 1:
        raise ProjectError("dispatch preparation has ambiguous retained tickets; preserve the original intents")
    return matches[0] if matches else None


def _continue_dispatch(root, identifier, attempt, *, publish=None):
    root, files = _files(root)
    identity = workflow._identity(root)
    item = store.item(files, identifier)
    _owned(item, identity)
    state = _state(item)
    entry = state.get("executions", {}).get(attempt)
    if state.get("current") != attempt or not entry or entry.get("result") or entry.get("finished_at"):
        raise ProjectError("dispatch continuation requires the current unfinished attempt without a result")
    if entry["input_binding"] != _binding(root, files, item):
        raise ProjectError("dispatch continuation input contract or dirty code snapshot is stale")
    _validate_reads(entry)
    role = entry["role"]
    if role in _predevelopment().WRITERS:
        _predevelopment().prepare_writer(root, files, item, role)
        item["owner"] = identity
        entry["input_binding"] = _binding(root, files, item)
        entry["read_hashes"] = _read_hashes(root, files, item, role)
        publication = _publish(root, files, [item], identity, "Bind Git transformation " + identifier, publish)
        if publication.get("status") not in {"published", "no_op"}:
            return _paused(root, identifier, attempt, publication)
    if role in {"implementation", "design-review", "design-revision"}:
        ticket = _preparation_ticket(root, item, entry, identity)
        if ticket:
            _, manifest = workflow._load(root, ticket)
            try:
                _validate_reads(manifest)
            except ProjectError as exc:
                raise ProjectError("dispatch continuation required read source changed; preserve its original ticket") from exc
            prepared = {"status": "ready", "ticket": ticket}
            if manifest["state"] not in {"editing", "finished"}:
                prepared = workflow.resume(root, ticket, publish=publish)
        else:
            options = {"execution": attempt}
            authorization = state["authorization"]
            formal_review = ((_predevelopment().state(item) or {}).get("phase") in {"reconciling", "formal"} or
                     ((item.get("workflow") or {}).get("lifecycle") or {}).get("fresh_reviews_required"))
            if role == "implementation" and authorization.get("skip_design_review") and not formal_review:
                options.update(skip_design_review=True, approval_source=authorization["source"])
            prepared = workflow.begin(root, OPERATIONS[role], identifier, options=options, publish=publish)
        if prepared.get("status") not in {"ready", "published", "no_op"}:
            return _paused(root, identifier, attempt, prepared)
        ticket = prepared["ticket"]
        if role == "implementation":
            finished = workflow.finish(root, ticket, publish=publish)
            if finished.get("status") not in {"published", "no_op"}:
                return _paused(root, identifier, attempt, finished)
        files = workflow._snapshot(root)
        item = store.item(files, identifier)
        state = _state(item)
        state["executions"][attempt]["input_binding"] = _binding(root, files, item)
        state["executions"][attempt]["workflow_ticket"] = ticket
        _validate_reads(state["executions"][attempt])
        state["executions"][attempt]["read_hashes"] = _read_hashes(root, files, item, role)
        publication = _publish(root, files, [item], identity, "Bind dispatch context " + identifier, publish)
        if publication.get("status") not in {"published", "no_op"}:
            return _paused(root, identifier, attempt, publication)
    files = workflow._snapshot(root)
    item = store.item(files, identifier)
    entry = _state(item)["executions"][attempt]
    return {"status": "ready", "attempt": attempt, "role": role, "worker_id": entry["worker_id"],
            "worker_paused": False, "input_binding": entry["input_binding"],
            "approved_contract": copy.deepcopy(_state(item).get("approved_contract")),
            **({"design_basis": copy.deepcopy(item["workflow"]["design_basis"])} if role == "design-review" and item.get("workflow", {}).get("design_basis") else {}),
            "code_context": workflow._code_context(root, item, store.project(files)),
            "git_operation": _predevelopment().writer_context(item, role),
            "prerequisites": copy.deepcopy(_predevelopment().pins(item)),
            "read": _payload(root, files, item, role)}


def _capture_directory(root, attempt):
    if not isinstance(attempt, str) or not workflow.TICKET.fullmatch(attempt):
        raise ProjectError("invalid result capture attempt")
    directory = root / ".project-local" / "autonomy-results" / attempt
    runtime._no_links(root, directory.relative_to(root).as_posix())
    return directory


def _retained_result(root, item, entry, identity):
    directory = _capture_directory(root, entry["attempt"])
    if not directory.exists():
        return None
    saved = workflow._load_manifest(root, directory)
    if (saved.get("identity") != identity or saved.get("item") != item["id"] or
            saved.get("dispatch_sha256") != workflow._hash(workflow._canonical(entry["spawn"]))):
        raise ProjectError("retained result does not match its coordinator or dispatch")
    captured = _receipt(saved.get("result"))
    for key in ("attempt", "worker_id", "role", "input_binding"):
        if captured.get(key) != entry.get(key):
            raise ProjectError("retained result mismatches execution " + key)
    if captured["host"] != entry["spawn"]["host"]:
        raise ProjectError("retained result mismatches dispatched host")
    _result_outcome(captured)
    _captured_body(saved, "report")
    if captured["outcome"] == "revised" or captured.get("mechanical_correction"):
        _captured_body(saved, "candidate")
    return saved


def _save_capture(root, attempt, saved):
    directory = workflow._local(root, "autonomy-results", attempt)
    workflow._save(root, directory, saved)


def _capture_journal(saved):
    response = (saved or {}).get("publication") or {}
    if response.get("code") == "publication_intent_mismatch":
        return None  # Diagnostic path is not an association to this attempt.
    return ((response.get("publication_recovery") or {}).get("journal") or
            (response.get("recovery") or {}).get("journal") or response.get("journal"))


def resume(root, selector, *, attempt, publish=None):
    root, files = _files(root)
    identifier = workflow._resolve(store.items(files), selector)
    item = store.item(files, identifier)
    identity = workflow._identity(root)
    _owned(item, identity)
    state = _state(item)
    entry = state.get("executions", {}).get(attempt)
    if not entry:
        raise ProjectError("unknown autonomous continuation attempt")
    if state.get("current") != attempt and entry.get("finished_at"):
        return {"status": "no_op", "attempt": attempt, "outcome": "execution_completed"}
    saved = _retained_result(root, item, entry, identity)
    journal = _capture_journal(saved)
    if journal:
        recovered = runtime.resume_publication(root, session=identity["session"],
                                               token=identity["token"], journal=journal)
        if (recovered.get("status") not in {"published", "no_op"} and
                recovered.get("code") != "publication_rejected_before_push"):
            return _pending_result(root, identifier, attempt, recovered)
        # A confirmed pre-push rejection settles only this journal. The retained
        # result goes through fresh contract/read/code guards before a new publish.
        saved.pop("publication", None)
        _save_capture(root, attempt, saved)
        return resume(root, identifier, attempt=attempt, publish=publish)
    if saved and not entry.get("result"):
        # A process can stop after the publisher creates a journal but before its
        # response is linked here. Require this capture's exact saved writes
        # before recovering any unique owned intent; session identity alone is
        # insufficient when the controller advances several items.
        recovered = runtime.resume_publication(root, session=identity["session"], token=identity["token"],
                                               expected_write_hashes=saved["capture_write_hashes"])
        if recovered.get("status") not in {"published", "no_op"}:
            return _pending_result(root, identifier, attempt, recovered)
        if recovered.get("status") == "published":
            return resume(root, identifier, attempt=attempt, publish=publish)
    if entry.get("result") or saved:
        return result(root, identifier, receipt=entry.get("result") or saved["result"], publish=publish)
    return _continue_dispatch(root, identifier, attempt, publish=publish)


def _pending_result(root, identifier, attempt, response):
    directory = _capture_directory(root, attempt)
    saved = workflow._load_manifest(root, directory)
    saved["publication"] = copy.deepcopy(response)
    _save_capture(root, attempt, saved)
    return {**response, "attempt": attempt, "stage_result_pending": True,
            "worker_paused": True, "continuation_command": _continuation(root, identifier, attempt)}


def _stage_ticket(root, files, item, entry, *, key="workflow_ticket"):
    """Refresh only program-written coordinator metadata on a bound stage ticket.

    Result validation already checked the original contract and code binding;
    original Markdown/instruction read hashes remain untouched and are rechecked
    by finish. This avoids abandoning a second editing intent on every dispatch.
    """
    directory, manifest = workflow._load(root, entry[key])
    if manifest["state"] == "editing":
        manifest["item"] = copy.deepcopy(item)
        manifest["checks"] = workflow._checks(files, item, manifest["operation"])
        manifest["checks"].setdefault(".project/graph.yaml", None)
        workflow._save(root, directory, manifest)
    return {"status": "ready", "ticket": manifest["ticket"],
            "editable": [{"path": str(directory / name)} for name in manifest.get("drafts", {})]}


def result(root, selector, *, receipt, publish=None):
    root, files = _files(root)
    identity = workflow._identity(root)
    identifier = workflow._resolve(store.items(files), selector)
    item = store.item(files, identifier)
    _owned(item, identity)
    captured = _receipt(receipt)
    attempt = captured.get("attempt")
    state = _state(item)
    entry = state.get("executions", {}).get(attempt)
    if not entry or state.get("current") != attempt:
        raise ProjectError("late or unknown execution attempt")
    for field in ("worker_id", "role", "input_binding"):
        if captured.get(field) != entry.get(field):
            raise ProjectError("host result mismatches execution " + field)
    if captured["host"] != entry["spawn"]["host"]:
        raise ProjectError("host result does not match dispatched host")
    outcome = _result_outcome(captured)
    blocks = _dependency_blocks(root, files, item)
    if blocks:
        raise ProjectError("checkpoint blocked: " + ",".join(blocks))
    # An unsuccessful writer may retain an unmerged index. Keep pass results
    # subject to the existing conflict-free snapshot check before capturing them.
    writer = entry["role"] in {"implementation", "fix", "baseline", "rebase"}
    current = _binding(root, files, item, code=not writer or outcome == "pass")
    # Writers may change only their code worktree; reviews bind the exact input.
    expected = copy.deepcopy(entry["input_binding"])
    # A retained design-update ticket can already have published its candidate
    # before coordinator finalization was interrupted. Only that exact derived
    # artifact, not an arbitrary later design, may complete the recorded result.
    derived = item.get("design", {}).get("approval") or {}
    _validate_reads(entry, revised_spec=str(root / workflow._spec(item)) if derived.get("execution") == attempt else None)
    if ((entry.get("result", {}).get("outcome") == "revised" or entry.get("result", {}).get("mechanical_correction")) and derived.get("execution") == attempt and
            current.get("spec_sha256") == entry.get("candidate_sha256") and current.get("version") == expected.get("version", 0) + 1):
        expected["spec_sha256"] = current["spec_sha256"]
        expected["version"] = current["version"]
    if writer:
        expected.pop("code_snapshot", None)
        current.pop("code_snapshot", None)
    if expected != current:
        raise ProjectError("execution input contract or dirty code snapshot is stale")
    role = entry["role"]
    if outcome == "pass" and role == "design-review" and item.get("design", {}).get("approval", {}).get("kind") in {"derived_revision", "derived_reuse_pending"} and captured.get("contract_unchanged") is not True:
        raise ProjectError("derived revision requires independent confirmation that the approved contract is unchanged")
    saved = _retained_result(root, item, entry, identity)
    if saved and saved["result"] != captured:
        raise ProjectError("captured result and report are immutable")
    if _capture_journal(saved):
        return _pending_result(root, identifier, attempt, saved["publication"])
    retained = entry if entry.get("result") else saved
    if retained:
        if retained["result"] != captured:
            raise ProjectError("captured result and report are immutable")
        report = _captured_body(retained, "report")
        candidate = _captured_body(retained, "candidate") if outcome == "revised" or captured.get("mechanical_correction") else None
        for key in ("result", "report", "candidate", "candidate_sha256"):
            if key in retained:
                entry[key] = copy.deepcopy(retained[key])
    else:
        report = _read_report(captured.get("report_file"))
        candidate = _read_report(captured.get("candidate_file")) if outcome == "revised" or captured.get("mechanical_correction") else None
        entry.update(result=captured, report={"sha256": workflow._hash(report), "body": report})
        if candidate is not None:
            entry["candidate"] = {"sha256": workflow._hash(candidate), "body": candidate}
            entry["candidate_sha256"] = workflow._hash(candidate)
    if outcome == "revised":
        if entry["candidate_sha256"] == workflow._hash(files.get(workflow._spec(item))) and derived.get("execution") != attempt:
            raise ProjectError("a revised design must contain changed candidate content")
    if saved is None:
        saved = {"identity": identity, "item": identifier,
                 "dispatch_sha256": workflow._hash(workflow._canonical(entry["spawn"])),
                 "capture_write_hashes": {name: workflow._hash(content) for name, content in
                                          store.write_item(files, item).items()
                                          if workflow._hash(content) != workflow._hash(files.get(name))}}
        saved.update({key: copy.deepcopy(entry[key]) for key in
                      ("result", "report", "candidate", "candidate_sha256") if key in entry})
        _save_capture(root, attempt, saved)
    publication = _publish(root, files, [item], identity, "Capture execution result " + identifier, publish)
    if publication.get("status") not in {"published", "no_op"}:
        return _pending_result(root, identifier, attempt, publication)
    if outcome not in {"blocked", "contract-change"} and role in {"design-review", "code-review", "design-revision"}:
        operation = "design-update" if outcome == "revised" or role == "design-revision" else OPERATIONS[role]
        options = {"execution": attempt}
        if operation == "development-finish":
            options.update(result=outcome, provenance=_provenance(captured), reviewer_session=entry["worker_id"], review_file=captured["report_file"])
        files = workflow._snapshot(root)
        item = store.item(files, identifier)
        retained = entry.get("result_ticket") or _preparation_ticket(root, item, entry, identity, operation=operation)
        if retained:
            prepared = _stage_ticket(root, files, item, {**entry, "result_ticket": retained}, key="result_ticket")
        elif role == "design-review" and outcome == "revised" and entry.get("workflow_ticket"):
            review_ticket = _stage_ticket(root, files, item, entry)
            if review_ticket["editable"]:
                review_path = next(value["path"] for value in review_ticket["editable"] if Path(value["path"]).name == "report.md")
                Path(review_path).write_text(report, encoding="utf-8")
            completed_review = workflow.finish(root, review_ticket["ticket"], options={"result": "fail", "provenance": _provenance(captured)}, publish=publish)
            if completed_review.get("status") not in {"published", "no_op"}:
                return _pending_result(root, identifier, attempt, completed_review)
            prepared = workflow.begin(root, operation, identifier, options=options, publish=publish)
        elif role in {"design-review", "design-revision"} and entry.get("workflow_ticket"):
            prepared = _stage_ticket(root, files, item, entry)
        else:
            prepared = workflow.begin(root, operation, identifier, options=options, publish=publish)
        if prepared.get("status") != "ready":
            return _pending_result(root, identifier, attempt, prepared)
        if not entry.get("result_ticket"):
            files = workflow._snapshot(root)
            item = store.item(files, identifier)
            item["workflow"]["autonomy"]["executions"][attempt]["result_ticket"] = prepared["ticket"]
            saved = _publish(root, files, [item], identity, "Bind result checkpoint " + identifier, publish)
            if saved.get("status") not in {"published", "no_op"}:
                return _pending_result(root, identifier, attempt, saved)
            files = workflow._snapshot(root)
            item = store.item(files, identifier)
            entry = item["workflow"]["autonomy"]["executions"][attempt]
            prepared = _stage_ticket(root, files, item, entry, key="result_ticket")
        content = candidate if operation == "design-update" else report
        if prepared["editable"] and captured.get("mechanical_correction"):
            target_spec = next(value for value in prepared["editable"] if Path(value["path"]).name == "spec.md")
            Path(target_spec["path"]).write_text(candidate, encoding="utf-8")
        if prepared["editable"]:
            target = next(value for value in prepared["editable"] if Path(value["path"]).name == ("spec.md" if operation == "design-update" else "report.md"))
            Path(target["path"]).write_text(content, encoding="utf-8")
        finish_options = {"result": outcome, "provenance": _provenance(captured)} if operation == "design-review" else None
        if operation == "design-review" and outcome == "pass" and (workflow._design_reuse().pending(files, item) or captured.get("mechanical_correction")):
            finish_options["contract_unchanged"] = captured.get("contract_unchanged")
        if captured.get("mechanical_correction"):
            finish_options["mechanical_correction"] = True
        finished = workflow.finish(root, prepared["ticket"], options=finish_options, publish=publish)
        if finished.get("status") not in {"published", "no_op"}:
            return _pending_result(root, identifier, attempt, finished)
    files = workflow._snapshot(root)
    item = store.item(files, identifier)
    state = _state(item)
    state.pop("current", None)
    state.pop("acceptance", None)
    if outcome in {"blocked", "contract-change"} or (outcome == "fail" and role in {"implementation", "fix", "baseline", "rebase"}):
        state["blocker"] = "user_contract_decision_required" if outcome == "contract-change" else "executor_blocked"
        if role in {"implementation", "fix", "baseline", "rebase"}:
            state["next_role"] = role
        if outcome == "contract-change":
            workflow._invalidate_implementation(item)
            item["design"].pop("approval", None)
            item["design"].pop("review", None)
            item.setdefault("workflow", {}).pop("design_basis", None)
            item["workflow"].pop("design_reuse", None)
            item["workflow"].pop("design_review_failure", None)
            item["design"]["state"] = "draft"
    else:
        state.pop("blocker", None)
        state["next_role"] = ("design-review" if outcome == "revised" or role == "design-revision" else
                              "design-revision" if role == "design-review" and outcome == "fail" else
                              "code-review" if role == "design-review" and (_predevelopment().state(item) or {}).get("rebased") else
                              "implementation" if role == "design-review" else
                              "fix" if role == "code-review" and outcome == "fail" else "code-review")
        if role in {"baseline", "rebase"}:
            _predevelopment().complete_writer(root, files, item, role)
        if role == "code-review" and outcome == "pass" and (_predevelopment().state(item) or {}).get("phase") == "reconciling":
            if not _predevelopment().state(item).get("rebased"):
                raise ProjectError("formal code review requires completed convergence")
            workflow._approved(files, item)
            _predevelopment().state(item)["phase"] = "formal"
        if role in {"implementation", "fix"}:
            development = item.get("development") or {}
            development.pop("review", None)
            development.pop("reviewed_snapshot", None)
            item["status"] = "developing"
    state["executions"][attempt]["finished_at"] = workflow._now()
    item["owner"] = identity if item.get("status") == "developing" else None
    publication = _publish(root, files, [item], identity, "Complete execution " + identifier, publish)
    return publication if publication.get("status") in {"published", "no_op"} else _pending_result(root, identifier, attempt, publication)


def _terminal_receipt(captured):
    if captured.get("host") == "codex" and captured.get("tool", "").rsplit(".", 1)[-1] in {
            "spawn_agent", "followup_task", "send_message", "interrupt_agent"}:
        raise ProjectError("execution termination requires a worker lifecycle query or wait receipt")
    terminal = captured.get("terminal_status")
    if terminal not in {"completed", "failed", "stopped"} or captured.get("descendants_stopped") is not True:
        raise ProjectError("execution requires observed terminal worker status and confirmed descendant cleanup")
    worker = captured["worker_id"]
    identity_keys = {"worker_id", "agent_id", "agent_name", "task_name", "target"}
    status_keys = {"status", "worker_status", "agent_status"}
    def status_matches(node):
        if isinstance(node, str):
            return node == terminal
        if isinstance(node, dict):
            return terminal in node or any(status_matches(value) for key, value in node.items() if key in status_keys)
        return False
    def observed(node):
        if isinstance(node, list):
            return any(observed(value) for value in node)
        if not isinstance(node, dict):
            return False
        direct = any(node.get(key) == worker for key in identity_keys)
        arguments = node.get("arguments")
        targeted = isinstance(arguments, dict) and any(arguments.get(key) == worker for key in identity_keys)
        if direct and any(status_matches(node.get(key)) for key in status_keys):
            return True
        if targeted and isinstance(node.get("result"), dict) and any(status_matches(node["result"].get(key)) for key in status_keys):
            return True
        return any(observed(value) for value in node.values())
    if not observed(captured["raw"]):
        raise ProjectError("raw receipt must associate the terminal status with the actual worker")


def _captured_body(entry, name):
    artifact = entry.get(name) or {}
    body = artifact.get("body")
    if not isinstance(body, str) or workflow._hash(body) != artifact.get("sha256"):
        raise ProjectError("invalid captured " + name + " content or hash")
    if name == "candidate" and artifact["sha256"] != entry.get("candidate_sha256"):
        raise ProjectError("captured candidate does not match its revision binding")
    return body


def _result_outcome(captured):
    _terminal_receipt(captured)
    outcome = captured.get("outcome")
    if outcome not in {"pass", "fail", "blocked", "revised", "contract-change"}:
        raise ProjectError("unknown execution outcome")
    if outcome != "blocked" and captured["terminal_status"] != "completed":
        raise ProjectError("a stage verdict requires a completed worker; interrupted workers may only report blocked")
    role = captured.get("role")
    mechanical = captured.get("mechanical_correction")
    if mechanical is not None and mechanical is not True:
        raise ProjectError("mechanical_correction must be an explicit true declaration")
    if mechanical and (role != "design-review" or outcome != "pass" or captured.get("contract_unchanged") is not True or not captured.get("candidate_file")):
        raise ProjectError("mechanical correction requires design-review pass, candidate and unchanged approved contract")
    if captured.get("candidate_file") and outcome != "revised" and not mechanical:
        raise ProjectError("a changed candidate requires a mechanical correction declaration or a separate revision")
    if outcome == "revised" and role not in {"design-review", "design-revision"}:
        raise ProjectError("only design stages may return a revised design")
    if role == "design-revision" and outcome not in {"revised", "blocked", "contract-change"}:
        raise ProjectError("design revision must return a candidate or a blocker")
    return outcome


def retire(root, selector, *, receipt, publish=None):
    """Close an unusable attempt after its actual worker stopped; accept no verdict."""
    root, files = _files(root)
    identity = workflow._identity(root)
    item = store.item(files, workflow._resolve(store.items(files), selector))
    _owned(item, identity)
    captured = _receipt(receipt)
    state = _state(item)
    attempt = captured.get("attempt")
    entry = state.get("executions", {}).get(attempt)
    if not entry or state.get("current") != attempt:
        raise ProjectError("retirement requires the current same-owner attempt")
    if any(captured.get(key) != entry.get(key) for key in ("worker_id", "role", "input_binding")) or captured["host"] != entry["spawn"]["host"]:
        raise ProjectError("retirement receipt does not match the original host execution")
    _terminal_receipt(captured)
    entry["retirement"] = {"receipt": captured, "recorded_by": identity["session"],
                           "reason": "unusable_stage_result", "created_at": workflow._now()}
    entry["finished_at"] = workflow._now()
    state.pop("current", None)
    state.pop("acceptance", None)
    state["blocker"] = "retired_execution_requires_explicit_restart"
    item["owner"] = identity if item.get("status") == "developing" else None
    return _publish(root, files, [item], identity, "Retire stopped execution " + item["id"], publish)


def _cleaned_code_root(root, files, item):
    """Allow historical reads only within the verified removed delivered worktree."""
    if (item.get("status") != "done" or item.get("delivery", {}).get("status") != "delivered" or
            item.get("cleanup") != "done" or not item.get("delivery", {}).get("record")):
        raise ProjectError("historical acceptance requires recorded delivery and verified cleanup")
    workflow.retention.live_record_paths(files, item["id"])
    record_id = item.get("workflow", {}).get("cleanup_record")
    name = "workitems/" + item["id"] + "/records/" + str(record_id) + ".yaml"
    cleanup = store.load_yaml(files[name], name) if name in files else {}
    if cleanup.get("status") != "done" or cleanup.get("mode") != "verify":
        raise ProjectError("historical acceptance requires recorded delivery and verified cleanup")
    location = Path(workflow._development_module().worktree_location(root, item, store.project(files)))
    if location.exists() or any(path.is_symlink() for path in (location, *location.parents)):
        raise ProjectError("historical acceptance requires the recorded code worktree to remain removed")
    return location


def _acceptance_review(root, files, item):
    if (_predevelopment().state(item) or {}).get("phase") in {"preparing", "baseline", "speculative", "reconciling"}:
        raise ProjectError("predevelopment requires formal convergence before human acceptance")
    if not _approved_contract(files, item):
        raise ProjectError("user acceptance requires the current approved contract")
    missing_root = _cleaned_code_root(root, files, item) if item.get("cleanup") == "done" else None
    workflow._implementation_approved(files, item, missing_root=missing_root)
    review = item["development"]["review"]
    current = (item["development"].get("reviewed_snapshot", {}) if missing_root is not None else
               workflow._code_snapshot(root, item, store.project(files)))
    if review.get("code_snapshot", {}).get("tree") != current.get("tree"):
        raise ProjectError("user modifications require independent review before acceptance")


def accept(root, selector, *, approval_source, publish=None):
    workflow._text(approval_source, "actual user acceptance source")
    root, files = _files(root)
    identity = workflow._identity(root)
    item = store.item(files, workflow._resolve(store.items(files), selector))
    workflow._ownership(item, identity)
    if _state(item).get("current"):
        raise ProjectError("cannot accept while executor liveness is unresolved")
    if item.get("kind") != "aggregate":
        _acceptance_review(root, files, item)
    _state(item)["acceptance"] = {"status": "accepted", "source": approval_source,
        "recorded_by": identity["session"], "created_at": workflow._now(), "binding": _artifact_binding(root, files, item)}
    return _publish(root, files, [item], identity, "Record user acceptance " + item["id"], publish)


def validate_state(item):
    """Validate persisted dispatch/result structure independently of CLI callers."""
    _predevelopment()._lifecycle().validate(item)
    workflow._design_reuse().validate(item)
    state = (item.get("workflow") or {}).get("autonomy")
    if state is None:
        return
    if not isinstance(state, dict):
        raise ProjectError("autonomy must be an object")
    _predevelopment().validate(item)
    authorization = state.get("authorization")
    if authorization is not None:
        if not isinstance(authorization, dict):
            raise ProjectError("autonomy authorization must be an object")
        for key in ("source", "coordinator"):
            workflow._text(authorization.get(key), "autonomy authorization " + key)
        if not isinstance(authorization.get("scope"), list) or item["id"] not in authorization["scope"]:
            raise ProjectError("autonomy authorization must explicitly include its item")
    executions = state.get("executions", {})
    if not isinstance(executions, dict):
        raise ProjectError("autonomy executions must be an object")
    for attempt, entry in executions.items():
        if (not isinstance(attempt, str) or not workflow.TICKET.fullmatch(attempt) or not isinstance(entry, dict) or
                entry.get("attempt") != attempt or entry.get("item") != item["id"] or entry.get("role") not in ROLES or
                not isinstance(entry.get("input_binding"), dict)):
            raise ProjectError("invalid autonomy execution item/role/attempt/input")
        reads = entry.get("read_hashes", {})
        if not isinstance(reads, dict) or any(not isinstance(name, str) or not Path(name).is_absolute() or
                (digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)))
                for name, digest in reads.items()):
            raise ProjectError("autonomy read guards must map original absolute paths to hashes or absence")
        spawned = _receipt(entry.get("spawn"))
        if spawned["worker_id"] != entry.get("worker_id"):
            raise ProjectError("autonomy execution worker differs from native spawn receipt")
        retirement = entry.get("retirement")
        if retirement is not None:
            if not isinstance(retirement, dict):
                raise ProjectError("autonomy retirement must retain its actual terminal receipt")
            terminal = _receipt(retirement.get("receipt"))
            _terminal_receipt(terminal)
            if any(terminal.get(key) != entry.get(key) for key in ("attempt", "worker_id", "role", "input_binding")):
                raise ProjectError("autonomy retirement differs from its dispatch")
        captured = entry.get("result")
        if captured is not None:
            _receipt(captured)
            outcome = _result_outcome(captured)
            if any(captured.get(key) != entry.get(key) for key in ("attempt", "worker_id", "role", "input_binding")):
                raise ProjectError("autonomy result differs from its dispatch")
            _captured_body(entry, "report")
            if outcome == "revised" or entry.get("candidate") is not None:
                _captured_body(entry, "candidate")
    if state.get("current") is not None and state["current"] not in executions:
        raise ProjectError("autonomy current must reference an existing execution")
    for key in ("code_authors", "design_authors"):
        if key in state and (not isinstance(state[key], list) or any(not runtime._nonempty(value) for value in state[key])):
            raise ProjectError("autonomy authors must be actual worker identities")
    acceptance = state.get("acceptance")
    if acceptance is not None and (not isinstance(acceptance, dict) or acceptance.get("status") != "accepted" or
            not runtime._nonempty(acceptance.get("source")) or not isinstance(acceptance.get("binding"), dict)):
        raise ProjectError("autonomy acceptance requires explicit user source and artifact binding")
    approval = (item.get("design") or {}).get("approval") or {}
    if approval.get("kind") == "derived_revision":
        original = approval.get("original_user_approval") or {}
        if original.get("kind") != "user" or not original.get("source") or not approval.get("execution"):
            raise ProjectError("derived revision must retain its real original user approval")

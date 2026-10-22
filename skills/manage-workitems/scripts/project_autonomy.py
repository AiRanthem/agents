"""Scope authorization and artifact readiness; agents own their execution trees."""
import copy
from pathlib import Path

try:
    import project_runtime as runtime
    import project_store as store
    import project_workflow as workflow
except ImportError:
    from . import project_runtime as runtime, project_store as store, project_workflow as workflow

ProjectError = runtime.ProjectError
OPERATIONS = {"design-review": "design-review", "implementation": "development-start",
              "code-review": "development-finish", "design-revision": "design-update"}


def _state(item):
    return item.setdefault("workflow", {}).setdefault("autonomy", {})


def release_execution_state(item):
    """Keep content attribution; historical worker scheduling is not a project lock."""
    state = (item.get("workflow") or {}).get("autonomy")
    if not isinstance(state, dict):
        return
    records = item["workflow"]
    reviews = [item.get("design", {}).get("review"), (item.get("development") or {}).get("review"),
               records.get("design_basis", {}).get("review"), records.get("design_review_failure")]
    guards = {}
    for review in reviews:
        if not review or not review.get("execution"):
            continue
        guard = _legacy_review_guard(item, review)
        if guard:
            guards[review["id"]] = guard
    if guards:
        records["review_guards"] = guards
    else:
        records.pop("review_guards", None)
    if not state.get("implementation"):
        products = [product for entry in state.get("executions", {}).values()
                    if (product := _legacy_product(entry))]
        if products:
            state["implementation"] = max(products, key=lambda value: value["created_at"])
    for key in ("code_authors", "design_authors"):
        previous = state.pop(key, [])
        authors = item["workflow"].setdefault(key, []) if previous else item["workflow"].get(key, [])
        for author in previous:
            if author not in authors:
                authors.append(author)
    for key in ("current", "executions", "next_role", "blocker"):
        state.pop(key, None)


def _legacy_review_guard(item, review):
    """Retain old content evidence without a dependency on its executor record."""
    records = item.get("workflow") or {}
    saved = records.get("review_guards", {}).get(review.get("id"))
    if saved and saved.get("review_sha256") == workflow._hash(workflow._canonical(review)):
        return copy.deepcopy(saved)
    entry = (records.get("autonomy") or {}).get("executions", {}).get(review.get("execution")) or {}
    if not entry.get("read_hashes") or not entry.get("input_binding", {}).get("project_sha256"):
        return None
    return {"review_sha256": workflow._hash(workflow._canonical(review)),
            "project_sha256": entry["input_binding"]["project_sha256"],
            "read_hashes": copy.deepcopy(entry["read_hashes"])}


def _legacy_product(entry):
    if not isinstance(entry, dict):
        return None
    result, report = entry.get("result") or {}, entry.get("report") or {}
    if (entry.get("role") not in {"implementation", "fix"} or not entry.get("finished_at") or
            result.get("outcome") != "pass" or
            not runtime._nonempty(report.get("body")) or workflow._hash(report["body"]) != report.get("sha256")):
        return None
    return {"binding": copy.deepcopy(entry.get("output_binding") or {}), "report": copy.deepcopy(report),
            "provenance": "retained-report-sha256:" + report["sha256"], "created_at": entry["finished_at"],
            "instruction_changes": copy.deepcopy(entry.get("instruction_changes", {})),
            "review_sha256": workflow._hash(workflow._canonical(None))}


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
    candidates.add(root / store.project_path(files))
    anchors = {root, root / "workitems" / item["id"]} | {Path(entry["path"]).parent for entry in read if Path(entry["path"]).name == "AGENTS.md"}
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


def _validate_reads(entry, *, revised_spec=None, missing_root=None, defer_instructions=False):
    changed = {}
    for name, expected in entry.get("read_hashes", {}).items():
        path = Path(name)
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise ProjectError("required read source is stale: " + name)
        if missing_root is not None and path.is_relative_to(missing_root) and not path.exists():
            continue
        if path.exists() and not path.is_file():
            raise ProjectError("required read source is stale: " + name)
        actual = workflow._hash(path.read_bytes()) if path.is_file() else None
        if actual != expected and not (actual is not None and revised_spec and name == revised_spec and actual == entry.get("candidate_sha256")):
            if defer_instructions and path.name == "AGENTS.md":
                changed[name] = {"before_sha256": expected, "after_sha256": actual}
                continue
            raise ProjectError("required read source is stale: " + name)
    return changed


def _implementation_current(root, files, item):
    state = _state(item)
    completion = state.get("implementation") or state.get("transformations", {}).get("rebase") or {}
    if not completion:
        products = [product for entry in state.get("executions", {}).values() if (product := _legacy_product(entry))]
        completion = max(products, key=lambda value: value["created_at"]) if products else {}
    return (completion.get("binding") == _binding(root, files, item) and
            completion.get("review_sha256") == workflow._hash(workflow._canonical((item.get("development") or {}).get("review"))))


def review_inputs_current(files, item, review, *, missing_root=None):
    basis = (item.get("workflow") or {}).get("design_basis") or {}
    guard = review if review.get("read_hashes") else basis if basis.get("review") == review else {}
    if review.get("execution"):
        legacy = _legacy_review_guard(item, review) or {}
        if legacy and legacy.get("project_sha256") != workflow._hash(files[store.project_path(files)]):
            return False
        if not guard.get("read_hashes"):
            guard = legacy
        if not legacy and not any(name.endswith("/" + store.project_path(files)) for name in guard.get("read_hashes", {})):
            return False
    if not guard.get("read_hashes"):
        # Ordinary historical reviews have no read guard. New checkpoints always
        # bind their required reads; source and contract bindings still apply.
        return not review.get("execution")
    try:
        _validate_reads(guard, missing_root=missing_root)
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
        release_execution_state(item)
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
    if not authorization or not workflow._ownership_module().authorized(item, identity):
        raise ProjectError("autonomy has another control claim; use explicit takeover")


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
    if workflow._validation_waived(files, item, "human-acceptance"):
        return True
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
    if workflow._validation_waived(files, item, "dependencies"):
        return []
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
    waivers = ((item.get("workflow") or {}).get("validation_waivers") or {})
    if waivers:
        result["verification_waivers"] = {gate: {"source": waiver.get("source"), "result": "skipped",
                                               "current": workflow._validation_waived(files, item, gate)}
                                          for gate, waiver in waivers.items()}
    review = (item.get("development") or {}).get("review") or {}
    if review.get("approval_kind") == "human_acceptance":
        result["implementation_approval_kind"] = "human_acceptance"
        result["implementation_approval_source"] = review.get("source")
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
    identity = workflow._identity(root, item=item["id"], create=False) if authorization or item.get("owner") else {"session": session, "token": None}
    if not authorization:
        result["reasons"].append("not_authorized")
    elif not workflow._ownership_module().authorized(item, identity):
        result["reasons"].append("control_claim_required")
    owner = item.get("owner") or {}
    if owner and owner.get("token") != identity["token"] and "control_claim_required" not in result["reasons"]:
        result["reasons"].append("control_claim_required")
    waived_design = workflow._validation_waived(files, item, "design-review")
    assess_reuse = not waived_design and not result["reasons"] and workflow._design_reuse().needed(root, files, item, session)
    pending_confirmation = not waived_design and workflow._design_reuse().pending(files, item)
    if not waived_design and not assess_reuse and not pending_confirmation and not _approved_contract(files, item):
        result["reasons"].append("approved_initial_design_required")
    if not assess_reuse and not pending_confirmation and authorization and authorization.get("requirement_sha256") != _contract(files, item)["requirement_sha256"]:
        result["reasons"].append("authorization_contract_changed")
    if not assess_reuse and not pending_confirmation and authorization and authorization.get("decision_sha256") != workflow._hash(files.get(workflow._documents(item)["decision"])):
        result["reasons"].append("authorization_decision_changed")
    if not result["reasons"] and ((item.get("workflow") or {}).get("lifecycle") or {}).get("replacement_pending"):
        result.update(state="ready", next_action="lifecycle_prepare")
        return result
    if not result["reasons"] and not workflow._validation_waived(files, item, "formal-convergence"):
        extra = _predevelopment().schedule(root, files, item, session)
        if extra:
            result.update(extra)
            return result
    result["reasons"].extend(_dependency_blocks(root, files, item))
    if result["reasons"]:
        result["state"] = "blocked"
        return result
    if assess_reuse:
        result.update(state="ready", next_action="design_reuse_assessment")
        return result
    binding = _binding(root, files, item)
    development = item.get("development") or {}
    review = development.get("review") or {}
    reviewed = (review.get("result") == "pass" and bool(review.get("code_snapshot")) and review["code_snapshot"].get("tree") == (binding.get("code_snapshot") or {}).get("tree")) or workflow._validation_waived(files, item, "implementation-review")
    if reviewed:
        try:
            workflow._implementation_approved(files, item)
        except ProjectError:
            reviewed = False
    if reviewed:
        extra = None if workflow._validation_waived(files, item, "formal-convergence") else _predevelopment().schedule(root, files, item, session, reviewed=True)
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
    formal_review = ((_predevelopment().state(item) or {}).get("phase") in {"reconciling", "formal"} or
                     ((item.get("workflow") or {}).get("lifecycle") or {}).get("fresh_reviews_required"))
    if item.get("design", {}).get("review", {}).get("result") == "fail" and not waived_design:
        role = "design-revision"
    elif not design_review_current and (formal_review or not authorization.get("skip_design_review") or
            item.get("design", {}).get("approval", {}).get("kind") == "derived_revision"):
        role = "design-review"
    elif _implementation_current(root, files, item):
        role = "code-review"
    elif item.get("status") == "awaiting_delivery" and review.get("result") == "pass":
        role = "code-review"
    elif not development or item.get("status") not in {"developing", "awaiting_delivery"}:
        role = "implementation"
    elif review.get("result") == "fail":
        role = "fix"
    else:
        role = "implementation"
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
    for state in ("ready", "blocked", "awaiting_acceptance", "awaiting_predecessor_delivery", "accepted_awaiting_delivery", "completed"):
        result[state] = [entry["id"] for entry in entries if entry["state"] == state]
    result["round_finished"] = not result["ready"]
    return result


def authorize(root, *, approval_source, all_items=False, tree=None, items=None, skip_design_review=False, predevelop=False, publish=None):
    workflow._text(approval_source, "explicit user advancement authorization source")
    root, files = _files(root)
    selected = scope(files, all_items=all_items, tree=tree, items=items)
    groups = {}
    for identifier in selected:
        identity = workflow._identity(root, item=identifier)
        groups.setdefault(identity["token"], {"identity": identity, "items": []})["items"].append(identifier)
    authorized, blocked, publications = [], [], []
    for group in groups.values():
        if publications:
            root, files = _files(root)
        response = _authorize_group(root, files, group["items"], selected, group["identity"],
            approval_source, skip_design_review, predevelop, publish)
        authorized.extend(response["authorized"])
        blocked.extend(response["blocked_items"])
        publications.append(response)
        if response["status"] not in {"published", "no_op"}:
            remaining = [key for key in selected if key not in authorized and key not in {value["id"] for value in blocked}]
            return {**response, "authorized": authorized, "blocked_items": blocked, "remaining_items": remaining}
    if len(publications) == 1:
        return publications[0]
    return {"status": "published" if any(value["status"] == "published" for value in publications) else "no_op",
            "authorized": authorized, "blocked_items": blocked, "publications": publications}


def _authorize_group(root, files, identifiers, selected, identity, approval_source, skip_design_review, predevelop, publish):
    """Keep each publication within one claim while retaining the requested scope."""
    records, blocked = [], []
    for identifier in identifiers:
        item = store.item(files, identifier)
        state = _state(item)
        owner = item.get("owner") or {}
        handoff = ((item.get("workflow") or {}).get("lifecycle") or {}).get("handoff")
        if handoff and not workflow._ownership_module().handoff_authorized(handoff, identity):
            blocked.append({"id": identifier, "reason": "recorded_coordinator_handoff"})
            continue
        if (owner and owner.get("token") != identity["token"]) or not workflow._ownership_module().authorized(item, identity):
            blocked.append({"id": identifier, "reason": "control_claim_required"})
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
                                  "claim_token": identity["token"],
                                  "scope": selected, "created_at": workflow._now(),
                                  "requirement_sha256": _contract(files, item)["requirement_sha256"],
                                  "decision_sha256": workflow._hash(files.get(workflow._documents(item)["decision"])),
                                  "skip_design_review": bool(skip_design_review)}
        state["authorization"]["predevelop"] = bool(predevelop)
        state.pop("blocker", None)
        records.append(item)
    publication = _publish(root, files, records, identity, "Authorize project advancement", publish) if records else {"status": "no_op"}
    confirmed = publication["status"] in {"published", "no_op"}
    return {**publication, "authorized": [item["id"] for item in records] if confirmed else [],
            "blocked_items": blocked, **({"pending_authorization": [item["id"] for item in records]} if not confirmed else {})}


def _read_report(path):
    selected = Path(workflow._text(path, "report file")).absolute()
    if any(part.is_symlink() for part in (selected, *selected.parents)) or not selected.is_file():
        raise ProjectError("report/candidate must be an actual regular file without symlinks")
    content = selected.read_text(encoding="utf-8")
    workflow._text(content, "report/candidate body")
    return content


def begin_transform(root, selector, *, role, author_session, publish=None):
    if role not in {"baseline", "rebase"}:
        raise ProjectError("only baseline/rebase prepare a Git transformation")
    workflow._text(author_session, "actual source author")
    root, files = _files(root)
    item = store.item(files, workflow._resolve(store.items(files), selector))
    identity = workflow._identity(root, item=item["id"])
    _owned(item, identity)
    readiness = _next(root, files, item, identity["session"])
    if readiness.get("next_role") != role:
        raise ProjectError("Git transformation is not ready: " + str(readiness))
    _predevelopment().prepare_writer(root, files, item, role, author_session=author_session)
    item["owner"] = identity
    _state(item)["transformation_basis"] = {"role": role, "binding": _binding(root, files, item, code=False),
        "read_hashes": _read_hashes(root, files, item, role)}
    result = _publish(root, files, [item], identity, "Prepare Git transformation " + item["id"], publish)
    if result["status"] not in {"published", "no_op"}:
        return result
    return {**result, "item": item["id"], "role": role,
            "read": _payload(root, files, item, role),
            "approved_contract": copy.deepcopy(_state(item).get("approved_contract")),
            "code_context": workflow._code_context(root, item, store.project(files)),
            "git_operation": _predevelopment().writer_context(item, role),
            "prerequisites": copy.deepcopy(_predevelopment().pins(item))}


def complete(root, selector, *, role, report_file, provenance, publish=None):
    """Record a verified work product, without registering a worker or its lifetime."""
    if role not in {"implementation", "fix", "baseline", "rebase"}:
        raise ProjectError("unsupported work product role")
    workflow._text(provenance, "actual work product provenance")
    report = _read_report(report_file)
    root, files = _files(root)
    item = store.item(files, workflow._resolve(store.items(files), selector))
    identity = workflow._identity(root, item=item["id"])
    _owned(item, identity)
    if role in {"baseline", "rebase"}:
        basis = _state(item).get("transformation_basis") or {}
        if basis.get("role") != role or basis.get("binding") != _binding(root, files, item, code=False):
            raise ProjectError("Git transformation inputs changed; prepare the current transformation")
        _validate_reads(basis)
        _predevelopment().complete_writer(root, files, item, role)
        target = _state(item).setdefault("transformations", {})
        key = role
        changes = {}
    else:
        basis = _state(item).get("implementation_basis") or {}
        if item.get("status") != "developing" or basis.get("binding") != _binding(root, files, item, code=False):
            raise ProjectError("implementation contract changed; begin a current development-start checkpoint")
        changes = _validate_reads(basis, defer_instructions=True)
        target, key = _state(item), "implementation"
        development = item.get("development") or {}
        development.pop("reviewed_snapshot", None)
    binding = _binding(root, files, item)
    product = {"binding": binding, "report": {"body": report, "sha256": workflow._hash(report)},
               "provenance": provenance, "created_at": workflow._now(), "instruction_changes": changes}
    if role in {"implementation", "fix", "rebase"}:
        product["review_sha256"] = workflow._hash(workflow._canonical((item.get("development") or {}).get("review")))
    target[key] = product
    if _binding(root, files, item) != binding:
        raise ProjectError("work product source changed while recording completion")
    return _publish(root, files, [item], identity, "Record work product " + item["id"], publish)


def validate_state(item):
    _predevelopment()._lifecycle().validate(item)
    workflow._design_reuse().validate(item)
    workflow._ownership_module().validate(item)
    waivers = (item.get("workflow") or {}).get("validation_waivers", {})
    if not isinstance(waivers, dict):
        raise ProjectError("validation waivers must be named records")
    for gate, record in waivers.items():
        if (not isinstance(record, dict) or record.get("kind") != "validation-waiver" or
                record.get("gate") != gate or record.get("item") != item["id"] or
                record.get("result") != "skipped" or not runtime._nonempty(record.get("source")) or
                not workflow.TICKET.fullmatch(str(record.get("id", ""))) or
                not isinstance(record.get("read_hashes"), dict) or not record["read_hashes"]):
            raise ProjectError("validation waiver requires its actual user source, item, gate and input guards")
    guards = (item.get("workflow") or {}).get("review_guards", {})
    if not isinstance(guards, dict):
        raise ProjectError("review content guards must be an object")
    for key, guard in guards.items():
        if (not isinstance(key, str) or not isinstance(guard, dict) or
                any(not isinstance(guard.get(name), str) or not runtime.HASH.fullmatch(guard[name])
                    for name in ("review_sha256", "project_sha256")) or not isinstance(guard.get("read_hashes"), dict) or
                not guard["read_hashes"] or any(not isinstance(path, str) or
                    value is not None and (not isinstance(value, str) or not runtime.HASH.fullmatch(value))
                    for path, value in guard["read_hashes"].items())):
            raise ProjectError("review content guards require exact content and input hashes")
    state = (item.get("workflow") or {}).get("autonomy") or {}
    authorization = state.get("authorization")
    if authorization is not None:
        if not isinstance(authorization, dict):
            raise ProjectError("autonomy authorization must be an object")
        for key in ("source", "coordinator"):
            workflow._text(authorization.get(key), "autonomy authorization " + key)
        if "claim_token" in authorization:
            workflow._text(authorization["claim_token"], "autonomy control claim token")
        if not isinstance(authorization.get("scope"), list) or item["id"] not in authorization["scope"]:
            raise ProjectError("autonomy authorization must include its item")
    for value in [state.get("implementation"), *state.get("transformations", {}).values()]:
        if value is not None and (not isinstance(value, dict) or not isinstance(value.get("binding"), dict) or
                not runtime._nonempty(value.get("provenance")) or not isinstance(value.get("report"), dict) or
                not runtime._nonempty(value["report"].get("body")) or
                workflow._hash(value["report"].get("body")) != value["report"].get("sha256")):
            raise ProjectError("work product requires its exact artifact binding and report")
    acceptance = state.get("acceptance")
    if acceptance is not None and (not isinstance(acceptance, dict) or acceptance.get("status") != "accepted" or
            not runtime._nonempty(acceptance.get("source")) or not isinstance(acceptance.get("binding"), dict)):
        raise ProjectError("autonomy acceptance requires explicit user source and artifact binding")
    approval = item.get("design", {}).get("approval") or {}
    if approval.get("kind") == "derived_revision":
        original = approval.get("original_user_approval") or {}
        if original.get("kind") != "user" or not original.get("source") or not (approval.get("revision") or approval.get("execution")):
            raise ProjectError("derived revision must retain its real original approval and revision checkpoint")


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
    if (_predevelopment().state(item) or {}).get("phase") in {"preparing", "baseline", "speculative", "reconciling"} and not workflow._validation_waived(files, item, "formal-convergence"):
        raise ProjectError("predevelopment requires formal convergence before human acceptance")
    if not _approved_contract(files, item) and not workflow._validation_waived(files, item, "design-review"):
        raise ProjectError("user acceptance requires the current approved contract")
    missing_root = _cleaned_code_root(root, files, item) if item.get("cleanup") == "done" else None
    workflow._implementation_approved(files, item, missing_root=missing_root)
    review = item["development"].get("review") or {}
    current = (item["development"].get("reviewed_snapshot", {}) if missing_root is not None else
               workflow._code_snapshot(root, item, store.project(files)))
    waived = workflow._validation_waived(files, item, "implementation-review", missing_root=missing_root)
    snapshot = item["workflow"]["validation_waivers"]["implementation-review"].get("code_snapshot", {}) if waived else review.get("code_snapshot", {})
    if snapshot.get("tree") != current.get("tree"):
        raise ProjectError("implementation approval does not cover the current code")


def accept(root, selector, *, approval_source, publish=None):
    workflow._text(approval_source, "actual user acceptance source")
    root, files = _files(root)
    item = store.item(files, workflow._resolve(store.items(files), selector))
    identity = workflow._identity(root, item=item["id"])
    workflow._ownership(item, identity)
    extra = {}
    if item.get("kind") != "aggregate":
        if not item.get("development"):
            raise ProjectError("human acceptance requires recorded development")
        # An actual current human acceptance can replace missing/failed/stale code
        # review, but does not silently waive another design or convergence gate.
        try:
            _acceptance_review(root, files, item)
        except ProjectError:
            if (_predevelopment().state(item) or {}).get("phase") in {"preparing", "baseline", "speculative", "reconciling"} and not workflow._validation_waived(files, item, "formal-convergence"):
                raise ProjectError("predevelopment requires formal convergence before human acceptance")
            if not _approved_contract(files, item) and not workflow._validation_waived(files, item, "design-review"):
                raise ProjectError("user acceptance requires the current approved contract")
            if item.get("design", {}).get("review", {}).get("result") == "fail" and not workflow._validation_waived(files, item, "design-review"):
                raise ProjectError("unresolved independent design findings block implementation acceptance")
            manifest = {"ticket": workflow.secrets.token_hex(16), "identity": identity,
                        "created_at": workflow._now(), "base_commit": workflow._base(item),
                        "options": {"provenance": approval_source}}
            record = workflow._report(root, manifest, item, files, extra, "development-finish",
                                      "# Human acceptance\n\n" + approval_source + "\n")
            current = workflow._code_snapshot(root, item, store.project(files))
            record.update(result="pass", approval_kind="human_acceptance", source=approval_source,
                          recorded_by=identity["session"], code_snapshot=current,
                          read_hashes=_read_hashes(root, files, item, "code-review"))
            extra["workitems/" + item["id"] + "/records/" + record["id"] + ".yaml"] = store.dump_yaml(record)
            item["development"].update(review=record, reviewed_snapshot=current)
            item["status"], item["owner"] = "awaiting_delivery", None
            _acceptance_review(root, files, item)
    _state(item)["acceptance"] = {"status": "accepted", "source": approval_source,
        "recorded_by": identity["session"], "created_at": workflow._now(), "binding": _artifact_binding(root, files, item)}
    return _publish(root, files, [item], identity, "Record user acceptance " + item["id"], publish, extra=extra)

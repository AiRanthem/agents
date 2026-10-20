"""Owner assessments retain independent coverage without inventing a new review.

known-limit: a trusted owner judges semantic equivalence; hashes establish exact
inputs, not unchanged meaning. Uncertain or changed contracts/assumptions require
independent incremental review. A future structured contract can narrow this
human/model judgment without weakening the current evidence and identity guards.
"""
import copy

try:
    import project_workflow as workflow
    import project_store as store
except ImportError:
    from . import project_workflow as workflow, project_store as store


def capture(root, files, item, *, reviewed=False, read=None, read_hashes=None):
    """Retain a verified current pass before its inputs or baseline are replaced."""
    state = item.setdefault("workflow", {})
    if state.get("design_basis") and not reviewed:
        return
    review = item.get("design", {}).get("review") or {}
    if review.get("result") != "pass":
        return
    if not reviewed:
        try:
            workflow._approved(files, item)
        except workflow.ProjectError:
            return
    approval = item["design"].get("approval") or {}
    if not approval.get("source") or review.get("session") in workflow._design_authors(item):
        return
    if read is None:
        read = workflow._read_payload(root, files, item, "design-review")
    hashes = dict(read_hashes) if read_hashes is not None else workflow._autonomy_module()._read_hashes(root, files, item, "design-review", read=read)
    hashes.update({row["path"]: workflow._hash(row["content"]) for row in read})
    state["design_basis"] = {"review": copy.deepcopy(review), "approval": copy.deepcopy(approval),
                             "read": read, "read_hashes": hashes}
    state.pop("design_reuse", None)
    state.pop("design_review_failure", None)


def ready(item, identity=None):
    """Require independent coverage and the current control claim."""
    state = item.get("workflow") or {}
    basis = state.get("design_basis") or {}
    review = basis.get("review") or {}
    if (not basis.get("approval", {}).get("source") or not basis.get("read") or
            review.get("result") != "pass" or not review.get("provenance") or
            not review.get("session") or review.get("session") in workflow._design_authors(item) or
            item.get("design", {}).get("review", {}).get("result") == "fail" or
            state.get("design_review_failure")):
        raise workflow.ProjectError("design reuse requires a retained independent pass without unresolved blocking findings")
    if identity and not workflow._ownership_module().authorized(item, identity):
        raise workflow.ProjectError("design reuse requires the current control claim")
    return basis


def target(root, files, item):
    return {"binding": workflow._autonomy_module()._binding(root, files, item, code=False),
            "read_hashes": workflow._autonomy_module()._read_hashes(root, files, item, "design-review"),
            "authorization": copy.deepcopy((item.get("workflow", {}).get("autonomy") or {}).get("authorization"))}


def current(files, item, review, *, missing_root=None):
    """Resolve old immutable review plus a precise current applicability record."""
    state = item.get("workflow") or {}
    basis, reuse = state.get("design_basis") or {}, state.get("design_reuse") or {}
    if (reuse.get("result") != "pass" or review != basis.get("review") or
            reuse.get("basis_review") != review.get("id") or
            reuse.get("basis_sha256") != workflow._hash(workflow._canonical(basis)) or
            not reuse.get("provenance") or not reuse.get("session")):
        return False
    expected = reuse.get("target") or {}
    binding = expected.get("binding") or {}
    autonomy = workflow._autonomy_module()
    actual = autonomy._binding(None, files, item, code=False)
    predevelopment = autonomy._predevelopment()
    convergence = predevelopment.state(item) or {}
    if convergence.get("phase") == "formal" and convergence.get("rebased") is True:
        # The state machine enters formal only after formal code review passes.
        # Its administrative acknowledgement preserves the assessed generation,
        # inputs and rebase plan; every other input remains exactly bound.
        before = {**predevelopment.identity(item), "phase": "reconciling"}
        if binding.get("predevelopment_sha256") == workflow._hash(workflow._canonical(before)):
            actual["predevelopment_sha256"] = binding["predevelopment_sha256"]
    if binding != actual:
        return False
    # Context, inherited instructions and even formerly absent sources remain
    # exact guards. Never rewrite the original independent execution receipt.
    try:
        workflow._autonomy_module()._validate_reads(expected, missing_root=missing_root)
    except workflow.ProjectError:
        return False
    return bool(expected.get("read_hashes"))


def validate(item):
    state = item.get("workflow") or {}
    basis = state.get("design_basis")
    if basis is not None:
        if not isinstance(basis, dict):
            raise workflow.ProjectError("design basis must retain original independent evidence")
        review, approval = basis.get("review") or {}, basis.get("approval") or {}
        if (review.get("kind") != "design-review" or review.get("item") != item["id"] or
                review.get("result") != "pass" or not review.get("session") or not review.get("provenance") or
                not approval.get("source") or not isinstance(basis.get("read_hashes"), dict) or
                not isinstance(basis.get("read"), list) or not basis["read"] or
                any(not isinstance(row, dict) or not isinstance(row.get("path"), str) or
                    not isinstance(row.get("content"), str) or
                    workflow._hash(row["content"]) != basis["read_hashes"].get(row["path"])
                    for row in basis["read"])):
            raise workflow.ProjectError("design basis must retain complete original inputs, approval and independent pass")
    reuse = state.get("design_reuse")
    if reuse is not None and (not isinstance(reuse, dict) or not basis or
            reuse.get("kind") != "design-reuse" or reuse.get("item") != item["id"] or
            reuse.get("result") not in {"pass", "fail"} or not reuse.get("session") or not reuse.get("provenance") or
            reuse.get("basis_review") != basis["review"]["id"] or
            reuse.get("basis_sha256") != workflow._hash(workflow._canonical(basis)) or
            not isinstance(reuse.get("target"), dict) or not reuse["target"].get("read_hashes")):
        raise workflow.ProjectError("design applicability must bind an exact target and original independent basis")
    approval = item.get("design", {}).get("approval") or {}
    if approval.get("kind") in {"derived_reuse", "derived_reuse_pending", "derived_confirmation", "derived_mechanical"}:
        original = approval.get("original_user_approval") or {}
        if (original.get("kind") != "user" or not original.get("source") or
                approval.get("kind") not in {"derived_confirmation", "derived_mechanical"} and (not reuse or
                    reuse.get("result") != ("fail" if approval["kind"] == "derived_reuse_pending" else "pass") or
                    approval.get("assessment") != reuse.get("id"))):
            raise workflow.ProjectError("reused approval must retain its real original user approval and assessment")


def pending(files, item):
    approval = item.get("design", {}).get("approval") or {}
    state = item.get("workflow") or {}
    reuse = state.get("design_reuse") or {}
    basis = state.get("design_basis") or {}
    if approval.get("kind") == "derived_revision":
        return bool(approval.get("original_user_approval", {}).get("kind") == "user" and
                    all(approval.get(key) == value for key, value in workflow._approval_binding(files, item).items()))
    comparison = (approval.get("kind") == "derived_reuse_pending" and approval.get("assessment") == reuse.get("id") or
                  approval.get("kind") == "derived_revision" and state.get("design_review_failure"))
    return bool(comparison and reuse.get("result") == "fail" and
                approval.get("original_user_approval", {}).get("kind") == "user" and
                basis.get("approval", {}).get("source") == approval.get("source") and
                all(approval.get(key) == value for key, value in workflow._approval_binding(files, item).items()))


def needed(root, files, item, session):
    try:
        ready(item, workflow._identity(root, item=item["id"], create=False))
        workflow._approved(files, item)
        return False
    except workflow.ProjectError:
        try:
            ready(item, workflow._identity(root, item=item["id"], create=False))
        except workflow.ProjectError:
            return False
    previous = (item.get("workflow") or {}).get("design_reuse") or {}
    return not (previous.get("result") == "fail" and previous.get("target") == target(root, files, item))


def finish(root, manifest, files, item, writes, report):
    basis = ready(item, manifest["identity"])
    captured = manifest["reuse_target"]
    if captured != target(root, files, item):
        raise workflow.ProjectError("design reuse target changed; begin a fresh assessment")
    record = workflow._report(root, manifest, item, files, writes, "design-reuse", report)
    record.update(result=manifest["options"]["result"], target=captured,
                  basis_review=basis["review"]["id"],
                  basis_sha256=workflow._hash(workflow._canonical(basis)))
    item.setdefault("workflow", {})["design_reuse"] = record
    if record["result"] == "pass":
        design = item["design"]
        original = copy.deepcopy(basis["approval"])
        design["approval"] = {**workflow._approval_binding(files, item), "kind": "derived_reuse",
                              "source": original["source"], "original_user_approval": original.get("original_user_approval", original),
                              "assessment": record["id"], "session": manifest["identity"]["session"]}
        design["review"] = copy.deepcopy(basis["review"])
        design["state"] = "implementable"
        item.pop("needs_review", None)
        autonomy = item["workflow"].get("autonomy") or {}
        authorization = autonomy.get("authorization")
        if authorization:
            # The assessor declares the same authorized contract applicable;
            # retain its real user source and link the exact reassessment.
            authorization.update(requirement_sha256=design["approval"]["requirement_sha256"],
                                 decision_sha256=captured["binding"]["decision_sha256"],
                                 design_reuse=record["id"])
        if (workflow._autonomy_module()._predevelopment().state(item) or {}).get("rebased"):
            item["status"] = "developing"
    else:
        # A failed assessment cannot hide behind the stale pass or a waiver.
        workflow._invalidate_implementation(item)
        approval = item["design"].get("approval") or {}
        if (not approval.get("source") or any(approval.get(key) != value for key, value in
                workflow._approval_binding(files, item).items())):
            original = copy.deepcopy(basis["approval"])
            item["design"]["approval"] = {**workflow._approval_binding(files, item),
                "kind": "derived_reuse_pending", "source": original["source"], "assessment": record["id"],
                "original_user_approval": original.get("original_user_approval", original)}
        item["design"]["state"] = "review-pending" if item["design"].get("approval") else "draft"
        autonomy = item["workflow"].get("autonomy") or {}
    writes["workitems/" + item["id"] + "/records/" + record["id"] + ".yaml"] = store.dump_yaml(record)

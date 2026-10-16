"""Prepare deterministic, guarded business changes without publishing or writing.

Review and delivery attestations record evidence supplied by the caller. They do
not establish the truth, independence, or completeness of external verification.
"""

import copy
from collections import deque
import hashlib
import json
import re

try:
    import project_runtime as runtime
    from project_context import ContextError, _resolve_item
    from workitem_ids import allocate_ids
except ImportError:  # pragma: no cover - package entrypoint
    from . import project_runtime as runtime
    from .project_context import ContextError, _resolve_item
    from .workitem_ids import allocate_ids


ProjectError = runtime.ProjectError
UPDATE_FIELDS = {"title", "kind", "repository", "status", "archived", "depends_on",
                 "delivery", "cleanup", "development"}
REQUEST_FIELDS = {"session", "token", "machine", "message", "operations"}
OPERATION_FIELDS = {
    "create": {"op", "slug", "title", "requirement", "kind", "repository",
               "delivery_required", "depends_on", "parent", "alias"},
    "update": {"op", "item", "set"},
    "archive": {"op", "item", "archived"},
    "document": {"op", "item", "name", "path", "text", "mode", "expected_sha256"},
    "claim": {"op", "item", "machine", "stage", "review"},
    "release": {"op", "item"},
    "deliver": {"op", "item", "evidence", "provenance", "acceptance_coverage"},
}
DESIGN_STATUS = re.compile(r"(?m)^design_status:[ \t]*([^\r\n]*)(\r?)$")


def _text(value):
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    except (ValueError, TypeError) as exc:
        raise ProjectError("operation values must be finite JSON data") from exc


def _hash(value):
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _required_text(value, label):
    if not runtime._nonempty(value):
        raise ProjectError(f"{label} must be a nonempty string")
    return value


def _known_fields(value, allowed, label):
    unknown = set(value) - allowed
    if unknown:
        raise ProjectError(f"{label} has unknown fields: {', '.join(sorted(map(str, unknown)))}")


def _attestation(value, label):
    if not (runtime._nonempty(value) or isinstance(value, dict) and bool(value)):
        raise ProjectError(f"{label} must contain explicit provenance")


def _frontmatter(text):
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None
    for offset, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return lines, offset
    return None


def _design_status(text):
    section = _frontmatter(text)
    if section is None:
        return None
    lines, end = section
    matches = DESIGN_STATUS.findall("".join(lines[1:end]))
    if len(matches) > 1:
        raise ProjectError("spec.md has duplicate design_status fields")
    if not matches:
        return None
    value = matches[0][0].strip()
    if re.fullmatch(r"(?:implementable|'implementable'|\"implementable\")(?:[ \t]+#.*)?", value):
        return "implementable"
    return value.strip("\"'")


def _invalidate(text):
    section = _frontmatter(text)
    if section is None or _design_status(text) != "implementable":
        return text
    lines, end = section
    lines[1:end] = [DESIGN_STATUS.sub(r"design_status: draft\2", line)
                    for line in lines[1:end]]
    return "".join(lines)


class _Preparation:
    def __init__(self, root, request):
        if not isinstance(request, dict):
            raise ProjectError("request must be an object")
        _known_fields(request, REQUEST_FIELDS, "request")
        for key in ("session", "message"):
            _required_text(request.get(key), "request." + key)
        if "token" not in request or (request["token"] is not None and not runtime._nonempty(request["token"])):
            raise ProjectError("request.token must be null or a nonempty string")
        if not isinstance(request.get("operations"), list) or not request["operations"]:
            raise ProjectError("request.operations must be a nonempty list")
        for entry in request["operations"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("op"), str) or entry["op"] not in OPERATION_FIELDS:
                raise ProjectError("unsupported operation; expected create/update/archive/document/claim/release/deliver")
            _known_fields(entry, OPERATION_FIELDS[entry["op"]], "operation " + entry["op"])
        self.root = runtime.find_project(root)
        runtime._check_tracked_paths(self.root)
        self.original = runtime._working_files(self.root)
        errors = runtime._validate_files(self.root, self.original)
        if errors:
            raise ProjectError("invalid project snapshot:\n" + "\n".join(errors))
        self.files = dict(self.original)
        self.request = request
        self.checks = {".project/project.json": _hash(self.original[".project/project.json"])}
        self.items = {}
        for name, content in self.files.items():
            if name.startswith("workitems/") and name.endswith("/item.json"):
                record = runtime._decode_json(content, name)
                self.items[record["id"]] = record
        self.aliases = {}
        self.actions = []
        self.changed_contracts = set()
        self.explicitly_reviewed = set()

    def guard(self, name):
        runtime._managed_path(name)
        runtime._no_links(self.root, name)
        self.checks[name] = _hash(self.original.get(name))

    def resolve(self, selector):
        _required_text(selector, "item selector")
        if selector.startswith("$"):
            if selector[1:] not in self.aliases:
                raise ProjectError(f"unknown batch alias: {selector}")
            identifier = self.aliases[selector[1:]]
        else:
            try:
                identifier = _resolve_item(
                    [{"id": key, "metadata": value} for key, value in self.items.items()], selector)["id"]
            except ContextError as exc:
                raise ProjectError(str(exc)) from exc
        self.guard(f"workitems/{identifier}/item.json")
        return identifier

    def dependencies(self, values):
        if not isinstance(values, list):
            raise ProjectError("depends_on must be a list of item selectors")
        return [self.resolve(value) for value in values]

    def owned(self, identifier):
        owner = self.items[identifier].get("owner")
        if owner is not None and (owner.get("session") != self.request["session"] or
                                  owner.get("token") != self.request["token"]):
            raise ProjectError(f"item {identifier} is owned by another session/token; no takeover is available")

    def put(self, name, text):
        if not isinstance(text, str):
            raise ProjectError(f"document content must be a string: {name}")
        self.guard(name)
        try:
            self.files[name] = text.encode("utf-8")
        except UnicodeError as exc:
            raise ProjectError(f"invalid UTF-8 content: {name}") from exc

    def save_item(self, identifier):
        path = f"workitems/{identifier}/item.json"
        if path in self.files and runtime._decode_json(self.files[path], path) == self.items[identifier]:
            return
        self.put(path, _text(self.items[identifier]))

    def create(self, op):
        _required_text(op.get("title"), "create.title")
        requirement = _required_text(op.get("requirement"), "create.requirement")
        parent = self.resolve(op["parent"]) if op.get("parent") is not None else None
        # Publication validates allocation against the merged remote hierarchy;
        # unrelated metadata updates do not need to invalidate this candidate.
        try:
            identifier = allocate_ids(self.items, [op.get("slug")], parent)[0]
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
        alias = op.get("alias")
        if alias is not None:
            if not runtime._identifier(alias) or alias in self.aliases:
                raise ProjectError("create.alias must be a unique safe identifier")
            self.aliases[alias] = identifier
        self.items[identifier] = {
            "id": identifier, "title": op["title"], "kind": op.get("kind", "development"),
            "status": "new", "archived": False, "depends_on": [], "split_from": parent,
            "repository": op.get("repository"), "owner": None, "development": None,
            "delivery": {"required": op.get("delivery_required", ["merged"]),
                         "status": "pending", "evidence": []}, "cleanup": "not_applicable"}
        self.items[identifier]["depends_on"] = self.dependencies(op.get("depends_on", []))
        self.save_item(identifier)
        self.put(f"workitems/{identifier}/requirement.md", requirement)

    def update(self, op):
        identifier = self.resolve(op.get("item"))
        self.owned(identifier)
        values = op.get("set")
        if not isinstance(values, dict) or not values or set(values) - UPDATE_FIELDS:
            raise ProjectError("update.set must contain only supported mutable fields")
        record = self.items[identifier]
        values = copy.deepcopy(values)
        if "delivery" in values and not isinstance(values["delivery"], dict):
            raise ProjectError("update.delivery must be an object")
        for key in ("delivery", "development"):
            if isinstance(values.get(key), dict) and isinstance(record.get(key), dict):
                values[key] = dict(record[key], **values[key])
        if "depends_on" in values:
            values["depends_on"] = self.dependencies(values["depends_on"])
        status = values.get("status", record["status"])
        if status != record["status"] and status in ("developing", "done"):
            raise ProjectError("enter developing through claim, and done through deliver")
        if record["status"] == "developing" and status not in ("developing", "awaiting_delivery"):
            raise ProjectError("developing must first hand off to awaiting_delivery")
        delivery = values.get("delivery", record["delivery"])
        if record["delivery"]["status"] == "delivered" and (
                status != "done" or delivery.get("status") != "delivered"):
            raise ProjectError("delivered items cannot reopen; create a linked repair through begin fix")
        if isinstance(delivery, dict) and delivery.get("status") == "delivered" and delivery != record["delivery"]:
            raise ProjectError("record delivered evidence through deliver")
        if record["status"] == "done" and status == "done" and any(key in values and values[key] != record[key]
                                                                    for key in {"kind", "repository", "depends_on", "delivery", "development"}):
            raise ProjectError("reopen a done item before changing its delivery contract")
        if status == "awaiting_delivery" and record["status"] == "developing":
            name = f"workitems/{identifier}/handoff.md"
            self.guard(name)
            if not self.files.get(name, b"").strip():
                raise ProjectError("implementation handoff requires nonempty handoff.md")
        contract_changed = (any(key in values and values[key] != record[key]
                                for key in {"kind", "repository", "depends_on", "development"}) or
                            isinstance(delivery, dict) and delivery.get("required") != record["delivery"]["required"])
        if contract_changed and record["delivery"]["status"] == "delivered" and delivery.get("status") != "pending":
            raise ProjectError(f"item {identifier}: reopen and reset delivered status before changing its accepted contract")
        if contract_changed:
            self.changed_contracts.add(identifier)
        if values != {key: record[key] for key in values}:
            record.update(values)
            self.save_item(identifier)

    def archive(self, op):
        self.update({"item": op.get("item"), "set": {"archived": op.get("archived", True)}})

    def document(self, op):
        if "path" in op:
            if "item" in op or "name" in op:
                raise ProjectError("document.path and item/name are mutually exclusive")
            path = op["path"]
            runtime._managed_path(path)
            if not (path.endswith(".md") or path.startswith("evidence/") and path.endswith(".json")):
                raise ProjectError("document.path permits approved Markdown or evidence JSON only")
            identifier = runtime._item_for_path(path)
            if identifier is not None:
                identifier = self.resolve(identifier)
                self.owned(identifier)
                name = path.split("/", 2)[2]
            else:
                name = path
        else:
            identifier = self.resolve(op.get("item"))
            self.owned(identifier)
            name = op.get("name")
            if not isinstance(name, str) or not name.endswith(".md"):
                raise ProjectError("document.name must be an approved item Markdown path")
            path = f"workitems/{identifier}/{name}"
        runtime._managed_path(path)
        self.guard(path)
        mode = op.get("mode", "replace")
        if mode not in ("replace", "append") or not isinstance(op.get("text"), str):
            raise ProjectError("document requires text and mode replace or append")
        current = self.files.get(path)
        if mode == "replace" and current is not None:
            if op.get("expected_sha256") != _hash(current):
                raise ProjectError(f"stale or missing expected_sha256 for {path}")
        elif "expected_sha256" in op and op["expected_sha256"] != _hash(current):
            raise ProjectError(f"stale expected_sha256 for {path}")
        text = (current.decode("utf-8") if mode == "append" and current else "") + op["text"]
        if text.encode("utf-8") != current:
            if identifier is not None and name in {"requirement.md", "spec.md"}:
                if self.items[identifier]["delivery"]["status"] == "delivered":
                    raise ProjectError(f"item {identifier}: reopen and reset delivered status before changing its accepted contract")
                self.changed_contracts.add(identifier)
            self.put(path, text)

    def prerequisites(self, identifier):
        for dependency in self.items[identifier]["depends_on"]:
            self.guard(f"workitems/{dependency}/item.json")
            record = self.items[dependency]
            if record["status"] == "cancelled" or record["delivery"]["status"] != "delivered":
                raise ProjectError(f"item {identifier} requires delivered, non-cancelled prerequisite {dependency}")

    def claim(self, op):
        identifier = self.resolve(op.get("item"))
        self.owned(identifier)
        token = _required_text(self.request["token"], "claim request.token")
        machine = _required_text(op.get("machine", self.request.get("machine")), "claim.machine")
        stage = op.get("stage")
        if stage not in ("preparation", "implementation"):
            raise ProjectError("claim.stage must be preparation or implementation")
        record = self.items[identifier]
        if record["kind"] != "development" or record["status"] in {"done", "cancelled", "awaiting_delivery"}:
            raise ProjectError("claim requires an active development item; resume an awaiting delivery separately")
        if stage == "preparation" and record["status"] == "developing":
            raise ProjectError("cannot replace an implementation claim with preparation")
        if stage == "implementation":
            if identifier in self.changed_contracts:
                raise ProjectError("changed requirement/spec/dependencies require a fresh independent review before implementation")
            self.prerequisites(identifier)
            review = op.get("review")
            if not isinstance(review, dict) or review.get("result") != "pass" or review.get("independent") is not True:
                raise ProjectError("implementation claim requires an explicit independent pass review attestation")
            _attestation(review.get("provenance"), "review.provenance")
            _required_text(review.get("reference"), "review.reference")
            if not runtime._identifier(review.get("id")):
                raise ProjectError("review.id must be a safe identifier")
            for name in ("spec.md", "requirement.md"):
                path = f"workitems/{identifier}/{name}"
                self.guard(path)
                content = self.files.get(path)
                if not content or review.get(name[:-3] + "_sha256") != _hash(content):
                    raise ProjectError(f"review must identify the current full {name} hash")
                if name == "spec.md" and _design_status(content.decode("utf-8")) != "implementable":
                    raise ProjectError("implementation claim requires an implementable current spec.md")
            development = record.get("development")
            if not isinstance(development, dict) or review.get("base_commit") != development.get("base_commit"):
                raise ProjectError("review.base_commit must match actual development metadata")
            path = f"workitems/{identifier}/reviews/{review['id']}.md"
            if path in self.files:
                if self.files[path] != ("# Implementation review attestation\n\n```json\n" + _text(review) + "```\n").encode("utf-8"):
                    raise ProjectError("review.id already identifies different review evidence")
            self.put(path, "# Implementation review attestation\n\n```json\n" + _text(review) + "```\n")
            self.explicitly_reviewed.add(identifier)
        owner = {"machine": machine, "session": self.request["session"], "token": token}
        if record.get("owner") is not None and record["owner"] != owner:
            raise ProjectError("release an existing claim before changing its machine identity")
        record["owner"] = owner
        record["status"] = "developing" if stage == "implementation" else "in_progress"
        self.save_item(identifier)

    def release(self, op):
        identifier = self.resolve(op.get("item"))
        self.owned(identifier)
        record = self.items[identifier]
        if record["owner"] is None:
            return
        if record["status"] == "developing":
            raise ProjectError("developing must first hand off to awaiting_delivery before release")
        receipt_path = f".project/sync/{identifier}.json"
        self.guard(receipt_path)
        if receipt_path in self.files:
            receipt = runtime._decode_json(self.files[receipt_path], receipt_path)
            if receipt["state"] in {"pending", "unknown"}:
                raise ProjectError("reconcile the pending/unknown sync outcome before releasing ownership")
        record["owner"] = None
        self.save_item(identifier)

    def deliver(self, op):
        identifier = self.resolve(op.get("item"))
        self.owned(identifier)
        record = self.items[identifier]
        if record["status"] in {"developing", "cancelled"}:
            raise ProjectError("delivery requires implementation handoff and a non-cancelled item")
        evidence = op.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(
                not isinstance(entry, dict) or not runtime._nonempty(entry.get("kind")) or
                not runtime._nonempty(entry.get("reference")) for entry in evidence):
            raise ProjectError("deliver.evidence must contain explicit kind/reference records")
        _attestation(op.get("provenance"), "deliver.provenance")
        if not set(record["delivery"]["required"]) <= {entry["kind"] for entry in evidence}:
            raise ProjectError("delivery evidence must cover every required kind")
        if record["kind"] == "aggregate":
            self.prerequisites(identifier)
            _required_text(op.get("acceptance_coverage"), "aggregate deliver.acceptance_coverage")
        record["delivery"] = dict(record["delivery"], status="delivered", evidence=copy.deepcopy(evidence),
                                  provenance=copy.deepcopy(op["provenance"]))
        if record["kind"] == "aggregate":
            record["delivery"]["acceptance_coverage"] = op["acceptance_coverage"]
        record["status"] = "done"
        self.save_item(identifier)

    def blocked_by(self, identifier):
        return [dependency for dependency in self.items[identifier]["depends_on"]
                if self.items[dependency]["status"] == "cancelled" or
                self.items[dependency]["delivery"]["status"] != "delivered"]

    def summaries(self, touched):
        summaries, changed, dependency_changed = [], set(), set()
        for identifier in touched:
            record = self.items[identifier]
            summaries.append({"id": identifier, "title": record["title"], "status": record["status"],
                              "archived": record["archived"], "delivery_status": record["delivery"]["status"],
                              "depends_on": list(record["depends_on"]), "blocked_by": self.blocked_by(identifier)})
            path = f"workitems/{identifier}/item.json"
            old = runtime._decode_json(self.original[path], path) if path in self.original else None
            if (old is None and record["depends_on"]) or (old is not None and old["depends_on"] != record["depends_on"]):
                dependency_changed.add(identifier)
            if (old is None or old["delivery"] != record["delivery"] or identifier in dependency_changed or
                    (old["status"] == "cancelled") != (record["status"] == "cancelled")):
                changed.add(identifier)
        affected = dependency_changed | {identifier for identifier, record in self.items.items()
                                         if changed.intersection(record["depends_on"])}
        effects = [{"id": identifier, "title": self.items[identifier]["title"],
                    "dependency_ready": not self.blocked_by(identifier), "blocked_by": self.blocked_by(identifier)}
                   for identifier in sorted(affected)]
        return summaries, effects

    def finish(self):
        affected = set(self.changed_contracts)
        downstream = {}
        for identifier, item in self.items.items():
            for dependency in item["depends_on"]:
                downstream.setdefault(dependency, []).append(identifier)
        pending = deque(sorted(affected))
        while pending:
            for identifier in downstream.get(pending.popleft(), []):
                if identifier not in affected:
                    affected.add(identifier)
                    pending.append(identifier)
        for identifier in sorted(affected - self.changed_contracts):
            self.actions.append({"item": identifier, "action": "assess_dependency_review",
                                 "reason": "an upstream contract changed; assess current dependency assumptions before implementation"})
        if affected.intersection(self.explicitly_reviewed):
            raise ProjectError("implementation claim was invalidated by a contract change in this batch")
        for identifier in sorted(self.changed_contracts):
            path = f"workitems/{identifier}/spec.md"
            self.guard(path)
            if path not in self.files:
                continue
            text = self.files[path].decode("utf-8")
            invalidated = _invalidate(text)
            if invalidated != text:
                self.owned(identifier)
                self.guard(f"workitems/{identifier}/item.json")
                self.put(path, invalidated)
                self.actions.append({"item": identifier, "action": "review_design",
                                     "reason": "requirement, spec, development baseline or dependency contract changed; implementable invalidated"})
        writes = {name: value.decode("utf-8") for name, value in sorted(self.files.items())
                  if value != self.original.get(name)}
        if not writes:
            return {"bundle": None, "changes": [], "items": [], "required_actions": [],
                    "business_digests": {}, "sync_context": {}, "aliases": self.aliases,
                    "files": self.files, "item_summaries": [], "dependency_effects": []}
        touched = sorted({runtime._item_for_path(name) for name in writes} - {None})
        sync_context = {}
        validation_files = dict(self.files)
        for identifier in touched:
            # Guard complete business input for backend projection and digest.
            for name in self.original:
                if name.startswith(f"workitems/{identifier}/"):
                    self.guard(name)
            self.guard(f"workitems/{identifier}/item.json")
            receipt_path = f".project/sync/{identifier}.json"
            self.guard(receipt_path)
            receipt = runtime._decode_json(self.original[receipt_path], receipt_path) if receipt_path in self.original else None
            changed_business = (f"workitems/{identifier}/item.json" not in self.original or
                                runtime._business_digest(self.original, identifier) != runtime._business_digest(self.files, identifier))
            if receipt and receipt["state"] in {"pending", "unknown"} and changed_business:
                raise ProjectError(f"item {identifier} has unresolved {receipt['state']} sync intent; reconcile before business update")
            sync_context[identifier] = {"receipt": receipt, "business_changed": changed_business}
            if receipt and receipt["state"] == "verified" and changed_business:
                # The persistence coordinator replaces this receipt with a pending
                # intent before publishing. The business layer never changes it.
                validation_files.pop(receipt_path)
        errors = runtime._validate_files(self.root, validation_files)
        if errors:
            raise ProjectError("invalid proposed project:\n" + "\n".join(errors))
        bundle = {"checks": dict(sorted(self.checks.items())), "writes": writes,
                  "session": self.request["session"], "token": self.request["token"],
                  "message": self.request["message"]}
        runtime._validate_bundle(bundle)
        runtime._check_owners(bundle, self.original, self.files)
        changes = [{"item": runtime._item_for_path(name), "path": name,
                    "before_sha256": _hash(self.original.get(name)),
                    "after_sha256": _hash(self.files[name])} for name in writes]
        item_summaries, dependency_effects = self.summaries(touched)
        return {"bundle": bundle, "changes": changes, "items": touched,
                "required_actions": self.actions, "aliases": self.aliases,
                "business_digests": {identifier: runtime._business_digest(self.files, identifier) for identifier in touched},
                "sync_context": sync_context, "files": self.files,
                "item_summaries": item_summaries, "dependency_effects": dependency_effects}


def prepare(root, request):
    """Validate a whole operation batch and return a guarded publication bundle.

    The result describes a local snapshot, not remote publication or externally
    verified review/delivery. With Aone enabled, the persistence coordinator must
    retain ownership and prepare pending intents before passing the bundle to Git.
    Dependency readiness describes prerequisite delivery only; review, ownership
    and implementation approval remain separate gates.
    """
    operation = _Preparation(root, copy.deepcopy(request))
    for entry in operation.request["operations"]:
        getattr(operation, entry["op"])(entry)
    return operation.finish()

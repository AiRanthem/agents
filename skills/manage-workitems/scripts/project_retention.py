"""Keep current machine-referenced credentials; Git owns superseded records."""

from pathlib import PurePosixPath
import re

try:
    import project_store as store
except ImportError:
    from . import project_store as store


_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _component(value, label):
    if not isinstance(value, str) or not _COMPONENT.fullmatch(value):
        raise store.StoreError(label + " must be a safe path component")
    return value


def _root_paths(identifier, root, kind):
    inline = root if isinstance(root, dict) else None
    if kind in {"design-review", "design-reuse", "development-finish", "validation-waiver", "user_design_review_waiver", "predevelopment-snapshot"}:
        if inline is None or inline.get("item") != identifier or inline.get("kind") != kind:
            raise store.StoreError("current " + kind + " root must be a same-item inline record")
    elif not isinstance(root, str):
        raise store.StoreError("current " + kind + " root must be a record id")
    record_id = _component(inline.get("id") if inline is not None else root, "record id")
    base = "workitems/" + identifier + "/records/" + record_id
    metadata, report = base + ".yaml", base + ".md"
    if inline is not None and (kind in {"design-review", "design-reuse", "development-finish"} or "report" in inline):
        if inline.get("report") != report:
            raise store.StoreError("current credential root report must reference its same-id pair: " + metadata)
    return metadata, report


def _record_paths(files, identifier, root, kind):
    metadata, report = _root_paths(identifier, root, kind)
    if metadata not in files or report not in files:
        raise store.StoreError("current credential requires its record pair: " + metadata)
    record = store.load_yaml(files[metadata], metadata)
    if (not isinstance(record, dict) or record.get("id") != PurePosixPath(metadata).stem or
            record.get("item") != identifier or record.get("kind") != kind):
        raise store.StoreError("current credential has inconsistent id/item/kind: " + metadata)
    if kind in {"design-review", "design-reuse", "development-finish", "delivery-record"}:
        if record.get("report") != report:
            raise store.StoreError("current credential report must reference its same-id pair: " + metadata)
    elif "report" in record and record["report"] != report:
        raise store.StoreError("current credential report escapes its same-id pair: " + metadata)
    if isinstance(root, dict):
        keys = {"id", "item", "kind"} | ({"report"} if "report" in record else set())
        if any(root.get(key) != record.get(key) for key in keys):
            raise store.StoreError("current credential root differs from its record: " + metadata)
    return {metadata, report}


def _current_roots(files, identifier):
    _component(identifier, "work item id")
    item = store.item(files, identifier)
    if item.get("id") != identifier:
        raise store.StoreError("work item id differs from its storage path: " + identifier)
    sections = {}
    for key in ("design", "development", "delivery", "workflow"):
        value = item.get(key)
        if value is not None and not isinstance(value, dict):
            raise store.StoreError("current " + key + " must be an object")
        sections[key] = value or {}
    roots = (sections["design"].get("review"), sections["development"].get("review"),
             sections["delivery"].get("record"), sections["workflow"].get("design_waiver"),
             sections["workflow"].get("cleanup_record"), sections["workflow"].get("development_discard_record"))
    kinds = ("design-review", "development-finish", "delivery-record", "user_design_review_waiver", "cleanup", "cleanup")
    current = [(root, kind) for root, kind in zip(roots, kinds) if root is not None]
    current.extend((root, "validation-waiver") for root in
                   (sections["workflow"].get("validation_waivers") or {}).values())
    if sections["workflow"].get("design_review_failure") is not None:
        current.append((sections["workflow"]["design_review_failure"], "design-review"))
    basis = sections["workflow"].get("design_basis") or {}
    if basis.get("review") is not None:
        current.append((basis["review"], "design-review"))
    if sections["workflow"].get("design_reuse") is not None:
        current.append((sections["workflow"]["design_reuse"], "design-reuse"))
    for captured in (sections["workflow"].get("autonomy") or {}).get("snapshots", {}).values():
        lifecycle = sections["workflow"].get("lifecycle") or {}
        if lifecycle.get("policy"):
            # Keep exact evidence until physical retirement finishes. Tombstones
            # remain in state/Git history, without pinning every report forever.
            resources = [row for row in lifecycle.get("resources", {}).values()
                         if row.get("snapshot") == captured["id"]]
            if resources and all(row.get("state") == "deleted" for row in resources):
                continue
        current.append((captured, "predevelopment-snapshot"))
    return current


def record_metadata_paths(files, identifier):
    """Resolve exact YAML roots before loading their record pairs from disk."""
    return {_root_paths(identifier, root, kind)[0] for root, kind in _current_roots(files, identifier)}


def live_record_paths(files, identifier):
    """Return current same-item credential pairs, rejecting malformed roots."""
    live = set()
    for root, kind in _current_roots(files, identifier):
        live.update(_record_paths(files, identifier, root, kind))
    return live


def prune_records(files, identifiers=None):
    """Return scoped deletions for unreferenced records and legacy review prose."""
    identifiers = store.items(files) if identifiers is None else identifiers
    deletes = {}
    for identifier in identifiers:
        live = live_record_paths(files, identifier)
        prefix = "workitems/" + identifier + "/"
        for name in files:
            if not name.startswith((prefix + "records/", prefix + "reviews/")):
                continue
            path = PurePosixPath(name)
            if str(path) != name or any(not _COMPONENT.fullmatch(part) for part in path.parts):
                raise store.StoreError("record path must be normalized and safe: " + name)
            if path.suffix not in ({".md", ".yaml"} if path.parts[2] == "records" else {".md"}):
                raise store.StoreError("unsupported retained record path: " + name)
            if name not in live:
                deletes[name] = None
    return deletes

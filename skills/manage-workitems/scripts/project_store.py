"""Physical project storage: strict YAML v2 and explicitly retained JSON v1 reads.

The expanded records are shared with the established validation/backend consumers.
Markdown is prose only; this module never reads or writes machine state in it.
"""

import copy
import json
import math
import re

import yaml


class StoreError(ValueError):
    pass


class _Loader(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise StoreError("YAML mapping keys must be strings")
        if key in result:
            raise StoreError("duplicate YAML key: " + key)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _data(value, active=None):
    active = set() if active is None else active
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) not in (dict, list):
        raise StoreError("unsupported YAML value type: " + type(value).__name__)
    if id(value) in active:
        raise StoreError("recursive YAML aliases are forbidden")
    active.add(id(value))
    for entry in (value.values() if isinstance(value, dict) else value):
        _data(entry, active)
    if isinstance(value, dict) and any(type(key) is not str for key in value):
        raise StoreError("YAML mapping keys must be strings")
    active.remove(id(value))


def load_yaml(data, name="YAML"):
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        value = yaml.load(data, Loader=_Loader)
        _data(value)
        return value
    except (UnicodeError, yaml.YAMLError, StoreError) as exc:
        raise StoreError(f"{name}: invalid UTF-8 YAML: {exc}") from exc


def dump_yaml(record):
    _data(record)
    return yaml.safe_dump(record, allow_unicode=True, sort_keys=False, default_flow_style=False)


def _json(data, name):
    def pairs(entries):
        value = {}
        for key, item in entries:
            if key in value:
                raise StoreError("duplicate JSON key: " + key)
            value[key] = item
        return value
    try:
        value = json.loads(data, object_pairs_hook=pairs,
                           parse_constant=lambda value: (_ for _ in ()).throw(StoreError(value)))
        _data(value)
        return value
    except (ValueError, UnicodeError) as exc:
        raise StoreError(f"{name}: invalid JSON: {exc}") from exc


def is_v2(files):
    return ".project/project.yaml" in files


def project_path(files):
    return ".project/project.yaml" if is_v2(files) else ".project/project.json"


def item_path(files, identifier):
    return f"workitems/{identifier}/" + ("metadata.yaml" if is_v2(files) else "item.json")


def receipt_path(files, identifier):
    return f".project/sync/{identifier}." + ("yaml" if is_v2(files) else "json")


def _object(files, name):
    if name not in files:
        raise StoreError("missing metadata: " + name)
    value = load_yaml(files[name], name) if name.endswith(".yaml") else _json(files[name], name)
    if not isinstance(value, dict):
        raise StoreError(name + " must be an object")
    return copy.deepcopy(value)


def _authority(files):
    v2 = is_v2(files)
    if v2 and ".project/project.json" in files:
        raise StoreError("mixed project authority: project.json and project.yaml")
    for name in files:
        if name.startswith("evidence/") and name.endswith(".yaml") and name[:-5] + ".json" in files:
            raise StoreError("mixed evidence authority: " + name)
        if re.fullmatch(r"workitems/[^/]+/(item.json|metadata.yaml)", name):
            if (name.endswith("item.json") and v2 or name.endswith("metadata.yaml") and not v2):
                raise StoreError("mixed item authority: " + name)
        if name.startswith(".project/state/") and not v2:
            raise StoreError("v2 state requires project.yaml")
        if re.fullmatch(r".project/sync/[^/]+\.(json|yaml)", name):
            if name.endswith(".json") == v2:
                raise StoreError("mixed receipt authority: " + name)


def project(files):
    _authority(files)
    return _object(files, project_path(files))


def item(files, identifier):
    _authority(files)
    record = _object(files, item_path(files, identifier))
    if not is_v2(files):
        return record
    state_name = f".project/state/{identifier}.yaml"
    state = _object(files, state_name) if state_name in files else {}
    forbidden = set(state) - {"owner", "development", "delivery", "workflow", "design"}
    if forbidden:
        raise StoreError(state_name + ": unsupported state fields: " + ", ".join(sorted(forbidden)))
    if any(key in record for key in ("owner", "development", "workflow", "blockers")):
        raise StoreError("metadata contains operational state or derived blockers: " + item_path(files, identifier))
    if not isinstance(record.get("delivery", {}), dict) or not isinstance(state.get("delivery", {}), dict):
        raise StoreError("delivery must be an object")
    if set(record.get("delivery", {})) - {"required", "status"}:
        raise StoreError("delivery evidence/provenance belongs in .project/state")
    if set(state.get("delivery", {})) & {"required", "status"}:
        raise StoreError("delivery required/status belongs in metadata.yaml")
    for key, default in {"archived": False, "depends_on": [], "split_from": None,
                         "repository": None, "cleanup": "not_applicable"}.items():
        record.setdefault(key, copy.deepcopy(default))
    record["owner"] = state.get("owner")
    record["development"] = state.get("development")
    if "workflow" in state:
        record["workflow"] = state["workflow"]
    if "design" in state:
        if not isinstance(state["design"], dict) or set(state["design"]) - {"approval", "review"}:
            raise StoreError(state_name + ": design state only supports approval/review credentials")
        if not isinstance(record.get("design", {}), dict) or set(state["design"]) & set(record.get("design", {})):
            raise StoreError("duplicate design authority: " + state_name)
        record["design"] = dict(record.get("design", {}), **state["design"])
    record["delivery"] = dict(record.get("delivery", {}), **state.get("delivery", {}))
    record["delivery"].setdefault("status", "pending")
    record["delivery"].setdefault("evidence", [])
    record.setdefault("documents", {"requirement": "requirement.md"})
    record.setdefault("design", {"file": "spec.md", "version": 0, "state": "draft"})
    return record


def items(files):
    suffix = "metadata.yaml" if is_v2(files) else "item.json"
    _authority(files)
    return {name.split("/")[1]: item(files, name.split("/")[1]) for name in sorted(files)
            if re.fullmatch(r"workitems/[^/]+/" + re.escape(suffix), name)}


def receipt(files, identifier):
    _authority(files)
    name = receipt_path(files, identifier)
    return _object(files, name) if name in files else None


def _write(files, name, record):
    return {name: dump_yaml(record) if name.endswith(".yaml") else
            json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"}


def write_project(files, record):
    return _write(files, project_path(files), record)


def write_item(files, record):
    record = copy.deepcopy(record)
    identifier = record["id"]
    if not is_v2(files):
        return _write(files, item_path(files, identifier), record)
    state = {key: record.pop(key) for key in ("owner", "development", "workflow") if key in record}
    if isinstance(record.get("design"), dict):
        credentials = {key: record["design"].pop(key) for key in ("approval", "review") if key in record["design"]}
        if credentials:
            state["design"] = credentials
    delivery = record.get("delivery", {})
    operational = {key: delivery.pop(key) for key in list(delivery) if key not in {"required", "status"}}
    if operational:
        state["delivery"] = operational
    for key in list(state):
        if state[key] is None:
            del state[key]
    if state.get("delivery") == {"evidence": []}:
        del state["delivery"]
    for key, default in {"archived": False, "depends_on": [], "split_from": None,
                         "repository": None, "cleanup": "not_applicable"}.items():
        if record.get(key) == default:
            record.pop(key, None)
    record.setdefault("documents", {"requirement": "requirement.md"})
    record.setdefault("design", {"file": "spec.md", "version": 0, "state": "draft"})
    if "blockers" in record:
        raise StoreError("blockers are derived workflow output, not stored metadata")
    writes = _write(files, item_path(files, identifier), record)
    writes.update(_write(files, f".project/state/{identifier}.yaml", state))
    return writes


def write_receipt(files, identifier, record):
    return _write(files, receipt_path(files, identifier), record)


def apply_writes(files, writes):
    result = dict(files)
    for name, value in writes.items():
        if value is None:
            result.pop(name, None)
        else:
            result[name] = value.encode("utf-8") if isinstance(value, str) else value
    return result


def as_legacy(files):
    """Produce an in-memory v1 view for established consumers; never persist it."""
    _authority(files)
    if not is_v2(files):
        return dict(files)
    result = {name: data for name, data in files.items()
              if not name.endswith(".yaml") or not (name.startswith((".project/state/", ".project/sync/", "evidence/"))
                 or name == ".project/project.yaml" or name.endswith("/metadata.yaml"))}
    record = project(files)
    record["schema_version"] = 1
    result[".project/project.json"] = _write({}, ".project/project.json", record)[".project/project.json"].encode()
    for identifier, record in items(files).items():
        name = f"workitems/{identifier}/item.json"
        result[name] = _write({}, name, record)[name].encode()
    for name, data in files.items():
        if name.endswith(".yaml") and name.startswith((".project/sync/", "evidence/")):
            result[name[:-5] + ".json"] = (json.dumps(load_yaml(data, name), ensure_ascii=False, allow_nan=False) + "\n").encode()
    return result

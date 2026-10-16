"""Replace or explicitly retire current knowledge cards through guarded publication."""

import copy
import hashlib
from pathlib import Path
import re
import shlex
import sys
import uuid

try:
    import project_context as context
    import project_runtime as runtime
    import project_store as store
    import project_workflow as workflow
except ImportError:
    from . import project_context as context, project_runtime as runtime, project_store as store, project_workflow as workflow


FIELDS = ("repository", "topic", "summary", "scope", "kind")
KINDS = ("fact", "inference", "search", "verification")


def _hash(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def _paths(identifier):
    if not isinstance(identifier, str) or not context.IDENTIFIER.fullmatch(identifier):
        raise runtime.ProjectError("knowledge id must be a safe path component")
    return f"evidence/{identifier}.yaml", f"evidence/{identifier}.md"


def _snapshot(root, identifier):
    metadata, body = _paths(identifier)
    files = runtime._working_files(root, paths=(".project/project.yaml", ".project/project.json",
                                              metadata, body, f"evidence/{identifier}.json"))
    if not store.is_v2(files):
        raise runtime.ProjectError("knowledge commands require migration to schema version 2")
    context._validate_project_record(store.project(files), Path(store.project_path(files)))
    if f"evidence/{identifier}.json" in files:
        raise runtime.ProjectError("legacy knowledge metadata requires migration before editing")
    if (metadata in files) != (body in files):
        raise runtime.ProjectError("knowledge requires its same-id YAML and Markdown pair")
    record = store.load_yaml(files[metadata], metadata) if metadata in files else None
    if record is not None:
        _validate(root, files, identifier, record)
    return files, record


def _validate(root, files, identifier, record):
    metadata, _ = _paths(identifier)
    if not isinstance(record, dict) or record.get("id") != identifier:
        raise runtime.ProjectError("knowledge id must match its metadata filename")
    repositories = {entry["id"] for entry in store.project(files)["repositories"]}
    context._validate_evidence_metadata(root, record, metadata, repositories)


def show(root, identifier):
    root = runtime.find_project(root)
    files, record = _snapshot(root, identifier)
    metadata, body = _paths(identifier)
    body_file = root / ".project-local" / "knowledge" / (identifier + "-" + uuid.uuid4().hex + ".md")
    runtime._no_links(root, body_file.relative_to(root).as_posix())
    guards = ["--expect-metadata-sha256", _hash(files.get(metadata)) or "absent",
              "--expect-body-sha256", _hash(files.get(body)) or "absent"]
    command = [sys.executable, str(Path(__file__).with_name("project.py").resolve()), "--root", str(root)]
    return {"id": identifier, "exists": record is not None, "metadata": record,
            "body": {"path": body, "sha256": _hash(files.get(body)),
                     "text": files[body].decode("utf-8") if body in files else None},
            "metadata_sha256": _hash(files.get(metadata)), "body_file": str(body_file),
            "update_command": shlex.join(command + ["knowledge-update", identifier, "--body-file", str(body_file)] + guards),
            "remove_command": shlex.join(command + ["knowledge-remove", identifier] + guards) if record is not None else None,
            "create_required_flags": ["--" + name for name in FIELDS] if record is None else [],
            "instruction": "Write the complete current Markdown to body_file, then run update_command. For a new card, add create_required_flags with their actual values.",
            "applicability": "Markdown meaning is not evaluated. Recheck scope and sources before reuse; explicitly replace or remove obsolete knowledge."}


def _guard(files, identifier, expected_metadata, expected_body):
    checks = {}
    for name, expected in zip(_paths(identifier), (expected_metadata, expected_body)):
        if expected == "absent":
            expected = None
        elif not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise runtime.ProjectError("knowledge guard must be the SHA256 or absent returned by knowledge-show")
        if _hash(files.get(name)) != expected:
            raise runtime.ProjectError("byte check conflict: " + name)
        checks[name] = expected
    return checks


def _inputs(values, flag="--input"):
    result = {}
    for entry in values:
        key, separator, value = entry.partition("=")
        if not separator or not key.strip() or key in result:
            raise runtime.ProjectError(flag + " requires unique KEY=VALUE entries")
        result[key] = value
    return result


def update(root, identifier, *, body_file, expected_metadata, expected_body, options=None, publish=None):
    root = runtime.find_project(root)
    runtime.refresh_project(root)
    files, old = _snapshot(root, identifier)
    checks = _guard(files, identifier, expected_metadata, expected_body)
    options = options or {}
    metadata, body = _paths(identifier)
    record = copy.deepcopy(old) if old is not None else {"id": identifier, "body": body, "inputs": {}, "sources": []}
    for key in FIELDS:
        if options.get(key) is not None:
            record[key] = options[key]
        elif old is None:
            raise runtime.ProjectError("new knowledge requires --" + key)
    if options.get("inputs") is not None:
        record["inputs"] = _inputs(options["inputs"])
    if options.get("clear_inputs"):
        record["inputs"] = {}
    if options.get("sources") is not None:
        if any(not isinstance(value, str) or not value.strip() for value in options["sources"]):
            raise runtime.ProjectError("--source requires a nonempty path")
        record["sources"] = [{"path": value} for value in options["sources"]]
    if options.get("clear_sources"):
        record["sources"] = []
    for key in ("revision", "sha256"):
        flag = "--source-" + key
        for path, value in _inputs(options.get("source_" + key) or [], flag).items():
            matches = [source for source in record["sources"] if source.get("path") == path]
            if len(matches) != 1:
                raise runtime.ProjectError(flag + " path must identify exactly one current or --source entry: " + path)
            if not value.strip() or key == "sha256" and not re.fullmatch(r"[0-9a-f]{64}", value):
                raise runtime.ProjectError(flag + " requires a nonempty revision or a SHA256 digest")
            matches[0][key] = value
    source = Path(body_file).absolute()
    if source.suffix != ".md":
        raise runtime.ProjectError("knowledge body input must be a Markdown file")
    # The input may live in a temporary directory, but no symlink component or
    # non-regular input can provide bytes for a guarded knowledge replacement.
    content = context._read_bytes(Path(source.anchor), source).decode("utf-8")
    # Validation checks only machine metadata and pair paths, not body meaning.
    repositories = {entry["id"] for entry in store.project(files)["repositories"]}
    for key in ("topic", "summary", "scope"):
        if not runtime._nonempty(record.get(key)):
            raise runtime.ProjectError("knowledge " + key + " must be nonempty")
    if record.get("repository") not in repositories or record.get("kind") not in KINDS:
        raise runtime.ProjectError("knowledge requires a configured repository and valid kind")
    checks[store.project_path(files)] = _hash(files[store.project_path(files)])
    return workflow._publish(root, {metadata: store.dump_yaml(record), body: content}, workflow._identity(root),
                             "Replace current knowledge " + identifier, checks, publish)


def remove(root, identifier, *, expected_metadata, expected_body, publish=None):
    root = runtime.find_project(root)
    runtime.refresh_project(root)
    files, record = _snapshot(root, identifier)
    checks = _guard(files, identifier, expected_metadata, expected_body)
    if record is None:
        raise runtime.ProjectError("cannot remove missing knowledge")
    checks[store.project_path(files)] = _hash(files[store.project_path(files)])
    return workflow._publish(root, dict.fromkeys(_paths(identifier)), workflow._identity(root),
                             "Retire current knowledge " + identifier, checks, publish)

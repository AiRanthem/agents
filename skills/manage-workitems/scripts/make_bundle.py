#!/usr/bin/env python3
"""Assemble guarded publication writes against one immutable Git snapshot.

--base REV defaults to HEAD; fetch the selected remote revision before invoking
this helper when needed. --write/--new read intended UTF-8 content from disk.
--intent ITEM:EXTERNAL:STATUS:STATUS_ID records the prospective business digest.
--receipt ITEM:READBACK_JSON_PATH verifies a committed pending intent against
explicit readback evidence, without accepting newer business content. The
agent-driven backend adapter must compare all owned fields before providing the
readback JSON. This helper performs no Git writes or backend calls; publication
remains project_runtime.py publish's responsibility.
"""

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import project_runtime as runtime


def _git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise runtime.ProjectError(f"git {args[0]} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def _commit(root, revision):
    return _git(root, "rev-parse", "--verify", "--end-of-options",
                revision + "^{commit}").decode("ascii").strip()


class Snapshot:
    """Read only requested management paths, caching bytes at a resolved commit."""

    def __init__(self, root, commit):
        self.root, self.commit = root, commit
        self.files, self.loaded, self.digests = {}, set(), {}

    def _load(self, path):
        if path in self.loaded:
            return
        entries = _git(self.root, "ls-tree", "-r", "-z", self.commit, "--", path)
        for entry in entries.split(b"\x00"):
            if not entry:
                continue
            metadata, raw_name = entry.split(b"\t", 1)
            mode, kind, object_id = metadata.decode("ascii").split()
            name = raw_name.decode("utf-8")
            runtime._managed_path(name)
            if mode not in {"100644", "100755"} or kind != "blob":
                raise runtime.ProjectError(f"tracked symlinks or nested repositories are forbidden: {name}")
            if name not in self.files:
                self.files[name] = _git(self.root, "cat-file", "blob", object_id)
            self.loaded.add(name)
        self.loaded.add(path)

    def get(self, name):
        self._load(name)
        return self.files.get(name)

    def item_files(self, item_id):
        prefix = f"workitems/{item_id}/"
        self._load(prefix)
        return {name: data for name, data in self.files.items() if name.startswith(prefix)}

    def digest(self, item_id, overlay=None):
        prefix = f"workitems/{item_id}/"
        changed = {name: content.encode("utf-8") for name, content in (overlay or {}).items()
                   if name.startswith(prefix)}
        if not changed and item_id in self.digests:
            return self.digests[item_id]
        files = self.item_files(item_id)
        files.update(changed)
        digest = runtime._business_digest(files, item_id)
        if not changed:
            self.digests[item_id] = digest
        return digest


def _json_object(data, name):
    value = json.loads(data)
    if not isinstance(value, dict):
        raise runtime.ProjectError(f"{name} must be a JSON object")
    return value


def _sync_path(item_id):
    if not runtime._identifier(item_id):
        raise runtime.ProjectError(f"invalid workitem id: {item_id!r}")
    return f".project/sync/{item_id}.json"


def _existing_sync(snapshot, sync):
    content = snapshot.get(sync)
    if content is None:
        raise runtime.ProjectError(f"{sync} must exist at --base")
    return _json_object(content, sync)


def _readback(path):
    data = _json_object(Path(path).read_text(encoding="utf-8"), path)
    for key in ("intent_id", "external_id", "git_source_commit", "checked_at"):
        if not runtime._nonempty(data.get(key)):
            raise runtime.ProjectError(f"readback requires nonempty {key}")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", data["git_source_commit"]):
        raise runtime.ProjectError("readback git_source_commit must be a full commit object ID")
    if not isinstance(data.get("content_sha256"), str) or not runtime.HASH.fullmatch(data["content_sha256"]):
        raise runtime.ProjectError("readback requires a lowercase content_sha256 digest")
    if not isinstance(data.get("baseline_fields"), dict) or not data["baseline_fields"]:
        raise runtime.ProjectError("readback requires nonempty baseline_fields verified from all owned fields")
    try:
        timestamp = data["checked_at"]
        checked = datetime.datetime.fromisoformat(timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp)
    except ValueError as exc:
        raise runtime.ProjectError("readback checked_at must be an ISO timestamp with timezone") from exc
    if checked.tzinfo is None or checked.utcoffset() is None:
        raise runtime.ProjectError("readback checked_at must include a timezone")
    return data


def _receipt(snapshot, snapshots, item_id, readback, writes, args):
    sync = _sync_path(item_id)
    pending = _existing_sync(snapshot, sync)
    if pending.get("state") != "pending":
        raise runtime.ProjectError(f"{sync} at --base must be pending before receipt verification")
    source_commit = _commit(snapshot.root, readback["git_source_commit"])
    _git(snapshot.root, "merge-base", "--is-ancestor", source_commit, snapshot.commit)
    if source_commit not in snapshots:
        snapshots[source_commit] = Snapshot(snapshot.root, source_commit)
    source = snapshots[source_commit]
    source_pending = _existing_sync(source, sync)
    for key in ("intent_id", "external_id", "content_sha256"):
        if not runtime._nonempty(pending.get(key)) or readback[key] != pending[key]:
            raise runtime.ProjectError(f"readback {key} does not match pending intent")
    for key in ("state", "intent_id", "external_id", "content_sha256", "target_status", "target_status_id"):
        if source_pending.get(key) != pending.get(key):
            raise runtime.ProjectError(f"source revision pending {key} does not match --base intent")
    if pending.get("target_status_id") is not None and readback["baseline_fields"].get("status") != pending["target_status_id"]:
        raise runtime.ProjectError("readback baseline_fields.status does not match target_status_id")
    expected = pending["content_sha256"]
    for label, actual in (("source", source.digest(item_id)),
                          ("base", snapshot.digest(item_id)),
                          ("prospective", snapshot.digest(item_id, writes))):
        if actual != expected:
            raise runtime.ProjectError(f"{label} business digest does not match pending intent; synchronize that version first")
    if (pending.get("space_id") is not None and readback.get("space_id") is not None
            and pending["space_id"] != readback["space_id"]):
        raise runtime.ProjectError("readback space_id does not match pending intent")
    receipt = dict(pending)
    receipt.update(state="verified", operation="readback-verify", session=args.session,
                   baseline_fields=readback["baseline_fields"], git_source_commit=source_commit,
                   checked_at=readback["checked_at"], result="readback-verified")
    if "space_id" in readback:
        receipt["space_id"] = readback["space_id"]
    if args.assert_note is not None:
        receipt["readback_assertions"] = args.assert_note
    return sync, receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--base", default="HEAD", help="committed guard/digest revision; resolved once (default: HEAD)")
    parser.add_argument("--session", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--write", action="append", default=[], help="content from a working-tree path")
    parser.add_argument("--new", action="append", default=[], help="working-tree path absent at --base")
    parser.add_argument("--intent", action="append", default=[], metavar="ITEM:EXTERNAL:STATUS:STATUS_ID")
    parser.add_argument("--receipt", action="append", default=[], metavar="ITEM:READBACK_JSON_PATH")
    parser.add_argument("--assert-note", help="optional supplementary readback_assertions text")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        snapshot = Snapshot(root, _commit(root, args.base))
        snapshots = {snapshot.commit: snapshot}
        checks, writes = {}, {}

        def add_write(name, text):
            runtime._managed_path(name)
            runtime._no_links(root, name)
            if name in writes:
                raise runtime.ProjectError(f"duplicate write: {name}")
            old = snapshot.get(name)
            checks[name] = hashlib.sha256(old).hexdigest() if old is not None else None
            writes[name] = text

        for name in args.write + args.new:
            runtime._managed_path(name)
            runtime._no_links(root, name)
            if name in args.new and snapshot.get(name) is not None:
                raise runtime.ProjectError(f"{name} exists at --base; use --write")
            add_write(name, (root / name).read_text(encoding="utf-8"))

        for spec in args.intent:
            item_id, external, status, status_id = spec.split(":", 3)
            sync = _sync_path(item_id)
            prior = _existing_sync(snapshot, sync)
            if not all(runtime._nonempty(value) for value in (external, status, status_id)):
                raise runtime.ProjectError("intent external/status/status-id must be nonempty")
            intent = {
                "intent_id": f"aone-update-{item_id}-{uuid.uuid4().hex}",
                "content_sha256": snapshot.digest(item_id, writes),
                "state": "pending", "operation": "update", "external_id": external,
                "target_status": status, "target_status_id": status_id,
                "session": args.session, "backend": "aone",
                "baseline_fields": prior.get("baseline_fields"),
                "git_source_commit": None, "checked_at": None,
            }
            if "space_id" in prior:
                intent["space_id"] = prior["space_id"]
            add_write(sync, json.dumps(intent, ensure_ascii=False, indent=2) + "\n")

        for spec in args.receipt:
            item_id, readback_path = spec.split(":", 1)
            sync, receipt = _receipt(snapshot, snapshots, item_id, _readback(readback_path), writes, args)
            add_write(sync, json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")

        for name in writes:
            item_id = runtime._item_for_path(name)
            if item_id is None:
                continue
            item_path = f"workitems/{item_id}/item.json"
            if item_path not in checks:
                old = snapshot.get(item_path)
                if old is None:
                    raise runtime.ProjectError(f"missing {item_path}")
                checks[item_path] = hashlib.sha256(old).hexdigest()

        bundle = {"checks": checks, "writes": writes, "message": args.message,
                  "session": args.session, "token": args.token}
        runtime._validate_bundle(bundle)
        Path(args.out).write_text(json.dumps(bundle, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    except (runtime.ProjectError, OSError, ValueError, UnicodeError) as exc:
        raise SystemExit(f"make_bundle: {exc}") from exc
    print(f"make_bundle: {len(writes)} writes, {len(checks)} checks -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Bounded a1 0.2.46 adapter; publication and write-ahead journaling belong to callers.

prepare_sync is read-only. Persist its result as receipt.operation with state unknown
before execute. No method publishes Git or retries an uncertain create.
"""

import copy
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import tempfile

try:
    from project_runtime import ProjectError, STATUSES, _business_digest, _decode_json
except ImportError:  # package entrypoint
    from .project_runtime import ProjectError, STATUSES, _business_digest, _decode_json


ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
BEGIN = "<!-- project-aone-managed:v1 "
END = "<!-- /project-aone-managed:v1 -->"


class AoneError(ProjectError):
    """A backend operation stopped; its durable intent must remain recoverable."""


def _string(value, label):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise AoneError(f"{label} must be a nonempty string")
    return value


def _differences(actual, expected):
    result = []
    for key in sorted(set(actual) | set(expected)):
        if actual.get(key) == expected.get(key):
            continue
        if isinstance(actual.get(key), dict) and isinstance(expected.get(key), dict):
            result.extend(key + "." + child for child in _differences(actual[key], expected[key]))
        else:
            result.append(key)
    return result


class AoneAdapter:
    def __init__(self, project, runner=None):
        self.project = copy.deepcopy(project)
        self.config = self.project.get("backends", {}).get("aone")
        self.runner = runner or subprocess.run
        self.identity = None

    def _run(self, *arguments, json_output=False):
        argv = ["a1", "--no-update-check", *arguments]
        if json_output:
            argv += ["--format", "json"]
        try:
            result = self.runner(argv, capture_output=True, text=True, timeout=45, check=False)
        except FileNotFoundError as exc:
            raise AoneError("Aone backend requires installed a1 CLI") from exc
        except subprocess.TimeoutExpired as exc:
            raise AoneError("a1 timed out; retain the unknown operation for reconciliation") from exc
        except OSError as exc:
            raise AoneError("a1 could not execute") from exc
        if result.returncode:
            # CLI diagnostics can contain authentication configuration or tokens.
            raise AoneError(f"a1 command failed (exit {result.returncode}); inspect local CLI diagnostics")
        output = result.stdout
        if not isinstance(output, str):
            raise AoneError("a1 runner must return decoded text output")
        if json_output:
            try:
                return _decode_json(output.encode("utf-8"), "a1 response")
            except ProjectError as exc:
                raise AoneError("a1 returned invalid JSON; adapter/schema reconciliation required") from exc
        return output.strip()

    def _whoami(self):
        value = self._run("auth", "whoami", json_output=True)
        if not isinstance(value, dict):
            raise AoneError("a1 whoami schema requires an object with emp_id")
        return _string(value.get("emp_id"), "a1 whoami emp_id")

    def preflight(self):
        """Validate configuration and supported installed CLI once per adapter."""
        if self.identity is not None:
            return {"cli_version": "0.2.46", "employee_id": self.identity}
        cfg = self.config
        if not isinstance(cfg, dict):
            raise AoneError("Aone backend is not enabled")
        for key in ("space_id", "type", "category"):
            _string(cfg.get(key), f"Aone {key}")
        mapping = cfg.get("status_map")
        if (not isinstance(mapping, dict) or set(mapping) != STATUSES or
                any(not isinstance(value, str) or not value.strip() for value in mapping.values())):
            raise AoneError("Aone status_map must map every local status to its confirmed Aone value")
        supported = {"space_id", "type", "category", "status_map", "required_custom_fields"}
        unsupported = sorted(key for key in cfg if key not in supported and cfg[key] not in (None, {}, []))
        if unsupported:
            raise AoneError("unsupported Aone configuration: " + ", ".join(unsupported))
        fields = cfg.get("required_custom_fields", {})
        if not isinstance(fields, dict):
            raise AoneError("Aone required_custom_fields must map exact field identifiers/labels to strings")
        for key, value in fields.items():
            _string(key, "custom field key")
            _string(value, "custom field value")
            if "=" in key or "\n" in key:
                raise AoneError("custom field key must not contain '=' or newlines")
        version = self._run("--version")
        if not re.match(r"a1 version 0\.2\.46(?:\s|$)", version):
            raise AoneError("unsupported a1 version; verify and adapt the response contract before use")
        commands = (("get", ()), ("list", ("--project", "--scope", "--category", "--description", "--page", "--page-size", "--id")),
                    ("create", ("--project", "--type", "--category", "--title", "--assignee", "--status", "--body-file", "--cfs", "--quiet")),
                    ("update", ("--title", "--status", "--body-file", "--cfs")))
        for command, flags in commands:
            help_text = self._run("project", "workitem", command, "--help")
            if any(flag not in help_text for flag in flags) or "--format" not in help_text:
                raise AoneError(f"a1 {command} help differs from the supported adapter contract")
        self.identity = self._whoami()
        return {"cli_version": "0.2.46", "employee_id": self.identity}

    def _marker(self, identifier):
        for value in (self.project.get("id"), identifier):
            if not isinstance(value, str) or not ID.fullmatch(value):
                raise AoneError("project/item correlation IDs must be safe identifiers")
        return f"{BEGIN}project={self.project['id']} item={identifier} -->"

    def desired(self, item, files, git_source_commit):
        """Return the owned projection without issuing any CLI command."""
        self._marker(item["id"])
        if not isinstance(git_source_commit, str) or not COMMIT.fullmatch(git_source_commit):
            raise AoneError("git_source_commit must be a full immutable Git object ID")
        try:
            status = self.config["status_map"][item["status"]]
        except (KeyError, TypeError) as exc:
            raise AoneError("Aone status mapping is missing") from exc
        prefix = f"workitems/{item['id']}/"
        requirement = files.get(prefix + "requirement.md")
        if not isinstance(requirement, bytes) or not requirement.strip():
            raise AoneError("Aone projection requires complete requirement.md bytes")
        try:
            requirement = requirement.decode("utf-8")
        except UnicodeError as exc:
            raise AoneError("requirement.md must be UTF-8") from exc
        if BEGIN in requirement or END in requirement:
            raise AoneError("requirement contains reserved Aone managed-section delimiters")
        clone = _string(self.project.get("storage", {}).get("url"), "Git storage clone URL")
        paths = sorted(path for path in files if path.startswith(prefix))
        body = (self._marker(item["id"]) + "\n"
                f"Project: {self.project['id']}\nItem: {item['id']}\n"
                f"Archived: {'true' if item.get('archived') else 'false'}\n"
                f"Dependencies: {', '.join(item.get('depends_on', [])) or '(none)'}\n\n"
                "## Requirement and acceptance\n\n" + requirement.rstrip("\n") + "\n\n"
                f"## Immutable Git documents\n\nClone URL: {clone}\nCommit: {git_source_commit}\n"
                + "".join(f"Path: {path}\n" for path in paths) + END)
        return {"projection_version": 1,
                "title": f"【{_string(self.project.get('name'), 'project name')}】{_string(item.get('title'), 'item title')}",
                "status": status, "managed_body": body,
                "custom_fields": copy.deepcopy(self.config.get("required_custom_fields", {}))}

    def _section(self, body, marker):
        if not isinstance(body, str) or body.count(BEGIN) != 1 or body.count(END) != 1 or body.count(marker) != 1:
            raise AoneError("managed_body conflict: missing, duplicated or wrong project/item marker")
        start = body.index(marker)
        end = body.index(END) + len(END)
        if end <= start:
            raise AoneError("managed_body conflict: invalid delimiter order")
        return body[start:end], body[:start], body[end:]

    def _list(self, *filters):
        result = []
        # Bound reconciliation cost; an incomplete search must never authorize create.
        for page in range(1, 101):
            rows = self._run("project", "workitem", "list", "--project", self.config["space_id"],
                             "--scope", "project", "--category", self.config["category"],
                             *filters, "--page", str(page), "--page-size", "100", json_output=True)
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise AoneError("a1 list schema requires an array of objects")
            for row in rows:
                for key in ("identifier", "subject", "status", "spaceIdentifier", "workitemType", "categoryIdentifier", "assignedTo"):
                    _string(row.get(key), f"a1 list {key}")
            result.extend(rows)
            if len(rows) < 100:
                return result
        raise AoneError("Aone reconciliation exceeded 100 pages; narrow/reconcile manually")

    def _read(self, external_id, marker):
        if not isinstance(external_id, str) or not ID.fullmatch(external_id):
            raise AoneError("external ID must be one safe identifier")
        value = self._run("project", "workitem", "get", external_id, json_output=True)
        if not isinstance(value, dict) or value.get("id") != external_id:
            raise AoneError("a1 get schema/identity mismatch")
        fields = value.get("fields")
        if not isinstance(fields, list) or any(not isinstance(field, dict) for field in fields):
            raise AoneError("a1 get schema requires fields array")
        def field(key):
            matches = [entry for entry in fields if entry.get("identifier") == key or entry.get("label") == key]
            if len(matches) != 1 or not isinstance(matches[0].get("value"), str):
                raise AoneError(f"a1 get requires one string-valued field: {key}")
            return matches[0]
        for key, expected in (("space", self.config["space_id"]), ("workitemType", self.config["type"])):
            actual = field(key)
            if expected not in (actual["value"], actual.get("displayValue")):
                raise AoneError(f"Aone identity mismatch: {key}")
        rows = self._list("--id", external_id)
        if len(rows) != 1 or rows[0]["identifier"] != external_id:
            raise AoneError("Aone category identity lookup is absent or ambiguous")
        if rows[0]["categoryIdentifier"].lower() != self.config["category"].lower():
            raise AoneError("Aone identity mismatch: categoryIdentifier")
        managed, before, after = self._section(value.get("description"), marker)
        projection = {"projection_version": 1, "title": _string(value.get("title"), "a1 get title"),
                      "status": field("status")["value"], "managed_body": managed,
                      "custom_fields": {key: field(key)["value"] for key in self.config.get("required_custom_fields", {})}}
        return {"fields": projection, "before": before, "after": after,
                "assignee": field("assignedTo")["value"], "url": value.get("url")}

    def prepare_sync(self, item, files, receipt):
        self.preflight()
        if not isinstance(receipt, dict) or receipt.get("state") not in {"pending", "unknown", "verified"}:
            raise AoneError("Aone synchronization requires a durable pending/unknown/verified receipt")
        if receipt.get("content_sha256") != _business_digest(files, item["id"]):
            raise AoneError("receipt business digest differs from synchronization input")
        _string(receipt.get("intent_id"), "receipt intent_id")
        expected = self.desired(item, files, receipt.get("git_source_commit"))
        marker = self._marker(item["id"])
        previous_operation = receipt.get("operation")
        receipt_snapshot = {key: copy.deepcopy(value) for key, value in receipt.items() if key != "operation"}
        plan = {"action": "create", "external_id": receipt.get("external_id"), "marker": marker,
                "expected_fields": expected, "identity": self.identity,
                "receipt": receipt_snapshot, "body": expected["managed_body"], "observed_fields": None}
        old = previous_operation
        if receipt["state"] == "unknown" and receipt.get("baseline_fields") is None and isinstance(old, dict) and old.get("action") == "adopt":
            if old.get("expected_fields") != expected or old.get("marker") != marker:
                raise AoneError("unknown adoption differs from recorded operation; reconciliation required")
            adopted_id = old.get("external_id")
            if plan["external_id"] not in (None, adopted_id):
                raise AoneError("unknown adoption has conflicting external IDs")
            plan["external_id"] = adopted_id
            plan["identity"] = old.get("identity")
            actual = self._read(adopted_id, marker)
            self._verify(actual, expected)
            if actual["assignee"] != plan["identity"]:
                raise AoneError("unknown adoption identity mismatch: assignedTo")
            plan["action"] = "adopt"
            return plan
        if receipt["state"] == "unknown" and not plan["external_id"]:
            if (not isinstance(old, dict) or old.get("action") != "create" or
                    old.get("expected_fields") != expected or old.get("marker") != marker):
                raise AoneError("unknown create lacks the exact recorded operation; reconciliation required")
            candidates = self._list("--description", marker)
            if len(candidates) != 1:
                raise AoneError(f"unknown create has {len(candidates)} candidates; reconcile without recreating")
            plan["external_id"] = candidates[0]["identifier"]
            plan["identity"] = old.get("identity")
            actual = self._read(plan["external_id"], marker)
            self._verify(actual, expected)
            if actual["assignee"] != plan["identity"]:
                raise AoneError("unknown create identity mismatch: assignedTo")
            plan["action"] = "adopt"
            return plan
        if not plan["external_id"]:
            if receipt.get("baseline_fields") is not None:
                raise AoneError("baseline without an external ID requires reconciliation")
            return plan
        baseline = receipt.get("baseline_fields")
        if not isinstance(baseline, dict) or set(baseline) != set(expected) or baseline.get("projection_version") != 1:
            raise AoneError("unsupported baseline_fields projection; explicit adapter reconciliation required")
        actual = self._read(plan["external_id"], marker)
        if receipt["state"] == "unknown" and isinstance(old, dict) and old.get("expected_fields") == expected and actual["fields"] == expected:
            plan["action"] = "adopt"
            return plan
        drift = _differences(actual["fields"], baseline)
        if drift:
            raise AoneError("Aone managed-field drift: " + ", ".join(drift))
        plan["observed_fields"] = actual["fields"]
        plan["body"] = actual["before"] + expected["managed_body"] + actual["after"]
        plan["action"] = "noop" if actual["fields"] == expected else "update"
        return plan

    @staticmethod
    def _verify(actual, expected):
        mismatch = _differences(actual["fields"], expected)
        if mismatch:
            raise AoneError("Aone readback mismatch: " + ", ".join(mismatch))

    def execute(self, plan):
        """Execute a caller-journaled plan, then return a verified receipt.

        known-limit: a1 has no verified CAS or idempotency key. Re-read narrows
        the manual-edit race; upgrading requires a verified server CAS contract.
        """
        self.preflight()
        plan = copy.deepcopy(plan)
        action, expected = plan["action"], plan["expected_fields"]
        external_id = plan.get("external_id")
        if action not in {"create", "update", "adopt", "noop"}:
            raise AoneError("unsupported Aone operation action")
        if action in {"create", "update"}:
            if self._whoami() != plan["identity"]:
                raise AoneError("Aone authenticated identity changed since operation preparation")
            body = plan["body"]
            write_status = action == "create"
            if action == "update":
                current = self._read(external_id, plan["marker"])
                self._verify(current, plan["observed_fields"])
                body = current["before"] + expected["managed_body"] + current["after"]
                # --status requests a workflow transition; self-transitions are rejected.
                write_status = current["fields"]["status"] != expected["status"]
            with tempfile.TemporaryDirectory(prefix="project-aone-") as directory:
                path = Path(directory) / "body.md"
                path.write_text(body, encoding="utf-8")
                arguments = ["project", "workitem", action]
                if action == "create":
                    arguments += ["--project", self.config["space_id"], "--type", self.config["type"],
                                  "--category", self.config["category"], "--assignee", plan["identity"]]
                else:
                    arguments.append(external_id)
                arguments += ["--title", expected["title"], "--body-file", str(path)]
                if write_status:
                    arguments += ["--status", expected["status"]]
                for key, value in sorted(expected["custom_fields"].items()):
                    arguments += ["--cfs", f"{key}={value}"]
                if action == "create":
                    arguments.append("--quiet")
                output = self._run(*arguments)
                if action == "create":
                    if not ID.fullmatch(output):
                        raise AoneError("create returned no single ID; reconcile the unknown create by marker")
                    external_id = output
        actual = self._read(external_id, plan["marker"])
        self._verify(actual, expected)
        if action in {"create", "adopt"} and not plan["receipt"].get("external_id") and actual["assignee"] != plan["identity"]:
            raise AoneError("Aone create readback mismatch: assignedTo")
        receipt = plan["receipt"]
        receipt.update(state="verified", external_id=external_id, baseline_fields=actual["fields"],
                       checked_at=datetime.now(timezone.utc).isoformat())
        receipt["operation"] = {key: value for key, value in plan.items() if key != "receipt"}
        if isinstance(actual["url"], str) and actual["url"]:
            receipt["external_url"] = actual["url"]
        return receipt

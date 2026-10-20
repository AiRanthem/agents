#!/usr/bin/env python3
"""Check project-stage agents, print native roles, or assemble captured host receipts."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
ROLES = {
    "project-design-reviewer": "design-review",
    "project-implementer": "implementation",
    "project-implementation-reviewer": "code-review",
    "project-fixer": "fix",
}
SKILLS = ("advance-project", "review-design", "explore-design", "implement-design",
          "review-implementation", "receiving-code-review")


def role_config(host, name):
    extension = "toml" if host == "codex" else "md"
    source = ROOT / host / "agents" / f"{name}.{extension}"
    content = source.read_text()
    if host == "codex":
        config = tomllib.loads(content)
    else:
        # These checked-in templates deliberately use JSON strings as YAML scalars.
        # known-limit: this is not a general YAML parser; a richer frontmatter
        # format must replace this reader with a YAML parser before it is adopted.
        header, body = content.removeprefix("---\n").split("\n---\n", 1)
        config = dict((key, json.loads(value.strip()))
                      for key, value in (line.split(":", 1) for line in header.splitlines()))
        config["developer_instructions"] = body.strip()
    for key in ("name", "description", "model", "developer_instructions"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{source}: missing {key}")
    if config["name"] != name:
        raise ValueError(f"{source}: native role name mismatch")
    if host == "codex" and not config.get("model_reasoning_effort"):
        raise ValueError(f"{source}: missing model_reasoning_effort")
    if host == "qoder" and not config.get("effort"):
        raise ValueError(f"{source}: missing effort")
    return source, content, config


def _skill_files(directory):
    files = {}
    for path in directory.rglob("*"):
        relative = path.relative_to(directory)
        if "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            raise ValueError(f"copied skill contains a symlink: {path}")
        if path.is_file():
            files[relative.as_posix()] = path.read_bytes()
    return files


def check(host, home, *, agents_dir=None, roles_file=None, skills_dir=None):
    if host != "cursor" and any(value is not None for value in (agents_dir, roles_file, skills_dir)):
        raise ValueError("explicit role/skill sources are supported only for Cursor")
    if agents_dir is not None and roles_file is not None:
        raise ValueError("select either an agents directory or injected roles")
    injected = None
    if roles_file is not None:
        injected = json.loads(roles_file.read_text())
        if not isinstance(injected, dict):
            raise ValueError("injected roles must be an object keyed by native role name")
    missing, roles = [], {}
    for name, stage in ROLES.items():
        source, content, config = role_config(host, name)
        target = (agents_dir if agents_dir is not None else home / f".{host}" / "agents") / source.name
        roles[name] = {"stage": stage, "source": str(source), "installed": str(target),
                       "model": config["model"]}
        if host == "codex":
            roles[name]["model_reasoning_effort"] = config["model_reasoning_effort"]
        if host == "qoder":
            roles[name]["effort"] = config["effort"]
        if injected is not None:
            actual = injected.get(name)
            if (not isinstance(actual, dict) or not isinstance(actual.get("source"), str) or
                    not actual["source"].strip()):
                missing.append(f"missing injected role or source: {name}")
            else:
                roles[name]["installed"] = actual["source"]
                if any(actual.get(key) != value for key, value in config.items()):
                    missing.append(f"injected role differs from repository: {name}")
            continue
        if host in ("codex", "qoder") and target.is_symlink():
            kind = "TOML" if host == "codex" else "Markdown"
            missing.append(f"native {host.capitalize()} agent must be a regular {kind} file: {target}")
        elif host == "cursor" and agents_dir is None and (not target.is_symlink() or target.resolve() != source.resolve()):
            missing.append(f"native Cursor agent must link to repository template: {target} -> {source}")
        elif not target.is_file():
            missing.append(f"missing native agent: {target}")
        elif target.read_text() != content:
            missing.append(f"native agent differs from repository: {target}")
    skill_root = skills_dir if skills_dir is not None else home / (".cursor" if host == "cursor" else ".agents") / "skills"
    for name in SKILLS:
        skill_dir = skill_root / name
        expected = ROOT / "skills" / name
        try:
            if not skill_dir.is_symlink() or skill_dir.resolve(strict=True) != expected.resolve():
                if skills_dir is not None and skill_dir.is_dir() and not skill_dir.is_symlink():
                    if _skill_files(skill_dir) != _skill_files(expected):
                        missing.append(f"copied skill differs from repository: {skill_dir}")
                else:
                    missing.append(f"skill must link to repository directory: {skill_dir} -> {expected}")
                continue
            with (skill_dir / "SKILL.md").open("rb") as entry:
                entry.read(1)
        except (OSError, RuntimeError, ValueError) as error:
            missing.append(f"unreadable skill entry: {skill_dir / 'SKILL.md'}: {error}")
    return {"host": host, "disk_ready": not missing, "roles": roles, "missing": missing,
            "runtime_verified": False}


def _receipt_runtime():
    sys.path.insert(0, str(ROOT / "skills" / "manage-workitems" / "scripts"))
    import project_autonomy
    return project_autonomy


def _regular_input(path):
    path = path.absolute()
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError(f"capture input must be a regular file without symlink components: {path}")
    return path


def capture_receipt(args):
    """Assemble actual coordinator-captured tool data; this does not call a host."""
    api = _receipt_runtime()
    raw = api.runtime.read_json(_regular_input(args.raw_file))
    receipt = {"host": args.host, "tool": args.tool, "raw": raw}
    if args.call_id:
        receipt["call_id"] = args.call_id
    if args.dispatch_file:
        context = api.runtime.read_json(_regular_input(args.dispatch_file))
        if (not isinstance(context, dict) or context.get("status") != "ready" or context.get("worker_paused") is not False or
                any(not context.get(key) for key in ("attempt", "worker_id", "role", "input_binding",
                                                       "approved_contract", "read", "code_context"))):
            raise ValueError("result receipt requires the complete accepted ready dispatch")
        receipt.update({key: context[key] for key in ("attempt", "worker_id", "role", "input_binding")})
        if args.worker_id and args.worker_id != receipt["worker_id"]:
            raise ValueError("worker differs from the accepted dispatch")
        if not args.report_file or not args.outcome or not args.terminal_status:
            raise ValueError("result receipt requires report, outcome and observed terminal status")
        receipt.update(outcome=args.outcome, terminal_status=args.terminal_status,
                       descendants_stopped=args.descendants_stopped,
                       report_file=str(_regular_input(args.report_file)))
        api._read_report(receipt["report_file"])
        if args.candidate_file:
            receipt["candidate_file"] = str(_regular_input(args.candidate_file))
            api._read_report(receipt["candidate_file"])
        if args.outcome == "revised" and not args.candidate_file:
            raise ValueError("revised result requires the actual candidate file")
        if args.contract_unchanged:
            receipt["contract_unchanged"] = True
        if args.mechanical_correction:
            receipt["mechanical_correction"] = True
    else:
        if any((args.outcome, args.report_file, args.candidate_file, args.terminal_status,
                args.descendants_stopped, args.contract_unchanged, args.mechanical_correction)):
            raise ValueError("result fields require an accepted dispatch file")
        receipt["worker_id"] = args.worker_id
    api._receipt(receipt)
    if args.dispatch_file:
        api._result_outcome(receipt)
    output = args.output.absolute()
    if any(part.is_symlink() for part in (output, *output.parents)) or not output.parent.is_dir():
        raise ValueError("receipt output requires an existing directory without symlink components")
    data = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    # Exclusive creation preserves the exact raw evidence on repeated invocation.
    with output.open("x", encoding="utf-8") as stream:
        output.chmod(0o600)
        stream.write(data)
    return {"status": "captured", "receipt_file": str(output), "worker_id": receipt["worker_id"],
            "sha256": hashlib.sha256(data.encode("utf-8")).hexdigest()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "role", "receipt"))
    parser.add_argument("--host", required=True, choices=("codex", "cursor", "qoder"))
    parser.add_argument("--home", type=Path, default=Path.home())
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--agents-dir", type=Path, help="Cursor project/cloud native agent directory")
    sources.add_argument("--roles-file", type=Path, help="Cursor injected role definitions and actual sources (JSON)")
    parser.add_argument("--skills-dir", type=Path, help="Cursor skill directory; accepts exact copies or repository links")
    parser.add_argument("--name", choices=ROLES, help="Native stage role for explicit dispatch")
    parser.add_argument("--tool", help="Actual native tool name for receipt assembly")
    parser.add_argument("--raw-file", type=Path, help="Unchanged actual tool arguments/result JSON")
    parser.add_argument("--worker-id", help="Native worker identity; required for a spawn receipt")
    parser.add_argument("--dispatch-file", type=Path, help="Complete accepted dispatch for a result receipt")
    parser.add_argument("--outcome", choices=("pass", "fail", "blocked", "revised", "contract-change"))
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--candidate-file", type=Path)
    parser.add_argument("--terminal-status", choices=("completed", "failed", "stopped"))
    parser.add_argument("--descendants-stopped", action="store_true")
    parser.add_argument("--contract-unchanged", action="store_true")
    parser.add_argument("--mechanical-correction", action="store_true",
                        help="Actual deterministic candidate correction confirmed by the independent design reviewer")
    parser.add_argument("--call-id", help="Only an ID exposed by the actual host tool")
    parser.add_argument("--output", type=Path, help="New controller-owned receipt file")
    args = parser.parse_args(argv)
    try:
        if args.command == "receipt":
            if not args.raw_file or not args.output or not args.tool:
                parser.error("receipt requires --raw-file, --output and --tool")
            try:
                result = capture_receipt(args)
            except _receipt_runtime().ProjectError as error:
                raise ValueError(str(error)) from error
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "role":
            if args.name is None:
                parser.error("role requires --name")
            source, _, config = role_config(args.host, args.name)
            print(json.dumps({"host": args.host, "source": str(source), **config}, indent=2))
            return 0
        result = check(args.host, args.home, agents_dir=args.agents_dir,
                       roles_file=args.roles_file, skills_dir=args.skills_dir)
        print(json.dumps(result, indent=2))
        return 0 if result["disk_ready"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        failure = ({"host": args.host, "status": "blocked", "error": str(error)}
                   if args.command == "receipt" else
                   {"host": args.host, "disk_ready": False, "missing": [str(error)]})
        print(json.dumps(failure))
        return 1


if __name__ == "__main__":
    sys.exit(main())

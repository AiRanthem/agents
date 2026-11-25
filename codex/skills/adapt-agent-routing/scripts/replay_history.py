"""Replay local Codex child usage and optional delegation feedback without emitting conversation text."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from statistics import median
import subprocess


FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")
DISPOSITIONS = {"直接采用": "used", "修正后采用": "used_after_correction", "未采用": "unused",
                "任务失效": "superseded", "补正": "correction_requested", "新任务": "new"}
MARKER = re.compile(r"\[([a-z0-9_]+(?:#[a-z0-9_]+)?) (" + "|".join(DISPOSITIONS) + r")\]")


class Gap(ValueError):
    """A missing or inconsistent observation that should stay in the coverage report."""


@contextmanager
def rollout(path):
    if path.is_file() and path.suffix != ".zst":
        with path.open("rb") as stream:
            yield stream
        return
    archive = path if path.suffix == ".zst" else Path(str(path) + ".zst")
    if not archive.is_file():
        raise Gap("missing rollout")
    try:
        decoder = subprocess.Popen(["zstd", "-qdc", "--", str(archive)], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL)
    except FileNotFoundError as error:
        raise Gap("zstd executable missing") from error
    with decoder:
        with decoder.stdout:
            yield decoder.stdout
        if decoder.wait():
            raise Gap("unreadable zstd archive")


def counts(usage):
    values = {key: usage[key] for key in FIELDS}
    if (any(type(v) is not int or v < 0 for v in values.values())
            or values["cached_input_tokens"] > values["input_tokens"]):
        raise Gap("invalid token counts")
    return values


def first_turn_usage(stream, thread, turn, start, end, status):
    if end is None:
        raise Gap("first turn still open" if status == "inProgress" else "missing turn boundary")
    if not isinstance(start, int) or not isinstance(end, int) or not 0 < start < end:
        raise Gap("invalid indexed turn bounds")
    header = json.loads(next(stream, b"{}"))
    if header["type"] != "session_meta" or header["payload"]["id"] != thread:
        raise Gap("rollout identity mismatch")
    profiles = set()
    responses = {}
    total = Counter()
    closed = False
    for ordinal, line in enumerate(stream, start=1):
        if ordinal < start or ordinal > end:
            continue
        row = json.loads(line)
        kind = row["type"]
        data = row["payload"]
        if ordinal in (start, end):
            if kind != "event_msg" or data.get("turn_id") != turn:
                raise Gap("turn boundary mismatch")
            if ordinal == start and data["type"] != "task_started":
                raise Gap("turn start mismatch")
            if ordinal == end:
                terminal = "turn_aborted" if status == "interrupted" else "task_complete"
                if data["type"] != terminal:
                    raise Gap("turn end mismatch")
                closed = True
            continue
        if kind not in ("turn_context", "token_usage_record"):
            continue
        if data.get("turn_id") != turn:
            continue
        if kind == "turn_context":
            profiles.add((data.get("model"), data.get("effort")))
            continue
        if data.get("thread_id") != thread:
            continue
        response = data.get("response_id")
        if not isinstance(response, str) or not response:
            raise Gap("missing response identity")
        usage = counts(data["usage"])
        if response in responses:
            if responses[response] != usage:
                raise Gap("conflicting duplicate response")
            continue
        responses[response] = usage
        total.update(usage)
        if dict(total) != counts(data["turn_token_usage"]):
            raise Gap("response sum differs from turn snapshot")
    if not closed:
        raise Gap("incomplete rollout")
    if not responses:
        raise Gap("missing response usage")
    if len(profiles) != 1:
        raise Gap("unresolved model or effort")
    model, effort = profiles.pop()
    if not all(isinstance(v, str) and v for v in (model, effort)):
        raise Gap("unresolved model or effort")
    return dict(model=model, effort=effort, tokens=dict(total),
                max_request_input=max(v["input_tokens"] for v in responses.values()))


def database(path):
    return closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True))


def feedback_marks(message):
    """Read trailing disposition marks on ordinary prose lines, excluding quoted examples."""
    fence = None
    for line in message.splitlines():
        if line.startswith(("    ", "\t")):
            continue
        line = line.strip()
        if line.startswith(("```", "~~~")):
            delim = line[:3]
            if fence in (None, delim):
                fence = None if fence else delim
        elif not fence and not line.startswith(">"):
            marks = []
            for match in reversed(list(MARKER.finditer(line))):
                if line[match.end():].strip():
                    break
                marks.append((match[1], DISPOSITIONS[match[2]]))
                line = line[:match.start()]
            yield from reversed(marks)


def parent_feedback(stream, parent, children):
    header = json.loads(next(stream, b"{}"))
    if header.get("type") != "session_meta" or header["payload"]["id"] != parent:
        raise Gap("parent rollout identity mismatch")
    assignments = {child: [dict(outcome="unknown")] for child in children}
    by_key = {}
    calls = {}
    pending = {}
    gaps = Counter()

    def apply_marks(marks, ordinal, turn, target=None):
        for key, action in marks:
            name = key.partition("#")[0]
            if name not in by_key:
                continue
            if target is None and (action == "new" or action == "correction_requested"):
                pending[turn, name] = key, action
            if action == "new":
                continue
            if key not in by_key:
                gaps["feedback for unlinked assignment"] += 1
                continue
            child, record = by_key[key]
            if target is not None and target != child:
                continue
            record["feedback_ordinal"] = ordinal
            if action == "correction_requested":
                record["correction_requested"] = True
                record["outcome"] = "unknown"
            elif action == "used" and record.get("correction_requested"):
                record["outcome"] = "used_after_correction"
            else:
                record["outcome"] = action

    for ordinal, line in enumerate(stream, 1):
        row = json.loads(line)
        data = row["payload"]
        if row["type"] == "response_item":
            if (data.get("type") == "function_call" and data.get("namespace") == "collaboration"
                    and data.get("name") in ("followup_task", "send_message")):
                try:
                    message = json.loads(data["arguments"])["message"]
                    marks = list(feedback_marks(message))
                except (ValueError, KeyError, TypeError, AttributeError):
                    marks = []
                calls[data["call_id"]] = data["name"], ordinal, marks
            elif data.get("type") == "function_call_output":
                calls.pop(data["call_id"], None)
            continue
        if (row["type"] != "event_msg" or data.get("type") != "item_completed"
                or data.get("thread_id") != parent):
            continue
        item = data["item"]
        turn = data["turn_id"]
        if item["type"] == "AgentMessage":
            for part in item["content"]:
                if part["type"] == "Text":
                    apply_marks(feedback_marks(part["text"]), ordinal, turn)
            continue
        if (item["type"] != "SubAgentActivity" or item["agent_thread_id"] not in children
                or item["kind"] not in ("started", "interacted")):
            continue
        child = item["agent_thread_id"]
        name = item["agent_path"].rsplit("/", 1)[-1]
        if item["kind"] == "started":
            record = assignments[child][0]
            record.update(key=name, dispatch_ordinal=ordinal)
            by_key[name] = child, record
        else:
            tool, call_ordinal, instruction_marks = calls.get(item["id"], (None, ordinal, []))
            if name not in by_key or by_key[name][0] != child:
                if tool != "send_message":
                    gaps["unclassified follow-up"] += 1
                continue
            # Some local transcripts redact tool messages. Join the preceding reassignment
            # update to the actual delivery in the same parent turn.
            announced = pending.pop((turn, name), None)
            marks = [*instruction_marks, announced] if announced else instruction_marks
            new_keys = {key for key, action in marks if action == "new" and key.startswith(name + "#")}
            if len(new_keys) == 1 and new_keys.isdisjoint(by_key):
                key = new_keys.pop()
                record = dict(key=key, dispatch_ordinal=ordinal, outcome="unknown")
                assignments[child].append(record)
                by_key[key] = child, record
            else:
                correction = any(key in by_key and by_key[key][0] == child and action == "correction_requested"
                                 for key, action in marks)
                # known-limit: classifying unmarked follow-ups needs inspection of the original assignment.
                if new_keys or tool is None or (tool == "followup_task" and not correction):
                    gaps["unclassified follow-up"] += 1
            apply_marks(instruction_marks, call_ordinal, turn, child)
    gaps["missing indexed child start in parent rollout"] += sum(
        "key" not in records[0] for records in assignments.values())
    return assignments, +gaps


def collect_feedback(home, cases):
    parents = defaultdict(dict)
    gaps = Counter()
    for case in cases:
        case["assignments"] = [dict(outcome="unknown")]
        if case["parent"]:
            parents[case["parent"]][case["thread"]] = case
        else:
            gaps["missing parent"] += 1
    with database(home / "state_5.sqlite") as state:
        for parent, children in parents.items():
            row = state.execute("SELECT rollout_path FROM threads WHERE id = ?", (parent,)).fetchone()
            try:
                if not row or not row[0]:
                    raise Gap("missing parent rollout")
                with rollout(Path(row[0])) as stream:
                    assignments, missing = parent_feedback(stream, parent, children)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                gaps[str(error) if isinstance(error, Gap) else type(error).__name__] += 1
                continue
            gaps.update(missing)
            for child, records in assignments.items():
                children[child]["assignments"] = records
    totals = dict(assignments=0, with_feedback=0, corrections_requested=0, outcomes=Counter(), gaps=gaps)
    for case in cases:
        for record in case["assignments"]:
            totals["assignments"] += 1
            totals["with_feedback"] += "feedback_ordinal" in record
            totals["corrections_requested"] += bool(record.get("correction_requested"))
            totals["outcomes"][record["outcome"]] += 1
    return totals


def collect(home, since, until, selected_threads=()):
    query = """
        SELECT t.id, t.rollout_path, e.parent_thread_id
        FROM threads t LEFT JOIN thread_spawn_edges e ON e.child_thread_id = t.id
        WHERE (t.thread_source = 'subagent' OR e.child_thread_id IS NOT NULL)
          AND t.created_at >= ? AND t.created_at < ? ORDER BY t.created_at, t.id
    """
    remaining = set(selected_threads)
    with database(home / "state_5.sqlite") as state, database(home / "thread_history_1.sqlite") as history:
        for thread, path, parent in state.execute(query, (since, until)):
            if selected_threads and thread not in selected_threads:
                continue
            remaining.discard(thread)
            case = dict(thread=thread, parent=parent)
            first = history.execute("""
                SELECT turn_id, status, duration_ms, final_agent_item_id, rollout_ordinal, rollout_end_ordinal
                FROM thread_turns
                WHERE thread_id = ? ORDER BY rollout_ordinal LIMIT 1
            """, (thread,)).fetchone()
            if first is None:
                yield dict(case, gap="missing indexed turn")
                continue
            turn, status, duration, final, start, end = first
            case.update(turn=turn, status=status, duration_ms=duration, final_item=bool(final))
            try:
                with rollout(Path(path)) as stream:
                    case.update(first_turn_usage(stream, thread, turn, start, end, status))
            except Gap as error:
                case["gap"] = str(error)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                case["gap"] = type(error).__name__
            yield case
    if remaining:
        raise ValueError(f"selected child threads missing from window: {', '.join(sorted(remaining))}")


def price(case, rates):
    uncached, cached, output, limit = rates
    t = case["tokens"]
    # known-limit: a cache write or tier crossing needs request-level prices for the entire turn.
    if t["cache_write_input_tokens"] or case["max_request_input"] > limit:
        return None
    return ((t["input_tokens"] - t["cached_input_tokens"]) * uncached
            + t["cached_input_tokens"] * cached + t["output_tokens"] * output) / 1_000_000


def summarize(cases, rates):
    groups = defaultdict(list)
    for case in cases:
        if "gap" not in case:
            groups[case["model"], case["effort"]].append(case)
    rows = []
    for (model, effort), group in sorted(groups.items()):
        completed = [c for c in group if c["status"] == "completed"]
        times = [c["duration_ms"] / 60000 for c in completed if c["duration_ms"] is not None]
        estimates = {}
        for name, rate in rates.items():
            costs = [p for c in group if (p := price(c, rate)) is not None]
            estimates[name] = dict(priced=len(costs), sum_usd=round(sum(costs), 8) if costs else None,
                                   median_usd=round(median(costs), 8) if costs else None)
        rows.append(dict(model=model, effort=effort, threads=len(group),
                         statuses=dict(Counter(c["status"] for c in group)),
                         completed_with_final_item=sum(c["final_item"] for c in completed),
                         completed_with_duration=len(times),
                         median_completed_minutes=round(median(times), 3) if times else None,
                         tokens={key: sum(c["tokens"][key] for c in group) for key in FIELDS},
                         fixed_token_usd=estimates))
    return dict(indexed_children=len(cases), known_parents=len({c["parent"] for c in cases if c["parent"]}),
                gaps=dict(Counter(c["gap"] for c in cases if "gap" in c)), groups=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", required=True, help="Inclusive ISO date or timestamp (local time by default)")
    parser.add_argument("--until", required=True, help="Exclusive ISO date or timestamp")
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--rate", action="append", nargs=5, default=[],
                        metavar=("MODEL", "INPUT", "CACHED", "OUTPUT", "MAX_INPUT"),
                        help="USD per million tokens and inclusive request input ceiling, or 'any' for a flat rate")
    parser.add_argument("--cases", action="store_true", help="Include local join keys and first-turn measurements")
    parser.add_argument("--feedback", action="store_true", help="Read parent dispositions for the selected children")
    parser.add_argument("--thread", action="append", default=[], metavar="ID",
                        help="Limit the report to these child threads in the window (repeat for each ID)")
    args = parser.parse_args()
    try:
        since, until = (datetime.fromisoformat(v).astimezone() for v in (args.since, args.until))
        if since >= until:
            raise ValueError("--until must follow --since")
        rates = {}
        for model, uncached, cached, output, limit in args.rate:
            amounts = tuple(map(float, (uncached, cached, output)))
            ceiling = math.inf if limit == "any" else int(limit)
            if model in rates or ceiling <= 0 or any(not math.isfinite(v) or v < 0 for v in amounts):
                raise ValueError("expected unique rate names, nonnegative finite prices and positive ceilings")
            rates[model] = (*amounts, ceiling)
        home = args.codex_home.expanduser()
        cases = list(collect(home, since.timestamp(), until.timestamp(), set(args.thread)))
        report = summarize(cases, rates)
        if args.feedback:
            report["feedback"] = collect_feedback(home, cases)
    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(2, f"History replay unavailable: {error}\n")
    report.update(created_since=since.isoformat(), created_before=until.isoformat(), rate_arguments=args.rate)
    report["population"] = "selected_children_in_window" if args.thread else "all_indexed_children_in_window"
    if args.cases:
        report["cases"] = cases
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

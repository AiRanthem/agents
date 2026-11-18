"""Summarize first turns of locally indexed Codex child threads without emitting conversation text."""

import argparse
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
from statistics import median
import subprocess


FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens")


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


def collect(home, since, until):
    # A fixed-stage delegate can itself spawn a child with an ordinary role name.
    query = """
        WITH RECURSIVE lineage(id, scope) AS (
          SELECT t.id, 'ordinary' FROM threads t
          WHERE t.thread_source = 'user'
          UNION
          SELECT e.child_thread_id, CASE WHEN t.agent_role GLOB 'project-*' THEN 'fixed' ELSE l.scope END
          FROM lineage l JOIN thread_spawn_edges e ON e.parent_thread_id = l.id
          JOIN threads t ON t.id = e.child_thread_id
        )
        SELECT t.id, t.rollout_path, e.parent_thread_id, coalesce(l.scope, 'unknown')
        FROM threads t LEFT JOIN thread_spawn_edges e ON e.child_thread_id = t.id
        LEFT JOIN lineage l ON l.id = t.id
        WHERE (t.thread_source = 'subagent' OR e.child_thread_id IS NOT NULL)
          AND t.created_at >= ? AND t.created_at < ? ORDER BY t.created_at, t.id
    """
    with database(home / "state_5.sqlite") as state, database(home / "thread_history_1.sqlite") as history:
        for thread, path, parent, scope in state.execute(query, (since, until)):
            case = dict(thread=thread, parent=parent, scope=scope)
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
            groups[case["scope"], case["model"], case["effort"]].append(case)
    rows = []
    for (scope, model, effort), group in sorted(groups.items()):
        completed = [c for c in group if c["status"] == "completed"]
        times = [c["duration_ms"] / 60000 for c in completed if c["duration_ms"] is not None]
        estimates = {}
        for name, rate in rates.items():
            costs = [p for c in group if (p := price(c, rate)) is not None]
            estimates[name] = dict(priced=len(costs), sum_usd=round(sum(costs), 8) if costs else None,
                                   median_usd=round(median(costs), 8) if costs else None)
        rows.append(dict(scope=scope, model=model, effort=effort, threads=len(group),
                         statuses=dict(Counter(c["status"] for c in group)),
                         completed_with_final_item=sum(c["final_item"] for c in completed),
                         completed_with_duration=len(times),
                         median_completed_minutes=round(median(times), 3) if times else None,
                         tokens={key: sum(c["tokens"][key] for c in group) for key in FIELDS},
                         fixed_token_usd=estimates))
    return dict(indexed_children=len(cases), known_parents=len({c["parent"] for c in cases if c["parent"]}),
                scope_counts=dict(Counter(c["scope"] for c in cases)),
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
        cases = list(collect(args.codex_home.expanduser(), since.timestamp(), until.timestamp()))
    except (ValueError, sqlite3.Error, OSError) as error:
        parser.exit(2, f"History replay unavailable: {error}\n")
    report = summarize(cases, rates)
    report.update(created_since=since.isoformat(), created_before=until.isoformat(), rate_arguments=args.rate)
    if args.cases:
        report["cases"] = cases
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

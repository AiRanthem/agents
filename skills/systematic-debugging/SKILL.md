---
name: systematic-debugging
description: Investigate bugs, failing tests, and unexpected behavior by tracing evidence to the responsible boundary and verifying a focused fix. Use when explicitly invoked; diagnosis alone remains read-only unless repair is requested.
---

# Systematic Debugging

Establish what failed, why the evidence supports that explanation, and whether the requested repair resolves it. Scale investigation to uncertainty and consequence; a clear local defect can need only a short trace and focused check.

## Evidence and diagnosis

Identify expected versus observed behavior, the affected version and environment, and the smallest available reproducer. Inspect errors, relevant changes, callers, and a working comparison when useful. For intermittent failures, preserve timing, ordering, and frequency; an unsuccessful reproduction does not disprove the failure.

Trace invalid data or state backward to its producer and forward through affected consumers. Across components, find the first boundary where the observed result differs from the contract. Prefer existing logs and read-only inspection. Add narrowly scoped diagnostics only within authorized repair or instrumentation work; collect allowlisted, redacted state rather than credentials, full environments, or sensitive payloads.

State the leading explanation and what observation would distinguish it from plausible alternatives. Use the smallest safe experiment that resolves that uncertainty. After a failed experiment, update the explanation using new evidence rather than accumulating speculative changes. Repeated attempts without new evidence call for a different observation or a precise missing-input question, not an automatic architecture rewrite.

## Repair and verification

When repair is requested, fix the cause at the boundary that owns the invariant. Preserve required validation at independent trust boundaries; add duplicate internal checks only for a demonstrated bypass or distinct contract. Keep unrelated cleanup separate.

For order-dependent tests, compare isolated and combined execution and narrow the responsible subset in a disposable environment. For asynchronous behavior, prefer existing event or condition-wait facilities with bounded timeout, cancellation, and useful failure state. Preserve actual timing assertions when timing is the contract; replacing a sleep with polling does not itself prove a race is fixed.

Use the smallest meaningful regression check for non-trivial behavior. Reuse adequate tests; trivial reversible fixes can use direct verification. Check the original failure and affected invariants, broadening only for shared behavior or concrete risk. Record the commands, results, and remaining limits.

When root cause remains unconfirmed, report what is established, what is hypothetical, and the next distinguishing evidence. An authorized emergency mitigation may proceed with its known limit, rollback, and follow-up; report it as mitigation rather than resolution. Pause only actions that need missing access, a changed contract, or additional authorization, and continue independent work.

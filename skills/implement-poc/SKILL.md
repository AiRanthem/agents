---
name: implement-poc
description: Build or repair the smallest verifiable proof of concept from a confirmed design by agreeing explicit acceptance criteria, trimming the design to the accepted happy path, implementing it quickly, diagnosing failures from runtime logs, and validating only that path. Use with $implement-poc or /implement-poc when the user wants fast feasibility evidence or needs a failed POC fixed from its logs. Exclude unconfirmed design exploration, production implementation, hardening, and review-only work.
---

# Implement POC

Produce the fastest runnable proof that the user's explicit acceptance scenario can work, or restore that proof when a POC run fails. The result is disposable POC code with enough runtime visibility to locate and fix faults in that scenario from logs. It is not production-ready implementation.

## Respect authority and host mode

- Follow user, harness, and higher-priority instructions, including permissions, security and data-protection boundaries, and safeguards for destructive or external actions. A POC does not expand authorization.
- **Plan mode** applies only when active host instructions explicitly establish native Plan mode. It is read-only: settle the acceptance contract and trimmed implementation or repair design, then return that design as the host's single final plan.
- **Agent mode** is normal operation outside native Plan restrictions. After the user confirms the acceptance contract and trimmed design, implement it directly without another planning phase.
- Preserve unrelated and pre-existing work. Do not create or modify design documents, ADRs, OpenSpec artifacts, task files, or review reports.

## Require an explicit acceptance contract

Do not trim the design, publish a final plan, or edit code until the user explicitly confirms concrete POC acceptance criteria. Silence, timeout, an inferred goal, or a broad request such as “prove the design” is not acceptance.

Acceptance criteria must make one runnable scenario unambiguous:

- the required environment and starting state;
- the exact input or actions that exercise the POC;
- the observable output, state transition, or external effect that constitutes success;
- any evidence the user expects to inspect, including required log evidence.

When criteria are missing or ambiguous, inspect the design and relevant current code first, then propose the smallest concrete acceptance scenario for confirmation. Continue independent read-only investigation while waiting, but do not make dependent choices.

## Trim the design with the user

Read the complete confirmed design and trace the current code only far enough to understand the accepted scenario and its callers. In Agent mode, when starting a POC without a current `implementable` status, explain the missing review assurance and obtain the user's explicit agreement before implementation; combine this with the acceptance and trimmed-design confirmation when useful. An approved Plan-mode final plan and its execution need no document status. A repair of an existing POC may reuse its current confirmed contract; a material Why/What change must be approved before affected repair. Convert the design into a POC implementation design that explains how the current code will become the runnable POC.

Present the user with three explicit groups and obtain confirmation before planning or implementation:

- **Do:** only the design goals and behavior required for the acceptance happy path.
- **Do not:** every other goal, defensive behavior, corner case, compatibility path, failure recovery, cleanup, cancellation, concurrency guarantee, production rollout concern, and quality improvement.
- **Modify:** any approved design behavior that must be simplified, hard-coded, bypassed, or replaced for this POC.

The trimmed design must identify the shortest concrete execution path, affected components and ownership boundaries, required data flow or interface shape, environment assumptions, shortcuts, runtime observability, and the minimal integration check. Resolve every choice that could change the accepted scenario. The user's confirmation of the concrete trimmed design authorizes its in-scope implementation; it does not authorize unrelated changes or external effects.

Keep the trimmed design only in the conversation or host-managed plan. Never write it to a repository file.

## Produce the mode-specific result

- **Plan mode:** Put the confirmed acceptance contract and trimmed implementation or repair design directly in the final plan. For a failed POC, include the log-supported failure point and code change. Include ordered implementation actions, the minimal happy-path integration check, required diagnostic logging, and the final diagnostic subagent audit. Tell the executor to load `$implement-poc` and execute this confirmed plan in Agent mode. Then stop without repository writes or implementation claims.
- **Agent mode:** Implement the confirmed trimmed design immediately. If resuming a plan, load `$implement-poc`, verify that the acceptance environment and relevant code assumptions still hold, and proceed. Return to the user only when new evidence changes the acceptance contract or trimmed design.

## Optimize only for time to acceptance

Choose the quickest implementation that can pass the accepted scenario. Reuse an existing path when it is faster; otherwise hard-code values, duplicate code, couple components, or bypass abstractions as needed.

- Do not write unit, component, regression, negative, boundary, compatibility, concurrency, or recovery tests.
- Do not write code comments or documentation.
- Do not perform general code review, refactoring, cleanup, formatting churn, or quality hardening.
- Do not optimize for readability, maintainability, extensibility, abstraction quality, repository architecture, or future reuse.
- Treat repository development conventions about style, layering, placement, test breadth, comments, review, readability, maintainability, compatibility, and production readiness as out of scope unless they are required by the acceptance path or a higher-priority instruction.
- Add no defensive behavior or corner-case handling beyond what the accepted environment and happy path actually exercise.

These shortcuts are requirements of this workflow. If a controlling instruction prevents one, obey that instruction and report the exact constraint instead of silently expanding the POC.

## Make the accepted path reconstructable from logs

Instrument the POC for maximum diagnostic visibility. A reader with the source and logs must be able to reconstruct the accepted execution from entry to completion or failure without attaching a debugger.

For every step and failure boundary on the accepted path, log enough context to connect the full run:

- a run or correlation identifier and the relevant resource identifiers;
- startup assumptions and effective configuration needed to explain behavior;
- entry and exit of each phase, branch decisions, state transitions, and elapsed time;
- external calls or commands, their destination and non-secret inputs, returned status, non-secret output, and errors;
- intermediate values and state needed to explain the next decision;
- complete error chains and stack traces when the runtime supports them;
- a final success or failure marker tied to the acceptance criteria.

Prefer existing structured logging; otherwise use a consistent, searchable format. High volume and duplication are acceptable. Never log credentials, tokens, private keys, secret values, or sensitive payloads; log safe identifiers, key names, lengths, hashes, or redacted representations instead.

## Repair a failed POC from its logs

When the user reports a POC bug or a failed validation run, preserve the existing acceptance contract and trimmed scope. Read the complete logs for the failed run before changing code. Correlate them by run and resource identifiers, reconstruct the ordered execution, and compare each observed step with the accepted happy path.

Apply every implementation rule in this skill to the repair itself. Optimize only for restoring the accepted scenario: do not add ordinary tests, comments, documentation, general review, refactoring, cleanup, defensive handling, maintainability work, or behavior outside the happy path. Keep maximum diagnostic logging, validate with only the same minimal integration or environment scenario, and run the independent diagnostic subagent audit after the final fix.

Locate the earliest observable divergence between expected and actual execution. Trace that point into the responsible code and its direct callers or external boundary. Distinguish the root fault from later symptoms, and state the log evidence that supports the diagnosis before editing.

- If the logs identify the fault, make the smallest code change that restores the accepted path.
- If the logs stop before the fault can be located, add the smallest additional high-visibility logging around the unresolved interval, rerun or ask the user to rerun the same scenario in its validation environment, then diagnose from the new logs. Do not guess a code fix when the existing evidence cannot distinguish the cause.
- If the failure reveals that the acceptance contract or trimmed design is wrong, stop the affected repair and obtain the user's explicit confirmation of the revised **Do**, **Do not**, or **Modify** entry before changing behavior.

Do not broaden the repair into production hardening or handle a new corner case unless it occurs in the confirmed acceptance scenario. After every fix, rerun only the same minimal integration or environment validation and inspect the new logs through the final acceptance marker. The independent diagnostic audit must cover the final repaired code and logs.

## Validate only the acceptance happy path

After implementation, add the smallest integration or end-to-end check that executes the user's exact acceptance scenario and asserts only its stated success evidence. Prefer the real validation environment and real owned components. Use the smallest substitute only when an external boundary is unavailable or unsafe, and disclose the substitution.

Run that check and inspect its actual exit status, observable result, and logs. Do not broaden validation when it passes. When it fails, use the logs to locate the failing step, make the smallest acceptance-path fix, and rerun only the invalidated check.

## Require one independent diagnostic audit

Once implementation and its integration check are complete, dispatch one independent read-only subagent that did not implement the POC. This is a targeted diagnosability audit, not a general code review.

Give it the confirmed acceptance contract, trimmed design, final diff, integration command and result, and produced logs. Require it to trace every accepted-path step and every operation that can fail and determine whether the logs expose the inputs, decisions, state transitions, external results, errors, and final outcome needed to locate a failure. It must report concrete blind spots with code-path evidence and must not edit files.

Fix every blind spot that could prevent diagnosis of the accepted scenario, rerun the integration check, and ask the same subagent to re-check the affected path. If no independent subagent is available, report the diagnostic audit as blocked and do not claim the POC has completed this workflow.

## Hand off the POC

Report concisely:

1. the confirmed acceptance scenario and whether it passed;
2. the implemented files and shortest runtime path;
3. the exact integration command, environment, observable result, and log location;
4. the diagnostic subagent's result and any fixed blind spots;
5. the deliberate shortcuts, excluded design goals, and why the result must not be treated as production-ready.

Do not claim behavior outside the single validated scenario.

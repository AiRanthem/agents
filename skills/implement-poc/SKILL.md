---
name: implement-poc
description: Build or repair the smallest verifiable proof of concept from a confirmed design. Use for fast feasibility evidence or to restore a failed POC. Confirm one acceptance scenario, trim the design to that path, diagnose failures from runtime evidence and validate that scenario. Exclude unconfirmed design exploration, production implementation, hardening and review-only work.
---

# Implement POC

Produce the fastest runnable proof that the user's explicit acceptance scenario can work, or restore that proof when a POC run fails. The result is disposable POC code with enough runtime visibility to locate and fix faults in that scenario from logs. It is not production-ready implementation.

## Project workitems

For a project work item, read its complete requirement and design and the original project and source instructions. Use the actual source location. In execution, record the confirmed POC scope and actual result in the existing project context and metadata. Commit and push authorized project-record changes under [project publication](../manage-workitems/references/persistence.md). POC success proves only its accepted scenario and does not establish production delivery.

## Respect authority and host mode

- Follow user, harness, and higher-priority instructions, including permissions, security and data-protection boundaries, and safeguards for destructive or external actions. A POC does not expand authorization.
- **read-only planning mode** applies only when active host instructions explicitly establish read-only planning mode. It is read-only: settle the acceptance contract and trimmed implementation or repair design, then return that design as the host's single final plan.
- **execution mode** is normal operation outside read-only planning restrictions. After the user confirms the acceptance contract and trimmed design, implement it directly without another planning phase.
- Preserve unrelated and pre-existing work. Keep POC design, task and review artifacts out of the repository. Use the existing project records described above when applicable.

## Require an explicit acceptance contract

Do not trim the design, publish a final plan, or edit code until the user explicitly confirms concrete POC acceptance criteria. Silence, timeout, an inferred goal, or a broad request such as “prove the design” is not acceptance.

Acceptance criteria must make one runnable scenario unambiguous:

- the required environment and starting state;
- the exact input or actions that exercise the POC;
- the observable output, state transition, or external effect that constitutes success;
- any evidence the user expects to inspect, including required log evidence.

When criteria are missing or ambiguous, inspect the design and relevant current code first, then propose the smallest concrete acceptance scenario for confirmation. Continue independent read-only investigation while waiting, but do not make dependent choices.

## Trim the design with the user

Read the complete confirmed design and trace the current code only far enough to understand the accepted scenario and its callers. Use the design and review evidence to explain what the POC can prove. For a new POC, define how the current code will become runnable for that scenario. When resuming or repairing an existing POC, reuse the confirmed acceptance criteria and trimmed design while they still apply.

For a new or materially changed trim, present three explicit groups and obtain confirmation before producing the final plan or editing affected code:

- **Do:** only the design goals and behavior required for the acceptance happy path.
- **Do not:** goals outside the confirmed acceptance scope, production rollout, and unrelated defensive, compatibility, recovery, cleanup, cancellation, concurrency or quality work. Preserve any behavior in these areas that the accepted scenario requires for correctness, security, readability or maintainability.
- **Modify:** any approved design behavior that must be simplified, hard-coded, bypassed, or replaced for this POC.

The trimmed design must identify the shortest concrete execution path, affected components and ownership boundaries, required data flow or interface shape, environment assumptions, shortcuts, runtime observability, and the minimal integration check. Resolve every choice that could change the accepted scenario. The user's confirmation of the concrete trimmed design authorizes its in-scope implementation; it does not authorize unrelated changes or external effects.

Keep the trimmed design only in the conversation or host-managed plan. Never write it to a repository file.

## Produce the mode-specific result

- **read-only planning mode:** Put the confirmed acceptance contract and trimmed implementation or repair design directly in the final plan. For a failed POC, include the failure point supported by runtime evidence and the proposed repair. Include ordered implementation actions, the minimal happy-path integration check, required diagnostic logging, and the final diagnostic subagent audit. Tell the executor to load `$implement-poc` and execute this confirmed plan in execution mode. Then stop without repository writes or implementation claims.
- **execution mode:** Implement the confirmed trimmed design immediately. When resuming a plan, load `$implement-poc`, verify that the acceptance environment and relevant code assumptions still hold, and proceed. Seek renewed confirmation only when new evidence changes the acceptance contract or trimmed design.

## Optimize only for time to acceptance

Choose a direct implementation that demonstrates the accepted scenario while keeping its path readable and maintainable. Prefer an existing simple path; use hard-coded values or a narrow bypass only when they keep the code understandable and preserve correctness and security. Trim behavior and verification to the confirmed POC scope; do not add production features or unrelated hardening.

- Do not write unit, component, regression, negative, boundary, compatibility, concurrency, or recovery tests.
- Avoid comments and documentation unless they explain a deliberate shortcut, invariant or safe use of the POC.
- Avoid broad review, refactoring, cleanup, and formatting churn unrelated to the accepted scope or its quality.
- Add no defensive behavior or corner-case handling beyond what the accepted environment and happy path actually exercise.

Keep POC-specific limits within the accepted scope while following governing code-quality, security and authorization requirements.

## Make the accepted path reconstructable from logs

Instrument the POC so a reader with the source and logs can reconstruct the accepted execution from entry to completion or failure without attaching a debugger.

For every step and failure boundary on the accepted path, log enough context to connect the full run:

- a run or correlation identifier and the relevant resource identifiers;
- startup assumptions and effective configuration needed to explain behavior;
- entry and exit of each phase, branch decisions, state transitions, and elapsed time;
- external calls or commands, their destination, safe diagnostic inputs and outputs, returned status, and errors;
- intermediate values and state needed to explain the next decision;
- error chains and stack traces when available, with sensitive detail removed;
- a final success or failure marker tied to the acceptance criteria.

Prefer existing structured logging. Allowlist the diagnostic fields and values needed for this scenario. Keep credentials and sensitive payloads out of logs. Redact sensitive details from configuration, error messages, stack traces and external output before logging. Use safe identifiers and summaries to retain the diagnostic signal.

## Repair a failed POC from runtime evidence

Read the available logs for the failed run before changing code. Correlate them by run and resource identifiers, reconstruct the execution and compare the observed steps with the accepted scenario. For startup failures or missing application logs, inspect available scheduling, launch, exit or log collection evidence. Locate the earliest observable divergence, trace it to the owning code or external boundary and distinguish the root fault from later symptoms.

- When runtime evidence identifies the fault, state that evidence and repair the owning path within the confirmed acceptance and trimmed scope.
- When the cause is unclear, collect the evidence that distinguishes the remaining explanations. Add focused logging only if the unresolved interval is in a path the POC can instrument. Rerun the same scenario if authorized and possible. If the validation environment is unavailable, request the specific run or evidence needed.
- If the failure requires a material change to the acceptance criteria or trimmed design, obtain the user's confirmation of the affected change before editing that behavior.

After repair, run the acceptance validation and diagnostic audit below on the repaired state. Keep the repair within the confirmed scenario.

## Validate only the acceptance happy path

Use the smallest integration or end-to-end check that runs the user's exact acceptance scenario and verifies its stated success evidence. Reuse an existing check or runnable validation steps when they cover that scenario. Add a check only when needed for coverage. Prefer the real validation environment and real owned components. Use the smallest substitute only when an external boundary is unavailable or unsafe, and disclose the substitution.

Run that check and inspect its actual exit status, observable result, and logs. Do not broaden validation when it passes. If it fails, apply the runtime-evidence repair process above and rerun the affected check after repair.

## Require one independent diagnostic audit

Once implementation and its integration check are complete, dispatch one independent read-only subagent that did not implement the POC. Apply [shared-context preparation](../../references/delegation-context.md) and use clean reviewer context. This is a targeted diagnosability audit, not a general code review.

Give it the confirmed acceptance contract, trimmed design, final diff, integration command and result, and the relevant logs. Remove sensitive details before sharing this evidence. Require it to trace every accepted-path step and every operation that can fail and determine whether the logs expose the inputs, decisions, state transitions, external results, errors, and final outcome needed to locate a failure. It must report concrete blind spots with code-path evidence and must not edit files.

Fix every blind spot that could prevent diagnosis of the accepted scenario, rerun the integration check, and ask the same subagent to re-check the affected path. If no independent subagent is available, report the diagnostic audit as blocked and do not claim the POC has completed this workflow.

## Hand off the POC

Keep the handoff concise and understandable without the earlier discussion. Include the following.

1. the confirmed acceptance scenario and whether it passed;
2. the implemented files and shortest runtime path;
3. the exact integration command, environment, observable result, and log location;
4. the diagnostic subagent's result and any fixed blind spots;
5. the deliberate shortcuts, excluded design goals, and why the result must not be treated as production-ready.

Do not claim behavior outside the single validated scenario.

# Implementable criteria

Use this standard for explore-design's completeness reflection and review-design's independent assessment. Apply the attribution, severity and Pass principles of the [implementation review standard](../../review-implementation/references/review-standard.md) to the design being reviewed; its code-specific execution gates remain with implementation review. Pass means adequate review found no blocking problem introduced by the proposed change, including an unmet requirement assigned to it. It does not require zero findings or a defect-free design.

## Scope and evidence

Identify the approved requirements, current design and task's established integration baseline or existing system. An earlier revision of this same proposal is not a baseline that turns its unresolved defects into pre-existing warnings. Review the affected outcome/scope, end-to-end behavior, failure/lifecycle, safety/compatibility, feasibility/dependencies, observable acceptance and implementation cost at a depth justified by the change. These are coverage dimensions, not separate certification gates. Keep the coverage mapping private; report material findings, essential gaps and relevant evidence without requiring a per-row proof table or new spec sections.

Attribute each candidate before assigning acceptance impact:

- **Introduced or assigned to this change:** Show new faulty behavior, an incremental regression, or an unmet explicit requirement assigned to this design. For an existing problem made worse or newly reachable, report only the added impact and causal link.
- **Pre-existing:** A baseline problem with no demonstrated new impact is a separate warning. It does not affect Pass, require a waiver or become a mandatory fix for this change, regardless of severity. If fixing it is an explicit requirement of this change, assess that unmet requirement instead.
- **Attribution unresolved:** State the uncertainty and investigate when it could materially affect this change. Only a concrete gap in essential assessment can prevent Pass; an unrelated unknown cannot.

For each retained finding, establish severity, location, trigger, expected versus proposed behavior, consequence, violated requirement or repository rule, evidence of introduction, and meaningful uncertainty. Trace the relevant path and try to disprove it against surrounding safeguards; merge duplicate symptoms under the supported cause. A concern about a possible bad implementation is not a design defect when the contract already defines the correct outcome and feasible internal choices remain available.

## Severity and acceptance impact

Apply severity only to introduced or assigned findings, using the same scale as implementation review:

| Severity | Design impact | Review consequence |
| --- | --- | --- |
| Critical | Likely security compromise, data loss or broad outage. | Blocks Pass. |
| High | Missing or incorrect required behavior, unintended scope, serious regression or an infeasible essential promise. | Blocks Pass. |
| Medium | A realistic design defect or substantial maintainability problem. | Normally fix before Pass; an exception needs explicit user acceptance and must not violate a governing requirement. |
| Low | A supported non-blocking improvement. | May remain with Pass; keep these few. No waiver, spec edit or re-review is required. |

Do not report cosmetic preferences or speculative risks. Private helpers, file layout, pseudocode, test commands, rollout procedures, missing reflection paperwork and opportunities to further optimize an adequate design do not by themselves block Pass. Required public/stored contracts, safety guarantees and consequential behavior must still be settled; do not disguise those gaps as implementation details. Existing authoritative requirements can establish an outcome without repeating it in every spec section. Do not require implementation or production validation merely to approve a design; seek focused evidence for a genuinely uncertain essential capability.

A necessary user decision or essential evidence gap is not a demonstrated defect. Explain the exact missing input and why a consequential conclusion depends on it. Ordinary implementation choices and nonessential uncertainty remain compatible with Pass. Preserve approved limitations consistent with governing requirements; neither author nor reviewer may waive a required guarantee.

Consolidate established blockers after reviewing the available scope. Re-review fixes and affected assumptions, preserving valid coverage. Do not reopen settled issues without new evidence or keep adding unrelated low-value comments after blockers are resolved.

## Verdict and official status

Return **Independent review passed** when adequate coverage and required independence found no blocking introduced or assigned problem and no essential assessment gap remains. Low findings, pre-existing warnings and implementation reminders may coexist with Pass. Return **Design changes required** for a concrete blocking finding; return **Unable to conclude** for a missing essential contract, stable target, independence, decision or evidence. If a blocker is demonstrated, report it and disclose additional gaps rather than hiding it behind uncertainty.

Bind the report to the exact requirement/design identity and source/dependency baseline. Separate blocking findings, non-blocking findings, baseline warnings and essential gaps as applicable; state the acceptance impact explicitly. A nonempty findings list is not a failed review. If only non-blocking issues remain, return `pass` and leave the candidate unchanged; do not turn optional polishing into `revised`, another approval request or another design-review round.

An independent quality pass is only one part of official `implementable` status. Recording that status also requires real user approval covering the unchanged current contract, valid reviewer/authorship and input bindings, and successful persistence through the active mode's authorized workflow. Follow [host modes](host-modes.md) or [project mode](project-mode.md); a stage executor returns its result to the controller and never writes official status. Native Plan never writes status.

Do not carry a pass across material changes to the contract or its assumptions. A revised version needs a valid independent assessment; reuse unaffected evidence with its applicability explained. A reviewer who helped revise the candidate cannot independently pass it. `Implementable` does not establish implementation authorization, prerequisite delivery, production correctness or human acceptance. Ordinary project implementation still requires actual predecessor delivery; authorized [predevelopment](../../advance-project/references/predevelopment.md) follows its frozen-input workflow and must be reconciled and reviewed after formal rebase.

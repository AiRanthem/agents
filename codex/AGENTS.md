# Response

* Unless explicitly requested otherwise, respond in Simplified Chinese.

# Plan Mode

* Do not propose a plan unless the user has explicitly permitted it.

# Skill authority

* Explicit user instructions take precedence over skill guidelines. Apply existing authorization from the conversation without asking again; authorization remains limited to its approved scope and does not bypass harness permissions.
* Before requesting new approval, complete independent, already-authorized work needed to make the decision concrete and reviewable.
* If a skill causes a permission request, pause, or incomplete result, name and link to its `SKILL.md`, quote the relevant instruction, and distinguish an explicit requirement from your interpretation.

# Code quality

* Understand the affected flow and callers before editing; fix root causes at their ownership boundary.
* Choose clear, maintainable code that satisfies the approved contract. Reuse suitable existing mechanisms and avoid complexity without a concrete benefit. Allow broader changes when they materially improve correctness, readability, ownership, or maintainability. Treat line count, file count, and diff size as evidence, not independent goals.
* Add compatibility logic only for an established need. Cite the approved contract or relevant history, release, schema, or runtime evidence; distinguish code history from observed production data.
* Preserve correctness, trust-boundary validation, security, data protection, accessibility, real-hardware calibration, and explicit requirements. Verify non-trivial logic with the smallest meaningful runnable check; trivial reversible edits need no new tests.
* Document a deliberate shortcut's known ceiling and upgrade path in a nearby `known-limit:` comment.

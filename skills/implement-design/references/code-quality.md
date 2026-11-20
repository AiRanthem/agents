# Code quality

Apply these criteria to the complete change against its integration baseline, including accumulated edits. Preserve the approved behavior, security boundaries and contracts that supported callers rely on.

- **Simplicity and ownership.** Prefer the smallest coherent change that remains clear and maintainable. Use the design, actual callers and existing repository patterns to judge whether branches, abstractions, dependencies, duplication or generated changes serve a purpose. Reuse suitable mechanisms and keep necessary refactoring. Line and file counts can help locate avoidable changes.
- **Readability.** Follow repository conventions for naming, placement and dependency direction. Keep control flow and responsibilities easy to trace. Comments should explain reasons, invariants and non-obvious failure or compatibility behavior. Ground compatibility logic in an approved requirement or concrete evidence of a supported caller, release, schema or runtime behavior.
- **Redundant guards.** Enforce each invariant at the boundary that owns it. A repeated check is redundant when every supported path already guarantees the condition and it still holds at the check site. Preserve checks that protect independent entry points or trust boundaries, or detect relevant state changes.
- **Production use.** Every production branch, API or helper must serve a supported runtime path or contract. Test coverage alone cannot establish production use. Exercise supported behavior through its entry points and keep helpers and fixtures used solely by tests in test code.
- **Dead code.** Confirm that code is unused or unreachable across supported configurations, runtime registrations and external callers. Trace those paths before drawing a conclusion from a search with no matches.

---
name: translate-design
description: Translate a stable Simplified Chinese design into a semantically equivalent English counterpart, usually after design freeze and before a pull request. Use for Chinese-to-English design translation or synchronization. Do not use for design exploration or changes, implementation, general translation, or English-to-Chinese translation.
---

# Translate Design

Take a stable Simplified Chinese design as input and output its natural English counterpart without changing the design contract. Treat the Chinese document as the source; preserve every decision, constraint, and status in English.

## Boundaries and authority

- Follow applicable user, repository, and harness instructions. Reuse established scope, paths, decisions, and authorization; do not ask again for information already available.
- If a request also changes the Chinese design, complete and exit that design work first. Translate only the resulting approved Chinese document; do not edit both languages concurrently under this skill.
- Read the Chinese design, applicable instructions, nearby document conventions, referenced repository evidence needed to understand project terminology, and any existing English counterpart.
- Do not reopen design decisions, add requirements, remove caveats, or repair the source while translating. Report a meaning-changing ambiguity or contradiction and obtain a source decision before translating that part.
- Write only the approved English design path. Do not modify the Chinese source, code, tasks, OpenSpec artifacts, ADRs, repository instructions, or unrelated documentation.
- Translation does not imply permission to commit, push, open a pull request, or edit its metadata. Perform those actions only when separately authorized.

## Confirm the translation target

Use the user-approved source and destination paths. If the destination is not specified, infer it only when repository conventions make one mapping unambiguous; otherwise obtain confirmation before writing.

- A source named `<base>-CN.md` maps to `<base>-EN.md` by default.
- Preserve an approved existing English path even when it does not follow the suffix convention. Do not rename either document merely to normalize filenames.
- Treat a frozen or otherwise approved Chinese design as the normal source. If the source is still a draft, translate it only when the user explicitly requests that, and preserve every draft marker and open question.
- When an English counterpart exists, update it in place. Preserve English-only metadata or formatting only when it does not conflict with the Chinese source or repository conventions.

## Translate the contract

Write natural technical English for the intended reviewers rather than a literal sentence-by-sentence rendering. Preserve the source's structure unless English readability or repository conventions require a local presentation adjustment.

- Keep every material decision, requirement, constraint, non-goal, accepted limitation, risk, open question, example, diagram, table, and status semantically equal.
- Preserve normative strength. Do not turn “必须” into “should,” a recommendation into a requirement, a possibility into a guarantee, or an unresolved choice into a decision.
- Keep ownership, trust boundaries, failure behavior, compatibility rules, state transitions, quantities, defaults, and conditions exact.
- Translate prose and reader-facing labels. Preserve identifiers, API names, field names, enum values, code, commands, paths, links, anchors, and branded terms unless the source or repository establishes an English form.
- Keep diagrams and tables structurally equivalent. Translate labels without changing edges, states, rows, columns, values, or ordering that carries meaning.
- Use consistent English terminology across the document. When a project term is ambiguous, prefer established repository usage supported by code or nearby English documents; report unresolved terms instead of inventing a contract.

## Validate and stop

Compare the completed English document directly with the Chinese source, not only with a previous translation.

- Check every heading and material paragraph, then compare tables, diagrams, examples, links, metadata, open questions, and document status separately.
- Confirm that no design content was added, omitted, weakened, strengthened, or resolved during translation.
- Run only narrow documentation checks relevant to the written file. Do not run application tests merely because a design document was translated.

Report the Chinese source path, English output path, source status, semantic comparison performed, and unresolved ambiguity. Do not claim the design was reviewed, approved, committed, pushed, or submitted as a pull request unless those actions were separately completed.

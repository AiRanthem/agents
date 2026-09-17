---
name: explain-design
description: Write a self-contained design explanation for technical experts unfamiliar with the repository, covering the problem, proposed behavior, decisions, and tradeoffs. Use to turn an established design into a readable, lasting introduction, in English unless another language is requested. Exclude design exploration, implementation, literal translation, and code walkthroughs.
---

# Explain Design

Write for a senior technical expert with limited time and no knowledge of this repository. The reader should understand why the change is needed, how the proposed system works, and why its consequential choices were made, with enough background to begin judging the change. The result is a lasting explanation of the design, not an abbreviated development specification.

The document must stand alone even if its input design is never published or is deleted. Write it in English unless the user explicitly requests another document language; the source and conversation language do not change that default.

## Authority and scope

User instructions take precedence over this skill's guidance. Reuse established scope, decisions, paths, and authorization. Write only the requested explanation; do not change the source design, code, or unrelated artifacts. Commit, push, and pull-request actions require separate authorization. Use the established destination or an unambiguous repository convention; ask when neither identifies the output.

Use confirmed design decisions from documents or conversation. Read code, history, and primary references when needed to understand background or verify facts. Distinguish design intent, observed behavior, and author rationale: implementation alone does not establish intent or reasons. Never invent motives, alternatives, guarantees, or delivery status. Report source-versus-implementation discrepancies separately from the article; do not turn them into an unapproved design correction, a bug verdict, or a temporary implementation-status section. If a discrepancy or missing reason prevents an accurate explanation of a consequential decision, ask and leave that part unfinished pending the answer. Decisions intentionally left open may remain open in the explanation.

## Choose the explanatory content

Compose an explanatory article from the problem and its causal story. Use the source's requirements to check correctness, not as a list of topics to reproduce. Establish what the system does for its users, the roles involved, and the meaning of the state or information they exchange. Component names alone do not supply that background.

Write at the level of system behavior and design reasoning. The reader needs to understand the solution and assess its tradeoffs, not reproduce its implementation or deployment. Translate a technical requirement into its consequence for that understanding; omit the requirement's operational form. A fact being precise, testable, security-related, or mandatory for an implementer does not by itself justify including it.

- Preserve the substance of consequential decisions and their supported rationale, including relevant alternatives, costs, assumptions, security and data-protection boundaries, compatibility effects, and failure outcomes. Explain the mechanism in terms of who interacts, what they exchange or decide, and how that produces the promised behavior. Do not reduce the article to goals and benefits.
- Leave out code organization, internal object ownership, algorithms at the helper or function level, startup/shutdown call sequences, test instructions, and operational recipes. Do not include code tours or move omitted implementation detail to an appendix.
- Express interfaces and configuration choices by their meaning, not their syntax: for example, which protection is enabled and what happens when it is absent, rather than the parameter that enables it. Omit ports, endpoint paths, field names, commands, status codes, and exact configuration settings. An identifier is warranted only when the change to that identifier itself is the subject, or when no plain description can distinguish the relevant behavior. Naming an endpoint or a setting in the source does not meet that exception.
- Retain a number when its magnitude is necessary to understand the promise or tradeoff, such as the length of a user's recovery window. Otherwise explain the qualitative consequence: an existing short deadline can cause a slow connection to fail. Do not enumerate retry counts, byte layouts, or validation checks just because they appear in the source. Do not invent a reason to justify retaining an arbitrary value.
- When a quantitative or conditional guarantee is necessary, preserve its subject, triggering event, scope, and exceptions exactly. A simpler sentence must not change when a guarantee starts, what it covers, or what happens on failure. Omit an irrelevant quantity rather than approximating it.

For example, suppose an import design lists validation functions and error codes, requires the entire import to be validated before any changes become visible, and gives the reason that partial imports are difficult for users to undo. Explain: "An import becomes visible only after all its entries have been checked. If any entry is invalid, none of the changes are applied, so users do not have to find and undo a partially imported dataset." The functions and codes add nothing to that explanation. Every causal explanation must be supported; a plausible reason is not evidence of a decision.

## Develop an understandable account

Open with a few paragraphs that establish the concrete situation, the problem, the principal change, and its benefit. Let later sections explain how it works and develop the important decisions and limitations. Choose the structure and length that the subject needs; use no fixed template or word count.

- Assume technical maturity, not local vocabulary. Introduce each necessary system role and project concept before relying on it. Use ordinary words and established technical terms, explaining specialized meanings in place. Avoid insider shorthand, invented labels, buzzwords, and compressed noun chains.
- Write complete sentences with clear actors, actions, conditions, and consequences. Give each paragraph one main point and enough connected explanation to support it. Reduce the reader's reconstruction work rather than minimizing words.
- Put a decision's reason and tradeoff near the decision. Develop the causal connection instead of appending a disconnected catalog of rejected options. Do not repeat the same rule under multiple headings.
- Use a concrete scenario when it clarifies behavior, without inventing an incident or additional promise. Use diagrams or tables only when they explain a relationship or comparison better than prose; they need not resemble the source's diagrams or tables.
- Preserve historical meaning: describe the baseline as the situation before this change, not as what the system does "currently." Keep temporary task labels, progress reports, code navigation, and review checklists out of the document. Mention a future reconsideration condition only if supported by the design.
- Put all necessary background, reasoning, and limitations in the article. Optional references may support claims but must not substitute for an explanation or require the original design to remain available.

## Check the actual document

Read the draft as a newcomer before comparing it with the source. Can the reader describe the roles, motivating problem, changed behavior, key reasons, and important limits without opening another document or code? If the article would mainly help someone configure, implement, or debug the system, rewrite it at the level of design meaning. Check every technical paragraph for its contribution to the explanation; remove operational inventories and concepts used before explanation, rather than merely shortening them.

Then check the retained claims against the evidence. Verify causal reasons and consequential guarantees, including their conditions and time origins. A paraphrase must preserve the actual required property: do not replace a broad constraint with one narrower way to satisfy it, or extend a local guarantee to the entire system. Ensure omissions do not hide a material tradeoff, security assumption, failure mode, or incompatibility. Keep unresolved factual questions out of claims of completion. Confirm the requested document language and that the explanation survives removal of the source and reorganization of incidental code.

## Independent review before delivery

After drafting and self-checking, delegate a content review to an independent subagent. Give the reviewer this skill, the draft, and the authoritative design materials and relevant evidence, without the author's self-assessment or intended verdict. The reviewer must apply the same explanatory purpose and content-selection criteria; independent review is not a demand to restore every omitted requirement.

The review must establish both newcomer comprehension and fidelity. Have the reviewer read the draft on its own first, then compare its claims and consequential omissions against the source. Findings need the affected passage, supporting evidence, and the impact on understanding or design meaning. Distinguish material defects from optional stylistic preferences. Review notes belong in the handoff, not in the article.

Resolve material findings, revise the document, and have the independent reviewer recheck the affected claims and surrounding explanation. Do not claim completion with unresolved material findings or substitute the author's own review for this gate. If independent delegation is unavailable, report the missing review explicitly rather than claiming it passed.

Run only relevant documentation checks. Report the output path, language, independent review outcome, checks actually performed, and any separately identified source discrepancy. Do not claim a review or validation that did not occur.

# Program-owned persistence

A completed checkpoint means the configured project Git ref and every enabled backend have verified the requested state. The program performs guarded publication, exclusive ownership, graph checks, durable external intent, readback and receipts. Agents use `begin`/returned `finish_command`; they do not assemble bundles, JSON mutations, Git commits or Aone requests for project records.

`published` ends a successful operation; `no_op` ends an unchanged operation without a commit or backend call. `partial` retains the same intent and returns the only resume command. For `blocked` with `code: stale_ticket`, execute only its returned `next_command` to begin again with current inputs. `blocked` with `code: stale_evidence` returns no `next_command` or `finish_command`; obtain current authorization/review evidence and report the blocker. Other blockers or missing input report the precise facts needed. Use these branches exactly; do not inspect remote refs, recompute receipts, choose a journal recovery path, blindly repeat uncertain creates or report a partial result as synchronized.

Ownership is published before implementation can begin. An uncertain external outcome retains its recovery identity and any required ownership. A new machine/session does not infer takeover from time, a missing local cache or an unchanged HEAD. Explicit handoff remains necessary within the program's gates.

Git holds full contracts and evidence. Optional Aone mirrors its managed projection. Unchanged source hashes and document bytes produce no churn. Code repositories have separate state and authorization: project metadata publication does not submit implementation code.

known-limit: Git and Aone do not share an atomic transaction, and Aone has no verified field CAS or server idempotency key. The program uses durable write-ahead intent and verified marker reconciliation; an uncertain outcome can remain blocked until an external fact is supplied.

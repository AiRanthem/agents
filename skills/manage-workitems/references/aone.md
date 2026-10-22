# Optional Aone mirror

The command workflow below governs ordinary synchronization. Script blockers or defects use the separate [user-authorized manual recovery](recovery.md#user-authorized-manual-recovery) contract. External writes need covering authorization, and uncertain creates require reconciliation before retrying.

Aone is enabled only by the selected project configuration. Git stores the complete requirement, spec and evidence; Aone mirrors the configured managed title, status, body and fields. Titles include `【项目名】`. Credentials remain outside project records.

At setup, select the actual existing space, type/category, required fields and status mapping. The adapter requires authenticated `a1`; unsupported mappings or missing identity are reported facts. Configuration alone is not a successful work-item synchronization.

Ordinary `begin`/`finish` publication and returned `resume` own all Aone discovery needed for execution, writes, readback, unknown-create reconciliation and receipts. Agents use the returned commands while the program invokes `a1`, builds projection bodies, maintains receipts and chooses recovery. A managed-field conflict is reported with exact affected fields; preserve unrelated external fields and obtain the missing intended business fact before resolving the conflict.

The program persists intent before sending external operations and verifies normalized readback before success. It searches an uncertain creation by stable project/item marker and adopts only an unambiguous verified match. An absent or ambiguous match remains unresolved and blocks another creation. Git links identify the business revision without a receipt-to-body update loop.

The adapter treats `update --status` as a workflow transition. When fresh readback already has the target status, it omits that option while updating the other managed fields. A rejected transition does not establish that any bundled field was updated; every successful update still requires complete readback verification.

In ordinary synchronization, only `published` or `no_op` completes the checkpoint. `partial` permits only the returned resume command. For `status: blocked` with `code: stale_ticket`, execute only the returned `next_command`; `status: blocked` with `code: stale_evidence` has no continuation command and requires current authorization/review evidence. Otherwise report its listed blockers or missing facts. See [commands](commands.md) for the fixed branch.

known-limit: this adapter has no verified Aone server idempotency key or atomic Git+Aone transaction. Durable intents, marker reconciliation and readback bound serial retries; an unknown creation or changed external field may require an actual external fact before progress.

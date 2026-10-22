# Optional Aone mirror

The command-only and stop/retry rules below describe ordinary synchronization. Script blockers may use [user-authorized manual recovery](recovery.md#user-authorized-manual-recovery) for concrete approved file/state correction and script repair, including direct readback of actual external facts. External writes still need covering authorization; reconcile uncertain creates before retrying.

Aone is enabled only by the selected project configuration. Git stores the complete requirement, spec and evidence; Aone mirrors the configured managed title, status, body and fields. Titles include `【项目名】`. Credentials remain outside project records.

At setup, select the actual existing space, type/category, required fields and status mapping. The adapter requires authenticated `a1`; unsupported mappings or missing identity are reported facts. Configuration alone is not a successful work-item synchronization.

Ordinary `begin`/`finish` publication and returned `resume` own all Aone discovery needed for execution, writes, readback, unknown-create reconciliation and receipts. Agents do not manually invoke `a1`, build projection bodies, inspect receipts or choose recovery. A managed-field conflict is reported with exact affected fields; preserve unrelated external fields and obtain the missing intended business fact rather than declaring a winner.

The program persists intent before sending external operations and verifies normalized readback before success. It searches an uncertain creation by stable project/item marker and adopts only an unambiguous verified match. An absent or ambiguous match remains unresolved instead of creating another item. Git links identify the business revision without a receipt-to-body update loop.

The adapter treats `update --status` as a workflow transition. When fresh readback already has the target status, it omits that option while updating the other managed fields. A rejected transition does not establish that any bundled field was updated; every successful update still requires complete readback verification.

Only `published` or `no_op` completes the checkpoint. `partial` permits only the returned resume command. For `status: blocked` with `code: stale_ticket`, execute only the returned `next_command`; `status: blocked` with `code: stale_evidence` has no continuation command and requires current authorization/review evidence. Otherwise report its listed blockers or missing facts. See [commands](commands.md) for the fixed branch.

known-limit: no verified Aone server idempotency key, field CAS or atomic Git+Aone transaction exists in this adapter. Durable intents and marker reconciliation bound retries; simultaneous manual changes or an unknown create may require an external fact before progress.

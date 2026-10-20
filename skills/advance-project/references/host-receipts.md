# Assemble controller-captured host receipts

Read this through the active host adapter when dispatching or collecting an autonomous stage. The helper assembles real tool data and validates the existing runtime receipt contract. It does not call the host, discover worker identity, infer liveness, or sign a host attestation.

Save the unchanged actual native arguments and returned result as JSON in a controller-owned regular file. When the client exposes the result programmatically, write that value directly instead of retyping it. Preserve the native worker identity; a targeted follow-up with an empty return may retain its actual arguments.target. Do not fill missing execution, completion, call IDs or model information. Do not read private transcripts to obtain it.

Run with the workspace Python and physical dev-kit root. For a spawn or wake receipt:

```sh
<PYTHON> <dev-kit>/scripts/host_agents.py receipt --host codex \
  --tool collaboration.followup_task --worker-id /root/stage_worker \
  --raw-file <canonical-stage-dir>/native-start.json \
  --output <canonical-stage-dir>/spawn-receipt.json
```

For a real terminal result, use the complete accepted ready dispatch to derive worker, attempt, role and input_binding exactly:

```sh
<PYTHON> <dev-kit>/scripts/host_agents.py receipt --host codex \
  --tool collaboration.list_agents \
  --raw-file <canonical-stage-dir>/native-terminal.json \
  --dispatch-file <canonical-stage-dir>/accepted-dispatch.json \
  --terminal-status completed --descendants-stopped --outcome pass \
  --report-file <canonical-stage-dir>/report.md \
  --output <canonical-stage-dir>/terminal-receipt.json
```

Use the actual host and tool names; Cursor uses its real Task/Agent lifecycle tools. `--descendants-stopped` is the controller's assertion after checking the real task tree, not a flag to infer cleanup. Failed/stopped executors may only return blocked. Substantive revised designs require `--candidate-file`. For an independent design reviewer’s mechanical correction of an authorized approved candidate, preserve actual `--outcome pass` and supply `--candidate-file`, `--mechanical-correction` and `--contract-unchanged`; the assembler carries `mechanical_correction: true` and `contract_unchanged: true` into the receipt. Record the exact diff, determining evidence and final candidate identity; this correction preserves independence from the original substantive authors and needs no new reviewer. `--contract-unchanged` requires the actual independent reviewer’s confirmation, never a controller-invented assertion. Include `--call-id` only when directly observable.

The assembler rejects explicit tool errors, mismatched workers, incomplete/paused dispatches, terminal claims without matching lifecycle evidence, missing cleanup, symlink paths and existing output files. Codex spawn, follow-up, message and interrupt calls establish no worker termination; collect an actual lifecycle query or wait result. It preserves raw data unchanged and reports only the saved path/hash, avoiding a second full payload in tool output. Pass its output file to the existing autonomy dispatch/result command; runtime current-input and independence checks remain authoritative.

known-limit: clients without a direct tool-output capture API still require the controller to save the actual raw result. The assembler removes repeated binding transcription, not this trust boundary; a native signed capture API can replace it when available.

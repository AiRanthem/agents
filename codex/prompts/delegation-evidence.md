# Shared evidence and judgment

Give each concrete check one execution owner in the task tree. Share target, command/cwd, relevant environment, status (`running`, `passed`, `failed`, `stale`) and accessible raw output. Wait for a running owner's result by default. Reuse completed results after checking scope, inputs, exit status and logs. Add checks for an uncovered risk, invalidated result or inaccessible evidence. After fixes, recheck affected scope/inputs and shared assumptions; a whole-tree fingerprint change alone does not invalidate all coverage.

Share facts, navigation and check results. The lead inspects critical code, test oracles and the necessary complete contract; quality and specialist reviewers focus on assigned boundaries. Avoid duplicating whole investigations or test runs, or assigning every executor a verifier. Fill essential evidence gaps and stop verification once acceptance is met.

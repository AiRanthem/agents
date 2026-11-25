# Shared evidence and judgment

Give each concrete check one execution owner in the task tree. Share the target, command, working directory, relevant environment, status (`running`, `passed`, `failed`, `stale`) and accessible raw output. Wait for a running owner's result by default. Before reusing a result, check its scope, inputs, exit status and logs.

Add checks for uncovered risks, invalidated results or inaccessible evidence. After a fix, recheck affected scope, inputs and shared assumptions. Retain coverage that still applies when the whole-tree fingerprint changes.

Share facts, navigation and check results. The lead inspects critical code, test oracles and the necessary complete contract; quality and specialist reviewers focus on assigned boundaries. Avoid duplicating whole investigations or test runs, or assigning every executor a verifier. Fill essential evidence gaps and stop verification once acceptance is met.

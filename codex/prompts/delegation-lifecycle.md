# Handoff and task lifecycle

Return one compact, self-contained handoff the recipient can use without reading progress updates. Include the identities of the inputs and outputs, key findings with original locations, check status and output locations, unresolved gaps and the next action. Keep large logs, source extracts and intermediate state in accessible disposable artifacts outside formal source documentation.

Consolidate settled updates to the same executor, communicate material changes promptly and request interim updates only for a decision or blocker. Use a new turn to resume a completed agent.

Close completed threads when supported, preserving results first. At capacity, reclaim completed threads or reuse a suitable executor within its scope and role; otherwise continue useful work or wait for relevant running work. Report a blocked required gate when eligible direct work is exhausted. Do not retry spawning without changed capacity. Use event-driven waiting within progress-update requirements; a timeout alone creates no new task or polling need.

Briefly report dispatched or reassigned tasks and why they were delegated. For main-agent dispatches and reassignments, include the selected model and reasoning effort, why they suit the task, and which settings were inherited or defaulted when their values are unavailable. Do not inspect subagent runtime settings or claim capabilities that did not run.

When an existing update discusses a result, end the line with its disposition, e.g. `[sample 直接采用]`. Use the child's task name and one of 直接采用 (used after verification), 补正 (substantive correction requested), 修正后采用 (used after correction), 未采用 (discarded), or 任务失效 (superseded). For distinct new work on the same child, mark the existing reassignment update before dispatch, e.g. `[sample#schema 新任务]`. Give the suffix a fresh task name and reuse the full key in later feedback. Several marks can share a line. Skip feedback that would require an extra update or tool call.

# Project publication

Write project documents, metadata and configuration directly at their final paths. Commit the task's related changes together, including only authorized edits within shared files. Preserve unrelated edits, staged changes and existing source work.

Resolve the exact destination under the repository's remote and branch mapping. Before a normal push, verify that every commit and change the destination would gain is within publication scope, including earlier local commits. If unrelated history is present, preserve it locally and prepare only the authorized changes against the verified destination when they can be separated safely. Project-record publication does not authorize source submission, deployment, messaging or deletion.

A failed commit or push leaves the files and local commits available for [recovery](recovery.md). After concurrent updates, reconcile with the published records and verify the combined hierarchy and dependencies even when Git merges cleanly. If another item already published the proposed sibling code, keep its identity and reassign only unpublished IDs, updating descendants, paths and references together before retrying. Check the destination first if the earlier push outcome is uncertain. Preserve user work and use a normal push.

Use the published project item identity when creating its [external mirror](aone.md). Report Git publication and external synchronization separately. Preserve actual external IDs and unresolved outcomes so a later attempt does not duplicate work.

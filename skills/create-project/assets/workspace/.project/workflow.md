# Project workflow

Use the installed `manage-workitems/references/workflow.md` for the version 1 protocol. This file records only project-specific delivery conventions and constraints.

{{DELIVERY_CONVENTIONS}}

Dependencies form a DAG and must deliver before implementation. Readonly initial design is allowed earlier. After prerequisites deliver, refresh the code baseline and have the user start `review-design` in a fresh context. A current independent pass and a remotely persisted exclusive claim are required for implementation. Final implementation review uses a fresh subagent; user inspection and code submission follow. Delivery and local cleanup are separate states.

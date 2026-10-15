# Project workflow

Use the installed `manage-workitems/references/workflow.md` for the current project-management protocol. This file records project-specific delivery conventions and constraints, with the essential workflow entrypoints below.

{{DELIVERY_CONVENTIONS}}

Creation ends at metadata, necessary background and requirement skeletons. Record supplied requirements as `new` items with unresolved details; enter design only on an explicit user request.

Dependencies form a DAG and must deliver before implementation. Follow the shared workflow's design cadence: within the requested scope, align related contracts and complete stable item designs ahead of delivery, retaining explicit open decisions and dependency assumptions for uncertain items. After each item's prerequisites deliver, reconcile its design with their actual results, refresh the code baseline and have the user start `review-design` in a fresh context. Eligible independent items can be reviewed in parallel. A current independent pass and a remotely persisted exclusive claim are required for implementation. Final implementation review uses a fresh subagent; user inspection and code submission follow. Delivery and local cleanup are separate states.

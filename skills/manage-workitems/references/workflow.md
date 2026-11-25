# Project work and evidence

Maintain project records directly under the user's requested scope. Read the original documents, perform the authorized work, update current facts in place, then commit and push affected project files. See [persistence](persistence.md) and [schema](schema.md).

Creation captures supplied requirements and known acceptance/delivery obligations and ends there. Design work develops the complete current contract, decisions and tradeoffs. Record actual user decisions and unresolved consequential questions. Independent review assesses the actual design and source evidence with real reviewer attribution; an author's own checks are not an independent review.

Implementation follows the approved scope and repository instructions. Record actual code location, changes, meaningful verification and remaining work. Reuse useful source and applicable earlier review evidence, assessing changed behavior and affected interactions. An unmet prerequisite is a concrete task fact to resolve or report.

Human acceptance records the user's actual conclusion. Preserve their final code/design choices and align remaining descriptive text where requested. Acceptance, source publication and delivery remain separate facts.

Record delivery for outcomes actually established: source push, merge, release, deployment or observed end-to-end behavior. Keep incomplete obligations visible. A passing test or review does not establish these outcomes. Cleanup records authorized removals and actual recovery locations.

## Child work items

Create children when decomposition is authorized for outcomes that need separate scheduling, ownership or acceptance. The complete parent design must be approved and have passed independent review. Keep shared guarantees and failure boundaries in that design. Resolve consequential gaps with the design owner before creating children that depend on them.

Give each child a stable ID, a usable outcome, its inherited design and acceptance scenarios, and its actual prerequisites. Keep behavior that must ship together in one child and assign one source repository per development child. Record hierarchy and dependencies under the [schema](schema.md). Give any remaining integration work its own child. Mark the parent as an aggregate once the children cover its original acceptance criteria. The parent retains whole-system acceptance and its [source and recovery records](resource-lifecycle.md).

Publish the parent and child documents and metadata together. Report their IDs, titles, outcomes, dependencies, design paths and publication status. Each child's inherited contract proceeds to its own [design review](../../review-design/SKILL.md) within the authorized scope.

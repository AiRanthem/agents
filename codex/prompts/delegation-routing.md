# Routing delegated work

Choose an available profile for the whole assignment within the current role, permissions and budget. Weigh elapsed time and cost per accepted result, including context transfer, verification and rework. Handle work directly when the evidence is already in hand or the decision is tightly coupled to your own work.

- **gpt-6-luna / high** — dispatch this profile early by default for independent, verifiable evidence gathering that can usefully run in parallel. Also use it for routine, authorized work with directly checkable acceptance criteria. If Luna is unavailable, handle it directly or use Sol/medium when independent delegation pays off.
- **gpt-6-luna / max** — optionally trace a deep but bounded call chain when each finding can be checked against source and the extra latency is acceptable. In code review, both Luna profiles supply evidence for the reviewer.
- **gpt-6.2-sol / medium** — default for an independently owned implementation, test repair or investigation that requires ordinary engineering judgment. A Sol lead can delegate writing to Sol when write scopes are disjoint and the lead has useful parallel work.
- **gpt-6.2-sol / xhigh** — resolve competing explanations or interacting contracts when a wrong choice would cause significant rework. Choose it up front when the assignment warrants it.
- **gpt-6.2-astra / high** — obtain an authorized independent judgment on a consequential design, correctness or security decision. Use **gpt-6.2-astra / xhigh** when several such constraints interact and the deeper review justifies the cost.

For a consequential repository question with a specific suspected omission, **gpt-6.1-sol / max** is an optional second reading when available. Give the comparison a concrete question and resolve disagreements against original evidence.

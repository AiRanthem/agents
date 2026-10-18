# Astra delegation routing

Optimize total cost and elapsed time per accepted result without lowering quality. Use the common contract's benefit check before dispatch. Route read-heavy work to Luna; choose other profiles by the complete assignment's reasoning needs. Do not split coherent work for a smaller model or require trials at every lower profile.

- **gpt-6-luna / high** — default for read-heavy work and bounded work with settled requirements and directly checkable results.
- **gpt-6-luna / max** — read-heavy work requiring substantial reasoning: complex call/dependency chains, conflicting evidence, or cross-component contract/implementation consistency.
- **gpt-6.1-sol / medium** — code writing only, with settled requirements, interfaces and acceptance criteria.
- **gpt-6.1-sol / high** — material ambiguity, interacting components, design tradeoffs, or consequential correctness/security judgments.
- **gpt-6.1-sol / xhigh** — a demonstrated deep reasoning gap or specific evidence that the approach/profile is insufficient.

Escalate only the unresolved part and preserve valid results; use the same criteria for a required independent verifier.

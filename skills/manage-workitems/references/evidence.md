# Reusable context and evidence

Build context on demand. Do not scan an entire code repository at project creation or revalidate every evidence card at every session start. The aim is to reuse verified facts without inheriting stale assumptions or old review conclusions.

## Three levels

1. Project navigation: `project_context.py list`, `show` and `context` select item metadata and role-specific input paths. Filter and paginate before reading bodies. `.project/context.md` carries only overall background.
2. Repository/topic evidence: compact independent records under `evidence/` capture discovered entry points, contracts, ownership and important call relationships. Create only records likely to save repeated exploration.
3. Item handoff: current approval, affected assumptions, review identities, progress, verification coverage and next action. Read the selected full requirement/spec for decisions; a handoff never substitutes for them.

Local `.project-local/index.json` is derived and disposable. Its metadata membership/content identity detects added, removed and edited records. Rebuild stale/corrupt cache from canonical metadata; malformed canonical data is an error. It never establishes that a capability or item does not exist. Queries inspect metadata, not all Markdown or code. Source discovery falls back to targeted canonical files and repository search on a miss.

## Evidence card

`evidence/<id>.json` routes to a concise `evidence/<id>.md` body:

```json
{
  "id": "service-routing-entry",
  "repository": "service",
  "topic": "request routing",
  "summary": "Routing entry points and owner boundaries",
  "kind": "fact",
  "sources": [{"path": "src/router.go", "revision": "full-source-commit", "sha256": "source-content-sha256"}],
  "scope": "request dispatch in this source snapshot",
  "inputs": {"configuration": "relevant defaults and flags", "search_scope": ["src/"]},
  "body": "evidence/service-routing-entry.md"
}
```

Kinds are `fact`, `inference`, `search`, or `verification`. The body records the claim, relevant path/symbol or source ranges, source and input identity, coverage and known unknowns. Keep fact and inference distinct. Record commands and actual observed outcomes when needed to reproduce evidence; omit broad raw logs and secrets. Evidence body paths stay within `evidence/` and never escape through symlinks.

## Freshness is checked by the consumer

Do not store universal `valid`, `current`, or `passed` flags. Applicability depends on the consuming task's source, inputs and acceptance. Check only the relevant records actually reused.

- A positive local fact can be reused when its source and relevant inputs are unchanged and it covers the present question. Follow critical source pointers directly.
- A claim such as “all callers”, “no other path” or “only implementation” depends on the complete search universe. New files/callers/configuration can invalidate it even when known source hashes match. Re-run the bounded search when that universe changed or cannot be established.
- Dirty worktrees require identities for relevant tracked modifications, untracked source, configuration and dependency inputs. A matching HEAD alone is insufficient.
- A spec edit invalidates its applicable review pass. It need not invalidate unrelated source facts. A delivered prerequisite or rebase may invalidate assumptions without changing the spec text.
- Test evidence is reusable only for the same applicable code/input scope and acceptance. Distinguish unit checks, build, deployment and end-to-end results.

An independent reviewer starts with original requirements, current full spec and raw source entry pointers. It forms its own issue candidates before reading previous findings or conclusions. Prior reviews appear as deferred input paths, never default context summaries. Record reviewed spec/base/diff identities separately from source evidence.

Use separate records for concurrent investigations. When evidence conflicts, preserve both sources and resolve applicability; do not let last-writer-wins prose silently erase conflicting facts. The index is navigation, never an authority for design approval, absence, claim ownership or delivery.

# Local history replay

From the physical skill directory, choose a window by child creation time. The end is exclusive. For example, to examine the first half of a month in Shanghai time, run

```sh
python3 -B scripts/replay_history.py \
  --since 2026-11-01T00:00:00+08:00 --until 2026-11-16T00:00:00+08:00
```

The report groups first turns by actual model, reasoning effort and role ancestry. It shows indexed children, missing observations, token totals, terminal statuses, final items and median elapsed time among completed turns with timing. Inspect sample size and gaps before comparing groups. Add `--cases` for local parent, thread and turn IDs to locate the original delegation, returned evidence, later corrections and downstream acceptance. Keep that output local. A missing index, schema change or archive is a coverage gap. Check the available records when the gap affects the decision.

Supply current rates only when needed. Repeat `--rate MODEL INPUT CACHED OUTPUT MAX_INPUT` for each price schedule, giving USD per million tokens and the applicable maximum input per request (`any` for a verified flat price). Each group is priced under **each** supplied schedule. The matching model gives a list-price estimate for the stated service tier. Other columns reprice exactly the same tokens. The priced count excludes turns with cache writes or any request above the ceiling. Apply the provider's actual tier and cache-write rules separately for excluded cases. Cost includes measured interrupted turns. Medians and sums show their own priced population.

The script opens the local thread and turn indexes read-only. It follows spawn edges from user roots, marks a `project-*` role and its descendants as fixed, and labels unresolved ancestry as unknown. It reads plain rollouts or their `.zst` archives (using `zstd`), checks the physical thread ID and indexed start and end events, and uses the first turn's actual model and effort. It sums unique response usage and reconciles it with cumulative turn snapshots. Cached input is included in input and reasoning output is included in output. Open turns, truncated traces, and older traces without attributable response usage are reported as gaps.

The first-turn window includes follow-through of that turn after the creation cutoff. Later turns, descendants' own work and the lead's verification time need separate attribution for end-to-end economics. Record a parent-level outcome only after inspecting the original acceptance evidence. Check the coverage of the local indexes against available archives when completeness matters.

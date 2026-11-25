# Local history replay

From the physical skill directory, choose a window by child creation time. The end is exclusive. For example, to examine the first half of a month in Shanghai time, run

```sh
python3 -B scripts/replay_history.py \
  --since 2026-11-01T00:00:00+08:00 --until 2026-11-16T00:00:00+08:00
```

The default report describes all indexed child threads in the window, grouped by actual model and reasoning effort. It shows indexed children, missing observations, token totals, terminal statuses, final items and median elapsed time among completed turns with timing. Add `--cases` for local parent, thread and turn IDs to locate the original assignments and results. Keep that output local. A missing index, schema change or archive is a coverage gap.

For a routing comparison, examine the original assignments before choosing representative cases. Check which models the lead could choose, the task and permission boundaries, and the acceptance criteria. Repeat `--thread ID` for each comparable child in the window. The selection includes only the listed IDs. Report the selection criteria, population size and exclusions alongside any comparison. Unverified assignments contribute only to descriptive usage totals.

Supply current rates only when needed. Repeat `--rate MODEL INPUT CACHED OUTPUT MAX_INPUT` for each price schedule, giving USD per million tokens and the applicable maximum input per request (`any` for a verified flat price). Each group is priced under **each** supplied schedule. The matching model gives a list-price estimate for the stated service tier. Other columns reprice exactly the same tokens. The priced count excludes turns with cache writes or any request above the ceiling. Apply the provider's actual tier and cache-write rules separately for excluded cases. Cost includes measured interrupted turns. Medians and sums show their own priced population.

The script opens the thread and turn indexes read-only. It reads plain rollouts or their `.zst` archives (using `zstd`), checks the physical thread ID and indexed start and end events, and uses the first turn's actual model and effort. It sums unique response usage and reconciles it with cumulative turn snapshots. Cached input is included in input and reasoning output is included in output. Open turns, truncated traces, and older traces without attributable response usage are reported as gaps.

The first-turn window includes follow-through of that turn after the creation cutoff. Later turns, descendants' own work and the lead's verification time need separate attribution for end-to-end economics. Record a parent-level outcome only after inspecting the original acceptance evidence. Check the coverage of the local indexes against available archives when completeness matters.

## Delegation feedback

Add `--feedback` to read the selected children's parent rollouts locally. The window still selects children by creation time. The report follows those children through the latest recorded feedback, including later assignments on the same thread. Use `--cases` to locate each assignment and its latest feedback by zero-based ordinal in the parent rollout. Reports omit conversation text.

The parent can append a short mark to an existing update. Use the child's task name for its first assignment. When reusing it for distinct work, append a fresh key such as `[sample#schema 新任务]` to the reassignment update before dispatch. The next delivery to that child in the same parent turn confirms the new assignment. Marks in delivered instructions are also read when the transcript preserves their text. End a prose line with one or more unquoted marks, for example:

    两项证据都已用于结论。 [sample 直接采用] [sample#schema 修正后采用]

`补正` records a substantive correction request. The outcome stays unknown until the parent gives a disposition. A later `直接采用` for that key counts as `used_after_correction`. `未采用` records discarded work and `任务失效` records superseded work. Normal verification is compatible with direct use.

For the reported children, `assignments` counts initial assignments and explicitly identified new ones. `with_feedback` includes pending correction requests. The five `outcomes` are used, used after correction, unused, superseded and unknown; only nonzero counts appear. For the direct adoption rate divide `used` by the sum of `used`, `used_after_correction` and `unused`. Report unknown and superseded counts alongside it. The original token and duration groups still measure child first turns.

An unmarked historical follow-up can mean a correction or new work. It contributes a gap and is excluded from the count of distinct new assignments. Missing parent evidence leaves the initial assignment unknown. The decoder uses the recorded collaboration activity and parent-authored marks; unmarked prose can be checked manually. For a label accuracy check, sample marked assignments, inspect the parent's actual use or correction at the cited ordinal, and report matches over cases checked.

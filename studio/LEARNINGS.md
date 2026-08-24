# Studio Learnings

Append-only memory of mistakes made while creating songs, and the rules they
produced. **Consult at the start of every skill** (compose-brief,
generate-song, judge-quality); **append immediately** when the user corrects
us or something goes wrong unexpectedly — same turn, never deferred.

Entry format:

```markdown
### YYYY-MM-DD · <short-slug>
- Symptom: what went wrong (observable)
- Cause: why it happened
- Rule: one-line imperative for future sessions
```

Keep entries tight; when a rule appears three or more times in the skills
themselves, fold it into the skill text and prune the entry here.

---

### 2026-08-23 · silently-lost-background-job
- Symptom: a take sat "pending" forever while the GPU idled; the echoed job id read back as `unknown job`.
- Cause: two tool calls merged into one invocation — the background dispatch never registered.
- Rule: dispatch one background job per tool call; verify liveness (job readable + GPU busy + fresh files) before reporting any ETA.

### 2026-08-23 · trust-disk-not-tool-results
- Symptom: pipeline steps downstream of a write failed because the file never landed, even though an earlier tool result claimed success.
- Cause: a merged/dropped tool invocation lost the write while its output still looked plausible.
- Rule: verify artifacts exist NON-EMPTY on disk (list the session folder) before gating on them.

### 2026-08-23 · lyric-text-next-to-tag-is-lost
- Symptom: a lyric line that shared its line with a section tag never got sung.
- Cause: upstream normalization keeps only tags on tag-leading lines and drops the rest of that line — silently.
- Rule: section tags always sit on their own line; never join lyrics onto a `[Tag]` line.

### 2026-08-23 · byte-exact-reproducibility
- Symptom: "the same song" regenerated differently after tidying whitespace in caption/lyrics.
- Cause: prompt bytes seed the backbone KV cache; rewrites change audio even with the same seed.
- Rule: never "tidy" session artifacts between regeneration rounds; byte-identical inputs are the reproducibility contract.

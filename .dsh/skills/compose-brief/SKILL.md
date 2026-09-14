---
name: compose-brief
description: >
  Turn a user's music idea into the full pre-generation artifact set:
  brief.md (interview result), lyrics.txt (tagged lyrics), style.txt (short
  YuE2 style prompt) and caption.md (Music 3.0 Structured Caption). Also asks —
  ONCE per song — which music model to use (YuE2 by default). Includes the
  user-interaction protocol. Use at the start of every song session.
origin: >
  Interaction protocol adapted from MiniMax's MIT-licensed `minimax-music-gen`
  skill (oss/skills/, © 2026 MiniMax); caption expansion delegates to the
  official `music-caption-rewriter` skill documentation in oss/minimax-music3/.
---

# Skill: compose-brief

## Inputs

- The user's request: anything from a one-liner ("a sad piano piece") to a
  detailed spec. Vocal songs are in scope. **Instrumental-only is NOT supported**
  (neither model can do it) and covers are not possible locally — see Step 0.

## Outputs (create `studio/sessions/<song-id>/`, id = `YYYYMMDD-HHMMSS-<slug>`)

| Artifact | Content |
|---|---|
| `brief.md` | Full interview result: genre/subgenre, mood arc, BPM/key hints, vocal character, instrument list, production feel, references, exclusions |
| `model.json` | The music-model choice for this session, written by `scripts/select_model.py`. Never hand-edit; never re-ask once it exists |
| `lyrics.txt` | Final lyrics with Music 3 section tags: `[Intro]` `[Verse]` `[Pre-Chorus]` `[Chorus]` `[Post-Chorus]` `[Bridge]` `[Instrumental]` `[Solo]` `[Outro]`. **Completely empty (0 bytes) only when the user, after being told instrumentals are unsupported, chose to attempt one anyway** — it is a request that the model usually ignores, not a supported mode |
| `style.txt` | **YuE2's prompt**: ONE line, comma-separated — language, genre/subgenre, vocal character, 2–3 key instruments, tempo/feel. E.g. `English, warm piano pop, expressive lead voice, acoustic piano, rounded bass and light drums, lyrical melody, unhurried, 88 BPM`. No headings, no prose, no lyric text, no section tags. Needed in every session (the default model consumes it) |
| `caption.md` (+ `.json` on request) | Structured Caption produced via `$music-caption-rewriter`: Global Metadata / Vocal Details / Arrangement. Needed for MiniMax Music 3 takes |
| `caption.json` | Machine-readable twin of the caption for programmatic consumers. Schema: `{"source_skill": "music-caption-rewriter", "inputs": {"description": "<one-paragraph brief summary>", "lyrics_sections": ["[Verse]", "..."]}, "rewritten_caption": "<exact full text of caption.md>"}` |

Write **both** prompt artifacts from the same interview. They are not
interchangeable: `caption.md` is a 250–450-word music-3 document, `style.txt` is
the short descriptor prompt YuE2 was trained to read. Each model gets its own
native prompt — never feed one to the other.

## Step 0 — Detect intent

0. **Learnings check.** Skim `studio/learnings/LEARNINGS.md` first (gitignored;
   if missing, treat as empty); apply its rules
   throughout the interview and artifact writing.

1. Song category: **vocal** or **instrumental** — see the hard rule below.
2. Mode: **Basic** (clear one-liner → infer everything, confirm once) or
   **Advanced** (user wants control over lyrics/prompt/structure).

Ambiguity is resolved by asking, never by assuming silently.

### Instrumental requests: say this FIRST, before any other work

**Neither shipped model can generate instrumental-only audio.** This is settled,
not a prompting problem:

- **YuE2** (`yue2`, the default) requires `lyrics` upstream and has no
  instrumental mode — it refuses outright.
- **MiniMax Music 3** accepts an empty `lyrics.txt` and then **still sings**. The
  owner reports this across many attempts, and `studio/learnings/LEARNINGS.md`
  records three separate 2026-08-27 entries where successively stronger captions
  ("strictly instrumental" → repeated in every section → truly 0-byte lyrics with
  the words *singing*/*vocal line* removed) all still produced vocals.

So when the user asks for an instrumental, **before the interview, before the
model question, before any GPU time**, tell them plainly that neither model can do
it and offer the honest options:

1. **Render it anyway** — accept that vocals will very likely appear, and treat the
   take as an experiment rather than a deliverable.
2. **Make it a vocal song** — what both models are actually good at.
3. **Don't use this studio for it today** — no instrumental path exists. (The same
   audio.cpp runtime does expose other `gen` families — `stable_audio`, `ace_step`,
   `heartmula` — which are *unverified leads* for a future feature, not available
   now. See [plans/2026-09-14-instrumental-generation-unsupported.md](../../../plans/2026-09-14-instrumental-generation-unsupported.md).)

Never promise an instrumental, and never present a sung take as the instrumental
the user asked for. If they choose option 1, keep going with the 0-byte
`lyrics.txt` convention below, and expect `generate/v1` to carry a `warnings`
entry saying exactly this.

## Step 0b — Music model: ask ONCE, here, before writing any prompt artifact

The model is chosen at the start of the song and never asked again. **Do this
before Step 1** so the prompts match the model.

1. Create the session folder, then read the current state:

   ```bash
   python scripts/select_model.py --session studio/sessions/<song-id>
   ```

2. If `needs_choice` is `true`, ask the user **exactly one** question, with the
   default first and no follow-ups:

   | Option | Why they'd pick it |
   |---|---|
   | **YuE2 — default** (`yue2`) | Frontier quality (top open model on WildSongBench, ahead of MiniMax Music 3 and Suno v5), ~3× faster, ~11 GB VRAM, and it writes an editable melody+chord score. **Weights are CC BY-NC 4.0: personal/non-commercial use only.** Vocal songs only |
   | **MiniMax Music 3** (`minimax-music3`) | The previous default engine (audio.cpp Q8 GGUF), ~4 min per song. Pick it for commercially usable output, or to A/B against YuE2. **Also vocal songs only** — it has no instrumental mode either |

   One line of context for the user:
   *"Default is YuE2 (best quality, ~3× faster). Pick MiniMax Music 3 if you need
   commercially usable output — YuE2's weights are non-commercial."*

   Category comes from Step 0: **instrumental requests are already handled there**
   (neither model can do them), so do not offer instrumentals as a reason to pick a
   model — no model choice unlocks them.

3. Report availability honestly before they commit. The same command lists each
   model with `ready` (`true` = installed, `false` = missing, `null` = cannot
   probe, read `details.probe_error`) and `details.remedy`:
   - If the preferred model is not `true`, say so and name the remedy
     (`python scripts/setup_yue2.py`, or `python scripts/setup_audiocpp.py`).
   - Offer the ready alternative. **Never silently fall back** to a different
     model, and never let the user pick a model that cannot run without telling
     them what it will take to get there.

4. Record the answer (once):

   ```bash
   python scripts/select_model.py --session studio/sessions/<song-id> --model yue2
   ```

   `needs_choice` is then `false` for the rest of the session. If it is already
   `false`, **do not ask again** — carry on with the recorded model
   (`chosen.model`). To deliberately switch models later, pass `--force`; never
   do that silently.

Model choice is session state on purpose (plan 2026-09-13-yue2-default-model.md,
decision Y2): the studio never edits `configs/`, and each session stays faithful
to whatever actually produced its takes.

## Step 1 — Interview

Consult `oss/skills/skills/minimax-music-gen/references/prompt_guide.md`
(genre tables, vocal-style phrases, instrument vocabulary, BPM bands) while
asking. Minimum to elicit before writing `brief.md`:

- genre + subgenre blend, overall mood (and mood progression across sections)
- vocals: presence, gender/timbre character, delivery style — described as a
  *character*, never "female vocal"
- narrative/theme (vocal) or scene imagery (instrumental)
- 2–3 key instruments precisely; leave the rest to the model
- tempo feel; structure preference (offer verse-chorus default)
- lyrics language = user's language unless explicitly overridden; express
  foreign-language vocals through style descriptors ("K-pop", "Mandopop ballad")

Never reproduce copyrighted lyrics. Original lyrics only.

## Step 2 — Lyrics iteration (Advanced mode)

Iterative editing contract: "change the second chorus" rewrites only that
section. Show lyrics formatted with their section markers before moving on.

**Instrumental rule:** if the user chose to *attempt* an instrumental after the Step 0
warning, `lyrics.txt` must remain **completely empty (0 bytes)** — do not write any
section tags (`[Intro]`, `[Verse]`, etc.), placeholder text, or explanatory notes, and
do not try another caption formula: three escalating strategies already failed. Leave the
file empty, carry the `pure instrumental, no vocals` style prompt in the caption, and
tell the user up front that the model will probably sing anyway.

## Step 3 — Prompt artifacts (style.txt, then the Structured Caption)

### 3a — `style.txt` (YuE2's prompt — write this in EVERY session)

One line, comma-separated, no headings and no prose. Cover, in this order:
language · genre/subgenre (+ explicit fusion only if the user asked for one) ·
vocal character (as a *character*, never "female vocal"; omit entirely for
instrumentals) · 2–3 defining instruments · tempo/feel.

```
English, warm piano pop, expressive lead voice, acoustic piano, rounded bass and light drums, lyrical memorable melody, unhurried phrasing, 88 BPM
```

Rules:
- Keep it to roughly 15–40 words. This is a *descriptor list*, not a caption.
- **No lyric text, no section tags, no production prose, no bullet points.**
- Preserve the user's explicit constraints and exclusions verbatim (e.g.
  `no guitar`, `no EDM`).
- An attempt at an instrumental gets no vocal descriptor and says `instrumental`
  explicitly, but remember no model choice makes it work — the take will most
  likely still sing (Step 0).

### 3b — Structured Caption (`caption.md` + `caption.json`)

**Preferred path:** invoke `$music-caption-rewriter` with the brief as caption
input and `lyrics.txt` content as optional tagged lyrics. If the material is
not fetched yet (`oss/minimax-music3` missing), fetch it first with
`bash scripts/fetch_upstream.sh` (Windows: Git Bash, or
`wsl bash <repo-in-wsl>/scripts/fetch_upstream.sh`) — see also env-setup Step 3.
This must also fetch `oss/yue2`, which the same script pins.

**Manual fallback** (host agent has no `$music-caption-rewriter` installed —
the vendored checkout contains everything needed). Follow the upstream skill's
own instructions at
`oss/minimax-music3/skills/music-caption-rewriter/SKILL.md`, condensed:

1. Build a private brief from the interview (never expose it in the caption).
2. Route via `oss/minimax-music3/skills/music-caption-rewriter/references/genre-router.md`
   → pick ONE primary family (two only for an explicit fusion).
3. Open that family's `references/index-*.md` ONLY; select ≤3 template cards
   with distinct roles: Foundation (identity/groove), Modifier (one matched
   dimension), Arrangement (timeline logic).
4. Read ONLY those selected `templates/*.txt` files.
5. Synthesize a NEW caption — never copy sentences or full structures from
   templates; do not inherit their key/BPM/vocalist specifics.

Hard rules inherited from the upstream skill:

- Lyric text NEVER enters the caption; only bracketed section tags act as
  musical directives inside the Arrangement section.
- Preserve explicit musical constraints from the user verbatim; keep
  exclusions (e.g., "no EDM") even if a section tag suggests otherwise.
- Output exactly three headings — Global Metadata / Vocal Details /
  Arrangement (~250–450 words) — and run the upstream SKILL.md validation
  checklist before writing anything to disk.

Save the result to `caption.md` AND the machine-readable twin to
`caption.json` (schema in Outputs above).

## Step 4 — Preview-and-confirm gate (mandatory)

Show the user: the recorded **model** (from `model.json`), category, mode,
one-paragraph creative summary, the `style.txt` line, lyrics excerpt, caption
highlights. Generate nothing until the user confirms or requests edits. Loop
edits through Steps 1–3 as needed.

Before the gate, list the session folder and confirm artifacts on disk.
A merged or dropped tool invocation can silently lose a write — verify on disk
instead of trusting earlier tool results:
- **Vocal:** `brief.md`, `lyrics.txt`, `style.txt`, `caption.md`, `caption.json`
  all exist **non-empty**, and `model.json` records the chosen model.
- **Instrumental (attempted after the Step 0 warning):** `brief.md`, `style.txt`,
  `caption.md`, `caption.json` non-empty; `lyrics.txt` must exist and be
  **completely empty (0 bytes)**; `model.json` is recorded normally (either model —
  neither can actually deliver it). Re-confirm with the user that this take is
  expected to contain vocals before spending GPU time.

## Handoff

On confirmation, tell the user you are invoking `generate-song` with this
session folder. For a `yue2` session, mention that it will first show them the
**composition** (a ~19 s score-only pass) and only render audio once they approve
it — so they can judge the structure before paying for a full render. They can
say "just render it" to skip that gate.

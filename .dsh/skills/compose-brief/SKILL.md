---
name: compose-brief
description: >
  Turn a user's music idea into the full pre-generation artifact set:
  brief.md (interview result), lyrics.txt (tagged lyrics), caption.md
  (Music 3.0 Structured Caption). Includes the user-interaction protocol.
  Use at the start of every song session.
origin: >
  Interaction protocol adapted from MiniMax's MIT-licensed `minimax-music-gen`
  skill (oss/skills/, © 2026 MiniMax); caption expansion delegates to the
  official `music-caption-rewriter` skill documentation in oss/minimax-music3/.
---

# Skill: compose-brief

## Inputs

- The user's request: anything from a one-liner ("a sad piano piece") to a
  detailed spec. Instrumental and vocal songs are both in scope.
  Cover versions are NOT possible with local Music 3 — say so if asked.

## Outputs (create `studio/sessions/<song-id>/`, id = `YYYYMMDD-HHMMSS-<slug>`)

| Artifact | Content |
|---|---|
| `brief.md` | Full interview result: genre/subgenre, mood arc, BPM/key hints, vocal character, instrument list, production feel, references, exclusions |
| `lyrics.txt` | Final lyrics with Music 3 section tags: `[Intro]` `[Verse]` `[Pre-Chorus]` `[Chorus]` `[Post-Chorus]` `[Bridge]` `[Instrumental]` `[Solo]` `[Outro]`. Empty file + one-line note for instrumentals |
| `caption.md` (+ `.json` on request) | Structured Caption produced via `$music-caption-rewriter`: Global Metadata / Vocal Details / Arrangement |
| `caption.json` | Machine-readable twin of the caption for programmatic consumers. Schema: `{"source_skill": "music-caption-rewriter", "inputs": {"description": "<one-paragraph brief summary>", "lyrics_sections": ["[Verse]", "..."]}, "rewritten_caption": "<exact full text of caption.md>"}` |

## Step 0 — Detect intent

1. Song category: **vocal** or **instrumental** (cover → explain unsupported locally).
2. Mode: **Basic** (clear one-liner → infer everything, confirm once) or
   **Advanced** (user wants control over lyrics/prompt/structure).

Ambiguity is resolved by asking, never by assuming silently.

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

## Step 3 — Structured Caption

**Preferred path:** invoke `$music-caption-rewriter` with the brief as caption
input and `lyrics.txt` content as optional tagged lyrics. If the skill material
is not fetched yet, run env-setup Step 3 (`scripts/fetch_upstream.sh`) first.

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

Show the user: category, mode, one-paragraph creative summary, lyrics excerpt,
caption highlights. Generate nothing until the user confirms or requests
edits. Loop edits through Steps 1–3 as needed.

Before the gate, list the session folder and confirm all four artifacts
(`brief.md`, `lyrics.txt`, `caption.md`, `caption.json`) exist non-empty on
disk. A merged or dropped tool invocation can silently lose a write — verify
on disk instead of trusting earlier tool results.

## Handoff

On confirmation, tell the user you are invoking `generate-song` with this
session folder.

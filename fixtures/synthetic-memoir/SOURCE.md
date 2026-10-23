# Synthetic memoir with a planted answer key

`record.md` is a fictional memoir of 155,158 words: Ray Lacasse, an instrument technician from a mill town in northern Ontario, 1977–2023, in 30 chapters. Every person and place in it is invented. Claude Opus 5.5 wrote the odd chapters and Codex (gpt-6.1-sol) the even ones, each from a brief listing the episodes that chapter must show, through the harness's own locked call path, so a writer saw only its own brief. `key/key.json` says what the record holds, and it was sealed (sha256) before the harness read a word of it.

## What is planted

`eras.json` cuts the record into six eras of five chapters: e1 1977–83, e2 1984–89, e3 1989–95, e4 1995–2002, e5 2002–11, e6 2011–23. The harness's own era proposal cut at the same chapters unaided.

| Trait | Behaviour | Planted |
|---|---|---|
| T1 | lists, ledgers, labelled bins | every era |
| T2 | yields rather than confront | every era |
| T3 | reads to understand how things work | every era |
| T10 | checks what others claim | every era |
| T4 | physical daring | e1–e3, then absent (a fade) |
| T5 | seeks out groups | e1–e2, then absent (a fade) |
| T6 | gives money or time to people in need | absent e1–e3, then every era (an emergence) |
| T7 | sticks with hard goals | absent e1–e2, then every era (an emergence) |
| T8 | chosen prayer and church | e1–e2, then single passing mentions only |
| T9 | drinks to cope | e5 only |
| T0, N1 | absorption in music or art; worry | never shown |

On top of that:

- 54 hindsight sentences: 42 the zoner should remove (reflection from the time of writing) and 12 plain sentences that look like reflection and should stay.
- 3 traps: a later-era sentence claiming an old trait still holds.
- 3 sentinel terms that appear only in a late era and must never reach an earlier era's raters.
- `sealed/` holds a self-prediction and IPIP-NEO-120 answers built so the six firm rows of the three-way map land in all six of its classes.

## Result

One live run, harness v0.9.2, 2026-10-22: about 180 model calls and 3 h 20 min. `score.json` is the full score; `../../examples/synthetic-memoir/report.md` is the report.

| Check (pass mark, fixed before the run) | Result |
|---|---|
| Hindsight removed (≥ 95 %) and plain sentences kept (≥ 80 %) | 42/42 removed, 12/12 kept |
| Traps excluded (all) | 3/3 |
| Late-era terms kept out of earlier eras (all) | 3/3 |
| Stable traits seen in at least 5 of 6 eras (≥ 3 of 4) | 3/4: T2 reads as conflicting in e4–e6 |
| Fades and emergences at the right era (≥ 3 of 4) | 4/4 |
| Held, one-era and never-shown traits | as planted |
| Firm three-way rows (≥ 4 of 6) | 5/6: O5 reads divergent |

Agreement between the two model families: inductive α .833 (reportable), deductive α .787 (tentative), lenient deductive α .868.

## How it was scored

The raters build their own codebook, so the scorer first needs each construct mapped to a planted trait. Two mappings were made from the codebook definitions alone, before any result was read: one by Claude (`mappings/A.json`), one by a fresh Codex process (`mappings/B.json`). Only constructs both map identically count (33 of 79; 4 disputed). `scripts/score.py` applies `key/scoring.md`'s rules; `evidence/validation.json` gives each planted sentence's id in the harness's segmentation.

To rerun: `init` a workspace with `--text record.md`, run the first `prepare`, copy `eras.json` and `redactions.json` into its `prepare/`, finish `prepare`, copy `sealed/` in, then `seal`, `freeze`, `extract` and `unmask`. Map the new codebook's constructs to the traits above, then `python3 scripts/score.py <repo> <workspace> A.json B.json out.json`. A new run builds a new codebook, so expect different construct ids and slightly different numbers.

sha256 at sealing: `record.md` `bc908420e40c5fab…`, `key/key.json` `07588bb59d56fc9c…`, `key/scoring.md` `49e7534163f203d9…`.

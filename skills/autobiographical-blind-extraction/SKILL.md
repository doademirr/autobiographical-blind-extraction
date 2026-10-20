---
name: autobiographical-blind-extraction
description: Run a pre-registered, blind, two-lineage (Claude + Codex) trait extraction over the user's own diary or autobiography, and compare it with their sealed self-prediction and IPIP-NEO-120. Use when the user asks to run the blind extraction on their life record, diary or autobiography, or invokes this skill by name.
---

# Blind extraction from a life record

You drive `scripts/run.py` stage by stage for the user. The harness does every model call in clean-room processes
and computes every number; your job is to run the stages in order, stop at each review point, and relay what the
harness prints.

## Hard rules

- **Never open, read, list, grep or summarise anything under `<workspace>/sealed/`**, and never ask the user what
  they wrote there. The workspace's `.claude/settings.json` denies it; treat that as a rule, not an obstacle.
- Never paraphrase, edit or "clean up" the user's text, and never author predictions, codebook entries or any input
  the harness feeds to a rater.
- Do not interpret results beyond what `report/report.md` says. It is not a clinical assessment; say so if asked.
- Each model-calling stage prints a call estimate; tell the user before running it. Live runs use their Claude and
  Codex subscriptions.

## Stages

Run from the folder holding `scripts/run.py`. `<ws>` is the workspace; it must sit outside any git repository or
synced folder.

1. `python3 scripts/run.py init <ws> --text <file>... [--canary <term>...]`
   Canaries are words that only the user's own profile or instruction files would contain (a nickname, a test
   result). Ask the user for two or three; the leak probe checks no rater knows them.
2. `python3 scripts/run.py prepare <ws>` — the first run writes `prepare/redactions.json`, `prepare/eras.json` and
   `prepare/segments-preview.txt`, then stops. **Review point 1:** the user lists third-party names to replace
   (`"names": {"Full Name": "First L."}`), splits the record into eras by segment id, and sets `"approved": true` in
   both files. The user decides the eras, not you: help them find the breaks, never choose for them. The `"note"` in
   `eras.json` states the rule (at least 5-6 eras of at least 10k words each, under the estimated maximum; in order,
   back to back, every segment in exactly one; cut at life events such as a move, a new school or job, a
   relationship, a birth or death, a gap in the writing; never around traits the user expects), and the preview
   gives each paragraph's word count. Nothing leaves the machine before that. Run `prepare` again: it checks every
   era's size before any model call (exit 2 names an era that is too big and its maximum; split it), then qualifies
   both CLIs, zones the text and prints per-era kept ratios. **Review point 2:** ask the user to skim `prepare/retrospective.md` (what was
   removed) and a few eras of `prepare/substrate/` (what raters will see).
3. **Review point 3:** the user fills in `sealed/self-prediction.md` and answers `sealed/ipip-120.csv` (items are
   in `sealed/ipip-120-items.md`) in their own editor. Then `python3 scripts/run.py seal <ws>`.
4. `python3 scripts/run.py freeze <ws>` — pre-registers the method and substrate.
5. `python3 scripts/run.py extract <ws>` — about 45 calls. Exit 1 means a reliability gate fired: the run is still
   valid and the report will say which arm is not reportable.
6. `python3 scripts/run.py unmask <ws>` — the crosswalk, the IPIP reveal, then `report/report.md`.

`python3 scripts/run.py status <ws>` says where a workspace stands and what to run next.

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | stage done | next stage |
| 1 | a reliability gate fired | continue; the report states it |
| 2 | usage or preflight failure | read the message; fix and rerun |
| 3 | isolation or leak failure | stop; show the user the message; do not work around it |
| 4 | a frozen or sealed file changed | stop; a new run needs a new workspace |
| 5 | a model call failed | rerun the same stage; completed calls are reused |

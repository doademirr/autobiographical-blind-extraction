# Architecture

Updated: 19/10/2026

Stdlib-only Python ≥ 3.10. `scripts/run.py` is the CLI; `scripts/abx/` holds one module per stage plus the shared
layers below. `SPEC.md` is the contract this structure implements, less the requirements listed under its "Scope of this version".

## Layout

```
scripts/run.py              CLI: subcommands, exit codes, all printing
scripts/abx/                the harness package
prompts/*.md                role templates (# abx-role: <role>, {{slot}} placeholders)
schemas/*.json              output schemas, the JSON Schema subset in schema.py
instruments/ipip-neo-120.json   IPIP-NEO-120 items, facets and keys
fixtures/franklin/          public-domain excerpt, redactions, eras, synthetic comparators
skills/autobiographical-blind-extraction/SKILL.md   drives the stages for an agent
tests/                      unittest suite; tests/fakes/ holds fake claude, codex and sandbox-exec
```

## Workspace

A workspace is a folder outside git and synced storage. `init` creates it:

```
config.json                 lineages (CLI paths, models, budgets, Codex disable set, retained tools), roles, canaries
text/original.txt           the user's text, read-only
.claude/settings.json       denies the orchestrating agent any access to sealed/
sealed/                     self-prediction.md, ipip-120.csv (+ items list), written by the user
prepare/                    redactions.json, eras.json (review point), redacted.txt, offsets, segments, sentences,
                            chunks/, zoning/, substrate/<era>.md, removed-sentences.json, retrospective.md,
                            stats.json, receipt.json
prereg/                     prompts/, schemas/ (facet codes filled from the instrument) and instrument/ copied
                            from the repo, facets.md, sealed-hashes.json, qualification-A.json, manifest.jsonl
run/                        qualification.json (until A), qualification-evidence/, probes/, requalification-audit.json,
                            calls/<stage>/<role>/<rater>.json, incidents/, discovery/, codebook/, recode/,
                            deductive/ (per-era ledgers, aggregate ledgers, scores), crosswalk/, agreement.json
report/                     results.json, report.md
```

## Stages

| Module | Stage | Produces |
|---|---|---|
| `init.py` | `init` | workspace, default config (resolves the native Codex binary behind the npm launcher), sealed templates |
| `revise.py` | `revise` | declared so the command exists; refuses (not in this version) |
| `prepare.py` | `prepare` | review files on first run; then redaction, segments/sentences, qualification, zoning per era, substrate, stats and a receipt hashing what it read and wrote |
| `seal.py` | `seal` | validates sealed/ and records its hashes; `verify_sealed` is called by every later stage |
| `freeze.py` | `freeze` | refuses a stale preparation (receipt mismatch), re-qualifies if a fingerprint moved, then freezes generation A: method, substrate, offset map, seal hashes, statistics, the instrument copy, the facet catalog, the qualification baseline and the zoning call records |
| `extract.py` | `extract` | discovery → pool → codebook + validator → card (generation B) → recode with the recurrence bar → deductive ledgers and scores → agreement and integrity audit (generation C) |
| `unmask.py` | `unmask` | two-coder crosswalk (generation D), IPIP scoring, comparisons, results and report (generation E) |
| `status.py` | `status` | generations, call counts, incidents, next step as a code `run.py` renders |

Each stage module declares a `lifecycle.Stage` descriptor (name, order, arguments, preflight `estimate`, and lifecycle rules: the generation it needs, the one that closes it, whether it checks the seal); `run.py` discovers them with `pkgutil` and dispatches uniformly, verifying the manifest before printing any estimate. Every workspace stage but `status` first passes `lifecycle.enter`, which verifies the manifest, the frozen files and (where required) the sealed hashes, and applies those rules. Generations B to D also freeze the call records behind their outputs.

## Shared layers

- **`store.py`**: the `Workspace` path holder, strict JSON (no NaN, no duplicate keys), atomic writes (temp file + rename), sha256, and the manifest: an append-only hash chain of generations, each mapping frozen paths to hashes. `verify_manifest` re-hashes every frozen file.
- **`errors.py`**: typed errors carrying their exit codes; `run.py` maps them and turns any other exception into exit 70, never 1.
- **`config.py`**: parses `config.json` once into typed `Config` and `Lineage` records; malformed config is a usage error. Each lineage keeps its config as canonical JSON text, whose hash is the fingerprint's config hash.
- **`roles.py`**: the single table of role policy: each role's allowed artifact kinds, schema, labels it may take, whether it reads zoned material, whether it runs per era, and which inputs must belong to the calling rater.
- **`schema.py`**: a validator for the JSON Schema subset the schemas use; unsupported keywords are an error.
- **`text.py`**: redaction with an offset map, paragraph segments, sentences (code-point offsets), era validation, and the two renderings: numbered chunks for the zoner, zoned eras for raters.
- **`artifacts.py`**: the artifact-id grammar (`kind:part:…`, each part checked by kind and arity) and its mapping to workspace files, contained in the workspace. Every prompt input is one of these files.
- **`withheld.py`**: gathers the text no prompt may carry (redacted names, removed sentences, self-prediction lines, IPIP answers) for the substring audit.
- **`lifecycle.py`**: the stage-entry guard and the sealed-hash check.
- **`prompts.py`**: the allowlist check against `roles.py`, `assemble` (fills a template's slots from artifact ids and the role's declared one-line labels, records each input's hash) and the secondary substring audit (redacted names everywhere; removed sentences for zoned-material consumers; self-prediction only in crosswalk prompts after generation C; IPIP answers nowhere).
- **`invoke.py`**: the only code that starts a model CLI, and the single call and probe boundary. `claude_argv` / `codex_argv` pin each lineage's invocation; `execute` runs one locked process on the pinned argv in an empty temp dir, and `execute_unlocked` is the positive controls' entry point (locked Claude calls with a temp `HOME` holding only the keychain and an identity-blank copy of the configured account profile, identity env overrides dropped, and an `identity_restored` event if the profile is rewritten; Codex with a temp `CODEX_HOME` and inside a `sandbox-exec` read allowlist), keeping partial output on a timeout; `parse_claude` / `parse_codex` reduce the stream to `Event` records plus every assistant, reasoning and diagnostic text (for canary scans only). `audit_events` reports forbidden kinds as fixed reason codes; `outcome` is the one success predicate (tool event, then timeout or failure, then registry evidence) used by fresh calls, probes, resume and the integrity audit. `call` takes a `CallRequest` of artifact ids, derives template labels and the reveal flag from the workspace, assembles and audits the prompt, holds the call to the frozen qualification baseline after generation A, checks the budget, reuses a record only when it is the same call, every input matches and its stored stream re-derives as a success, and records only validated successes with their events and exit code. `probe` runs the leak probe (or its positive control), decides it and records it without reply content.
- **`capture.py`**: a loopback fake model provider (Responses-API SSE for Codex, Messages-API SSE for Claude) that answers with a scripted tool call and optionally forwards Codex's non-inference reads to the real backend. Handler threads post messages to one recorder (a request dropped before it is recorded becomes `incomplete` traffic); after the server joins them, `Capture.evidence` is a detached snapshot.
- **`qualify.py`**: per lineage, the request capture (no model) and the leak probe (one model call through `invoke.probe`). One predicate covers every locked capture: every request's registry (and, after the baseline, the baseline registry exactly), request model, transport rule, canaries, the shared success predicate and, for a scripted call, the tool's exact pinned result. File and MCP positive controls use `mcp_canary.py`; every capture's sanitized evidence is recorded, pass or fail. `leak_control` is the probe's own positive control, run in the live smoke.
- **`agreement.py`**: Krippendorff's α (nominal, ordinal) over any hashable units, run collapse (mode / rounded median), the arm gate with its 50 % pairing rule, thresholds and reason codes, per-construct statuses, and the integrity-audit runner: typed `Check` outcomes, every check run even after one fails on a harness error.
- **`ipip.py`**: IPIP-NEO-120 parsing and scoring, in exact fractions, and the equal-thirds bands.
- **`extract.py`** also exposes the read interface the verification uses: `load_ratings` returns the blind ratings keyed by `RaterKey`, and `arms` rebuilds both gates from them.
- **`report.py`**: renders `report.md` from `results.json`; it formats and never computes.

## Tests

- Unit tests per module; `tests/fakes/` emulates both CLIs' event streams and their measured behaviour against the capture provider, with switches for tool events, failures, leaks, version changes and interruption.
- `tests/test_capture_cli.py` runs qualification's capture against the real `claude` and `codex` binaries with a stand-in provider, model-free, and skips when a binary is absent.
- `tests/test_end_to_end.py` drives `run.py` stage by stage on the Franklin fixture with the fakes; `tests/recompute.py` recomputes every report figure from the frozen run files and is shared with `tests/live_smoke.sh`, which runs the same pipeline against the real CLIs.

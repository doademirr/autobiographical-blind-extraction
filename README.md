# autobiographical-blind-extraction

Blind, pre-registered personality extraction from your own diary or autobiography, rated by two model families (Claude and Codex) and compared with what you predicted about yourself.

> **Status:** v0.1, walking skeleton. Runs end to end live on macOS. 156 tests, including real-binary isolation checks that call no model. Not yet run on a real person's record.

```console
$ python3 scripts/run.py extract ~/abx/franklin
extract: about 43 model calls (+2 conditional): discovery, recode and ledger per rater and era, ...
{
 "gates": {"inductive": "not_reportable", "deductive": "tentative"},
 "alpha": {"inductive": null, "deductive": 0.7910170196227302}
}
$ python3 scripts/run.py unmask ~/abx/franklin
{"report": "report/report.md"}
```

From the [Franklin demo report](examples/franklin/report.md):

```
- Deductive facets (strict) (ordinal, 30 units): α = 0.791, tentative (0.667 ≤ α < 0.80).
  - Units with both lineages: 90%; raw agreement on them: 48%; missing: 7%; stability α within lineage: claude 0.888, codex 0.921.

| C27 | Frugal calculation         | claude, codex | supported  | no-verdict |
| C43 | Books as social currency   | claude, codex | supported  | supported  |
| C52 | Acting on ideas from reading | claude, codex | supported | supported |
```

## Why

Ask a model what your writing says about you and you get a confident read with nothing behind it. The model knows who's asking, it sees your other files, it does its own arithmetic and nobody can check any of it. This tool runs the same question as a small study instead.

- **Blind.** Raters are clean-room CLI processes with no tools, no instruction files and no account identity. Each role sees only what its allowlist names (a rater, one era of your redacted text). Before any of your text leaves the machine, each CLI is qualified against a local capture of what it sends, and every run is checked again by a leak probe.
- **Two lineages.** Claude and Codex rate independently, so agreement means two different model families saw the same thing.
- **Pre-registered.** The method, the text the raters see and the codebook are hash-frozen before the results exist. A frozen file that changes stops the run.
- **Scripts do the maths.** Krippendorff's α, the gates and every figure in the report are computed by script and recompute from the run files. No model does arithmetic the report states.
- **Sealed comparators.** You write down your predictions and answer the IPIP-NEO-120 before the run. Neither is opened until the blind results are frozen.

The claim ceiling is agreement between raters, never objectivity.

**When not to use it:**

- You want advice, a diagnosis or a type. The report describes patterns and agreement. It isn't a clinical assessment.
- Your record is short. Two eras of about 6k words each were not enough for the inductive arm in the demo (34% of units rated by both lineages against a 50% floor). Expect to need a lot more text.
- You're on Linux or Windows. The Codex read sandbox uses macOS `sandbox-exec` and the Claude login comes from the macOS keychain.
- You want to compare people. One subject per workspace.

## Requirements

- macOS
- Python 3.10+ (stdlib only, nothing to install)
- [Claude Code](https://code.claude.com) 2.1.303+ and [Codex CLI](https://github.com/openai/codex) 0.160.1+, both logged in. Calls run on your own subscriptions; there are no API keys.

Codex qualification pins the exact inert results some tools return on a given CLI version. A newer Codex can fail qualification until those pins are updated, which is deliberate (exit 3 beats an unproven sandbox).

## Install the skill

Clone the repo somewhere local (not a synced folder). The skill drives `scripts/run.py` from the clone, so either open your agent in the clone, or copy `skills/autobiographical-blind-extraction/` into your agent's skills folder (for Claude Code, `~/.claude/skills/`) and tell it where the clone is. Then ask it to run the blind extraction on your record. It stops at each review point and never opens your sealed files.

## Use

Pick a workspace folder outside any git repo or synced folder (Dropbox, iCloud, Google Drive). Then, stage by stage:

```bash
python3 scripts/run.py init    ~/abx/me --text memoir.md --canary 'Bunny' 'INTJ'
python3 scripts/run.py prepare ~/abx/me   # writes review files, then stops
python3 scripts/run.py prepare ~/abx/me   # after you approve them: qualifies both CLIs, zones the text
python3 scripts/run.py seal    ~/abx/me   # after you fill in sealed/
python3 scripts/run.py freeze  ~/abx/me
python3 scripts/run.py extract ~/abx/me
python3 scripts/run.py unmask  ~/abx/me
python3 scripts/run.py status  ~/abx/me   # where a workspace stands and what's next
```

Three review points are yours:

1. **Names and eras.** `prepare` lists candidate names from a local scan (no model). You decide which third parties to replace in `prepare/redactions.json`, split the record into eras in `prepare/eras.json`, and approve both. Nothing is sent before that.
2. **Zoning.** A zoner removes sentences written in hindsight ("looking back, I was…") so raters judge what happened, not your later reading of it. Skim `prepare/retrospective.md` for what went and `prepare/substrate/` for what raters will see.
3. **Sealed comparators.** Write your predictions in `sealed/self-prediction.md` and answer `sealed/ipip-120.csv` in your own editor, before `seal`.

Canaries are words only your own profile or instruction files would contain (a nickname, a test score). The leak probe checks that no rater knows them.

| Exit | Meaning |
|---|---|
| 0 | stage done |
| 1 | a reliability gate fired; the run is valid and the report says which arm isn't reportable |
| 2 | usage or preflight failure (a missing login, a bad config, a probe that could not run) |
| 3 | isolation or leak failure; stop, don't work around it |
| 4 | a frozen or sealed file changed, or a CLI changed since qualification; a new run needs a new workspace |
| 5 | a model call failed; rerun the stage and completed calls are reused |
| 70 | an unexpected harness error (a bug; please report it) |

The report lands in `report/report.md`: agreement per arm, the construct table, how your predictions matched, and the observer estimate against your IPIP-NEO-120 by domain.

## Behaviour worth knowing

- **Cost.** Every model-calling stage prints its call estimate first. The Franklin demo (two eras, about 12.5k words) took 51 calls and 36 minutes. Calls scale with eras × raters × replicates.
- **Resuming.** A failed call (exit 5) can be rerun; finished calls are reused only when every input still matches.
- **What isolation means here.** Before your text is sent, each CLI is pointed at a local fake provider and the harness reads the request it actually sends: the tool list, the system text and any canary. Scripted tool calls prove the tools a CLI won't remove are inert, and positive controls prove the checks can see a real file or MCP read. Codex's capture runs on your real login; Claude's runs on a dummy API key, so it can't see what Claude Code adds only for logged-in accounts. The one such addition known is the account email, so every Claude call runs with a temp home holding the login and an account profile with the identity blanked, any identity written back fails the call, and the leak probe checks end to end. Codex runs every call inside a macOS read sandbox.
- **Strict evidence bar.** A construct counts as present in an era only with two occurrences in separate, non-adjacent passages. On short records most verdicts end up insufficient, and the inductive arm says not reportable rather than guess.
- **Famous texts aren't blind.** Models know published autobiographies. On Franklin they restored redacted names from memory (the prompt audit stopped the run, which is why the demo approves an empty redaction list). The demo tests the pipeline, not the method's validity.

## Development

```bash
python3 -m unittest                  # offline: fake CLIs, plus model-free checks against the real binaries
tests/live_smoke.sh "$TMPDIR/abx-live"   # live: the Franklin pipeline on your subscriptions (~55 calls)
```

`SPEC.md` is the contract and `ARCHITECTURE.md` the as-built structure.

## Credits

- IPIP-NEO-120 items and key: Johnson, J. A. (2014). Measuring thirty facets of the Five Factor Model with a 120-item public domain inventory. *Journal of Research in Personality*, 51, 78–89. Public domain, via [ipip.ori.org](https://ipip.ori.org).
- Krippendorff's α follows Krippendorff (2011), *Computing Krippendorff's Alpha-Reliability*, and reproduces its worked examples.
- Demo text: *Autobiography of Benjamin Franklin*, Project Gutenberg eBook #20203. The demo's self-prediction and questionnaire answers are synthetic.

## Licence

MIT. See [LICENSE](LICENSE).

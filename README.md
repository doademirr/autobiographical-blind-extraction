# autobiographical-blind-extraction

Run a blind analysis over a body of text about you. Diaries, an autobiography project, even years of scattered writing about different events in your life.

The longer the better. To get a decent result we suggest at least 10k words of content in each era, across at least 5-6 different life eras. Each era is a period of years in length.

Why blind extraction? Why not just feed your diary to an agent and ask it for some psychoanalysis? Well, expect to get back a judgement coloured by its memory, AGENTS.md files, account holder info, and other leaks.

This tool does three things:

1. **Strips hindsight.** A zoner removes sentences where the author interprets their past self ("looking back, I was…"). Raters judge what the person did, not how they later explained it.
2. **Uses two blind raters, Claude and Codex.** Each runs as a clean-room CLI process with no tools, instruction files or account identity. It never sees who you are, your sealed self-prediction or any later era of your life.
3. **Counts a trait only if both model families find it in separate episodes.** Claude and Codex rate independently across repeated runs, with identical prompts. The method and codebook are frozen before any results exist, and scripts compute every number.

**When not to use it:**

- You want advice, a diagnosis or a type. The report describes patterns and agreement. Not a clinical assessment.
- Your record is short. 12k words total produced a poor result in tests. Expect to need a lot more text.
- You're on Linux or Windows. Sorry! Feel free to open a PR. The Codex read sandbox uses macOS `sandbox-exec` and the Claude login comes from the macOS keychain.
- You want to compare people. One subject per workspace.
- You want to psycho-analyse a famous person. Like Ben Franklin. Technically possible, but expect the text to already be in the models' training data, so the result will be coloured.

## Requirements

- macOS
- Python 3.10+ (stdlib only, nothing to install)
- [Claude Code](https://code.claude.com) 2.1.303+ and [Codex CLI](https://github.com/openai/codex) 0.160.1+, both logged in. Calls run on your own subscriptions, recommend at least Max 5x / Pro, the cheap plans are unlikely to be enough. There are no API keys in this version.

Codex qualification pins the exact inert results some tools return on a given CLI version. A newer Codex can fail qualification until those pins are updated, which is deliberate (exit 3 beats an unproven sandbox).

## Install the skill

Clone the repo somewhere local. The skill drives `scripts/run.py` from the clone, so either open your agent in the clone, or copy `skills/autobiographical-blind-extraction/` into your agent's skills folder (for Claude Code, `~/.claude/skills/`) and tell it where the clone is. Then ask it to run the blind extraction on your record. It stops at each review point and never opens your sealed files.

**Your text** must be plain UTF-8 text: `.txt` or `.md` files (Markdown is read as plain text, so headings and lists just become paragraphs). PDF, Word and scans aren't read; export them to text first. Pass one file or several with `--text`. Several files are joined in the order you list them, so list them oldest first. Separate paragraphs with a blank line: paragraphs are the units you group into eras.

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

1. **Names and eras.** `prepare` writes `prepare/segments-preview.txt` (each numbered paragraph's first 100 characters) and two templates. You list the third parties to replace in `prepare/redactions.json` (this version has no name scanner; you find them yourself), split the record into eras in `prepare/eras.json`, and approve both. Nothing is sent before that.
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

- **Cost.** Every model-calling stage prints its call estimate first. Calls scale with eras × raters × replicates. For scale: Ben Franklin's full *Autobiography* is about 61k words (53k after the hindsight strip) across 6 eras, and a full run took about 125 model calls and 2 hours.
- **Resuming.** A failed call (exit 5) can be rerun; finished calls are reused only when every input still matches.
- **What isolation means here.** Before your text is sent, each CLI is pointed at a local fake provider and the harness reads the request it actually sends: tool list, system text and any canary. Claude's capture uses a dummy API key, so it can't see what Claude Code adds only for logged-in accounts. Claude calls run with your account identity blanked, Codex calls inside a macOS read sandbox, and a leak probe checks both end to end.
- **Strict evidence bar.** A construct counts as present in an era only with two occurrences in separate, non-adjacent passages. On short records most verdicts end up insufficient, and the inductive arm says not reportable rather than guess.
- **Famous texts aren't blind.** Models know published autobiographies and restore redacted names from memory.

## Development

```bash
python3 -m unittest                  # offline: fake CLIs, plus model-free checks against the real binaries
tests/live_smoke.sh "$TMPDIR/abx-live"   # live: the Franklin pipeline on your subscriptions (~55 calls)
```

`SPEC.md` is the v0.1 contract; its "Scope of this version" section lists the requirements this code does not yet build. `ARCHITECTURE.md` is the as-built structure.

## Credits

- IPIP-NEO-120 items and key: Johnson, J. A. (2014). Measuring thirty facets of the Five Factor Model with a 120-item public domain inventory. *Journal of Research in Personality*, 51, 78–89. Public domain, via [ipip.ori.org](https://ipip.ori.org).
- Krippendorff's α follows Krippendorff (2011), *Computing Krippendorff's Alpha-Reliability*, and reproduces its worked examples.
- Test fixture: *Autobiography of Benjamin Franklin*, Project Gutenberg eBook #20203, with synthetic comparators. An example report is in [`examples/franklin/`](examples/franklin/report.md).

## Licence

MIT. See [LICENSE](LICENSE).

# autobiographical-blind-extraction

Run a blind analysis over a body of text about you. Diaries, an autobiography project, even years of scattered writing about different events in your life.

Get back a list of your main personality traits:

- **Consistent:** present through all your life.
- **Fading:** present in earlier years but not later.
- **Emerging:** present in later years but not earlier.

> [!NOTE]
> This is a fun exercise. Its results should not be taken as clinical or medical advice.

The longer the better. We suggest at least 100k words, across at least 5-6 different life eras of 10k words or more each. Each era is a period of years in length.

Why blind extraction? Why not just feed your diary to an agent and ask it for some psychoanalysis? Well, expect to get back a judgement coloured by its memory, AGENTS.md files, account holder info, and other leaks.

This tool does three things:

1. **Strips hindsight.** A zoner removes sentences where the author interprets their past self ("looking back, I was…"). Raters judge what the person did, not how they later explained it.
2. **Uses two blind raters, Claude and Codex.** Each runs as a clean-room CLI process with no tools, instruction files or account identity. It never sees who you are, your sealed self-prediction or any later era of your life.
3. **Counts a trait only if both model families find it in separate episodes.** Claude and Codex rate independently across repeated runs, with identical prompts. The method and codebook are frozen before any results exist, and scripts compute every number.

**When not to use it:**

- You want advice, a diagnosis or a type. The report describes patterns and agreement. Not a clinical assessment. A psychologist can ask you questions and notice what your writing leaves out.
- You want a quick read. Pasting your diary into a chatbot is faster and fine for a conversation. It just isn't blind.
- You only want your Big Five scores. The [IPIP-NEO-120](https://ipip.ori.org) on its own measures them directly. This adds what your writing shows, era by era.
- Your record is short. 12k words total produced a poor result in tests. Expect to need a lot more text.
- You're on Linux or Windows. Sorry! Feel free to open a PR. The Codex read sandbox uses macOS `sandbox-exec` and the Claude login comes from the macOS keychain.
- You want to compare people. One subject per workspace.
- You want to psycho-analyse a famous person. Like Ben Franklin. Technically possible, but expect the text to already be in the models' training data, so the result will be coloured.

## Tested on a synthetic memoir

We wrote a 155k-word fictional memoir with a known answer: traits planted in every era, traits that fade or appear partway through, hindsight sentences to strip, and decoys. The pass marks were fixed before the run.

| Check | Result |
|---|---|
| Hindsight sentences removed / plain ones kept | 42/42, 12/12 |
| Fades and emergences found at the right era | 4/4 |
| Traits planted in every era, found in at least 5 of 6 | 3/4 |
| Traits never shown, never reported | 2/2 |
| Later eras leaking into earlier ones | none |

Details, the record and the key: [`fixtures/synthetic-memoir/`](fixtures/synthetic-memoir/SOURCE.md). The report: [`examples/synthetic-memoir/`](examples/synthetic-memoir/report.md).

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
python3 scripts/run.py freeze  ~/abx/me   # writes test items (foils), one call per era
python3 scripts/run.py extract ~/abx/me
python3 scripts/run.py unmask  ~/abx/me
python3 scripts/run.py status  ~/abx/me   # where a workspace stands and what's next
python3 scripts/run.py --version          # the harness version and commit, e.g. 0.9.3 (277e506)
```

Three review points are yours:

1. **Names and eras.** `prepare` writes `prepare/segments-preview.txt` (each numbered paragraph's word count, whether it reads as a heading or a dated passage, and its first 100 characters) `prepare/names-preview.txt` and two files to review. `prepare/redactions.json` comes pre-filled from a local scan for names (capitalised words seen mid-sentence, twice or after a title), each with a placeholder; the preview lists every candidate, including those seen once. Delete what isn't a person you want hidden (places, organisations), add the names it missed (nicknames, names only ever at the start of a sentence), then check the eras `prepare/eras.json` proposes (cut at headings and dated passages, within the size limits; each era's `basis` says why it starts there), move the cuts to life events, write each era's label (labels are sent to the raters, so leave names out), and approve both. Nothing is sent before that.

   You decide the eras. Aim for at least 5-6, each a period of years with at least 10k words, and no bigger than the maximum the template's note gives. Eras run in order, back to back, and every paragraph sits in exactly one. Cut at life events: a move, a new school or job, a relationship starting or ending, a birth or death, a long gap in the writing. Don't cut around traits you expect to see. `prepare` checks every era's size before anything is sent and names any era that's too big.
2. **Zoning.** A zoner removes sentences written in hindsight ("looking back, I was…") so raters judge what happened, not your later reading of it. Then read `prepare/spot-check.json`: 20 kept and 20 removed sentences. Mark any that are wrongly labelled and approve it; `freeze` waits for that. Your marks are counted in the report and never change what the raters see. Skim `prepare/retrospective.md` for what went and `prepare/substrate/` for what raters will see.

   The zoner is checked on your own text every run. About 120 sampled sentences, half it kept and half it cut, are labelled blind by a Claude judge and a Codex judge, who see whole paragraphs and never the zoner's labels. If more than 5 % of the sampled kept sentences are reflection, or more than 20 % of the sampled cut ones are events, counting only sentences both judges agree on (the ones they split on are left out and reported), `prepare` and `freeze` stop with exit 1 and no real run is permitted. These are rates on the sample, not confidence bounds.
3. **Sealed comparators.** Write your predictions in `sealed/self-prediction.md` and answer `sealed/ipip-120.csv` in your own editor, before `seal`.

Canaries are words only your own profile or instruction files would contain (a nickname, a test score). The leak probe checks that no rater knows them. It matches text, ignoring case, so pick short distinctive tokens rather than sentences (a model paraphrases), give a hyphenated one in its spaced form too, and check none of them appears in your record.

| Exit | Meaning |
|---|---|
| 0 | stage done |
| 1 | a gate fired: from `prepare` or `freeze`, the zoner failed calibration and the run stops; from `extract`, the run is valid and the report says which arm isn't reportable |
| 2 | usage or preflight failure (a missing login, a bad config, a probe that could not run) |
| 3 | isolation or leak failure; stop, don't work around it |
| 4 | a frozen or sealed file changed, or a CLI changed since qualification; a new run needs a new workspace. Don't upgrade Codex mid-run; Claude Code's self-updates don't affect a run |
| 5 | a model call failed; rerun the stage and completed calls are reused |
| 70 | an unexpected harness error (a bug; please report it) |

The report lands in `report/report.md`: agreement per arm, foil error rates and the audit's flags, the construct table, how each construct changes across eras (fades and emergences both model families see, eras held only by assumption, and its state at the end of the record), how your predictions matched, the observer estimate against your IPIP-NEO-120 by domain (and, as descriptive detail, by facet), each supported construct set against the IPIP facets a separate model mapped it to, and a facet-by-facet map of where the blind extraction, your predictions and your questionnaire agree and diverge.

## Behaviour worth knowing

- **Cost.** Every model-calling stage prints its call estimate first. Calls scale with eras × raters × replicates. For scale: Ben Franklin's full *Autobiography* is about 61k words (53k after the hindsight strip) across 6 eras, and a full run took about 125 model calls and 2 hours. A 155k-word synthetic memoir across 6 eras took about 180 calls and 3 hours 20 minutes.
- **Resuming.** A failed call (exit 5) can be rerun; finished calls are reused only when every input still matches.
- **What isolation means here.** Before your text is sent, each CLI is pointed at a local fake provider and the harness reads the request it actually sends: tool list, system text and any canary. Claude's capture uses a dummy API key, so it can't see what Claude Code adds only for logged-in accounts. Claude calls run with your account identity blanked, Codex calls inside a macOS read sandbox, and a leak probe checks both end to end.
- **Strict evidence bar.** A construct counts as present in an era only with two occurrences in separate, non-adjacent passages. Agreement asks whether both model families see a construct in an era; a construct an era doesn't show counts as not shown, so most of a whole-life codebook is not shown in any one era.
- **Two scoring stances.** Each rater scores the questionnaire facets twice from the same evidence ledgers: strictly (each score rests on that facet's own cited evidence) and leniently (it may infer from the whole ledger set). Only the strict scores gate the observer estimate and feed the comparisons; the report gives the lenient agreement and how far the two stances differ as a sensitivity check.
- **Foils and the audit.** A clean-room author writes up to three test items per era with a known answer for that era, and the raters score them mixed in with the real constructs. The report gives how often raters marked a trait present that the era plainly lacks, and how often they found one it plainly shows. A second model family audits each era first: it drops test items whose answer is arguable and flags constructs the era holds counter-evidence against. Foils never count toward the agreement gate; the report gives an agreement figure with them included for information only.
- **Famous texts aren't blind.** Models know published autobiographies and restore redacted names from memory.

## Development

```bash
python3 -m unittest                  # offline: fake CLIs, plus model-free checks against the real binaries
tests/live_smoke.sh "$TMPDIR/abx-live"   # live: the Franklin pipeline on your subscriptions (~60 calls)
```

[`ARCHITECTURE.md`](ARCHITECTURE.md) is the as-built structure, and its [Not yet built](ARCHITECTURE.md#not-yet-built) section lists what this version leaves out. Bug reports and fixes are welcome: see [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Credits

- IPIP-NEO-120 items and key: Johnson, J. A. (2014). Measuring thirty facets of the Five Factor Model with a 120-item public domain inventory. *Journal of Research in Personality*, 51, 78–89. Public domain, via [ipip.ori.org](https://ipip.ori.org).
- Krippendorff's α follows Krippendorff (2011), *Computing Krippendorff's Alpha-Reliability*, and reproduces its worked examples.
- Test fixture: *Autobiography of Benjamin Franklin*, Project Gutenberg eBook #20203, with synthetic comparators. An example report is in [`examples/franklin/`](examples/franklin/report.md).
- Synthetic memoir: written for this repo by Claude Opus 5.5 and Codex, chapter by chapter from briefs; every person and place in it is invented.

## Attribution

For those who care about such things, the majority of the code in this repo was produced by Claude Opus 5.5 (Anthropic), with david guiding Claude, providing insights, direction and critical review throughout the process.

## Licence

MIT. See [LICENSE](LICENSE).

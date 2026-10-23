# Blind extraction report

## This is not a clinical assessment

This report describes patterns that two families of language models found, blind, in a written life record, and how they line up with your own predictions and questionnaire answers. It is not a diagnosis, a psychological evaluation or advice. The claim it supports is agreement between raters, never objectivity. If anything in it is distressing, set it down and talk to someone you trust.

## How it was made

- Era e1: 1662 sentences in 318 segments; zoning kept 99% of 28439 words (normal); 3 mixed and 5 reflective sentences removed.
- Era e2: 1647 sentences in 310 segments; zoning kept 99% of 25045 words (normal); 2 mixed and 7 reflective sentences removed.
- Era e3: 1477 sentences in 231 segments; zoning kept 100% of 26925 words (normal); 3 mixed and 5 reflective sentences removed.
- Era e4: 1483 sentences in 231 segments; zoning kept 99% of 25319 words (normal); 3 mixed and 7 reflective sentences removed.
- Era e5: 1579 sentences in 298 segments; zoning kept 99% of 25571 words (normal); 5 mixed and 9 reflective sentences removed.
- Era e6: 1582 sentences in 268 segments; zoning kept 99% of 24995 words (normal); 2 mixed and 12 reflective sentences removed.
- Zoning calibration: 120 held-out sentences labelled blind by claude and codex judges; where both judges agree, false keeps 0 of 60 (0%; limit 5%) and false removals 8 of 57 (14%; limit 20%); the judges split on 0 kept and 3 cut sentences, which are left out and unresolved; they gave the same label to 97% and agreed on keep or remove for 98%. These are rates on the sample, against limits fixed in advance, not confidence bounds.
- Your spot check of zoning: you read 20 kept and 20 removed sentences and marked 0 kept and 3 removed as wrongly labelled. Marks are reported, never applied.
- claude: 2.1.308 (Claude Code), model claude-opus-5-5.
- codex: codex-cli 0.160.1, model gpt-6.1-sol.

## Agreement (computed by script)

- **Inductive constructs** (nominal, 474 units): α = 0.833, reportable (α ≥ 0.80).
  - Units with both lineages: 100%; raw agreement on them: 92%; missing: 0%; stability α within lineage: claude 0.922, codex 0.929.
- **Deductive facets (strict)** (ordinal, 30 units): α = 0.787, tentative (0.667 ≤ α < 0.80).
  - Units with both lineages: 87%; raw agreement on them: 58%; missing: 8%; stability α within lineage: claude 0.952, codex 0.960.
- Deductive facets, lenient stance (sensitivity, not a gate; 30 units): α = 0.868; units with both lineages: 87%; raw agreement on them: 54%; stability α within lineage: claude 0.937, codex 0.961.
- Strict against lenient scoring (sensitivity; 55 of 60 lineage-facet scores paired): α = 0.950; the same score in 89%; lenient minus strict on average: +0.05.
- Constructs plus foils (diagnostic, not a gate; 576 units): α = 0.864; units with both lineages: 100%; raw agreement on them: 93%.
- Verdicts downgraded to insufficient by the recurrence and counter-evidence rules: 53.
- Invalid outputs (failed their schema or validator; each call gets up to 3 attempts): 1 (prepare 0, freeze 0, extract 1, unmask 0).

## Foils and the blind audit

Foils are test items written from one era with an answer set in advance (absent for clear and near-miss foils, present for anchored ones), and mixed into the card so raters cannot tell them from constructs. The rates count every rater run's verdict in the foil's own era. They are descriptive: replicate runs are not independent samples, and the audit lineage chose which foils stayed, so they do not rank the lineages.

- Foils written: 18; dropped by the audit as unclear: e3 F3.
- Clear foils (false-positive rate, 5 kept): claude 0% (0 of 15 verdicts); codex 0% (0 of 15 verdicts).
- Near-miss foils (false-positive rate, 6 kept): claude 0% (0 of 18 verdicts); codex 0% (0 of 18 verdicts).
- Anchored foils (recovery rate, 6 kept): claude 100% (18 of 18 verdicts); codex 100% (18 of 18 verdicts).
- Constructs the audit flagged with counter-evidence their definition does not account for: C01 (e6), C05 (e4), C08 (e3, e4, e6), C09 (e4, e5, e6), C10 (e4, e5, e6), C11 (e1), C14 (e1, e2, e3, e4, e5, e6), C16 (e1, e2, e3, e4, e5, e6), C20 (e3, e4, e5, e6), C21 (e3, e4), C22 (e2), C23 (e1, e2), C25 (e1, e4, e5), C27 (e5), C31 (e2), C32 (e4, e6), C35 (e1, e2, e3), C41 (e1, e2, e3), C42 (e5), C44 (e4, e6), C45 (e5, e6), C46 (e4), C48 (e2, e4, e6), C49 (e2, e4, e6), C50 (e1), C51 (e1), C56 (e4), C62 (e1, e2, e4, e5, e6), C63 (e2, e4), C65 (e4), C68 (e2), C76 (e5), C78 (e6), C79 (e1, e2, e4, e5). Flags are reported, not acted on; the construct table shows what raters found.

## Constructs

| Id | Construct | Found by | e1 | e2 | e3 | e4 | e5 | e6 |
|---|---|---|---|---|---|---|---|---|
| C01 | Labelled storage and inventory systems | claude, codex | supported | supported | supported | supported | supported | supported |
| C02 | Financial ledger kept to the cent | claude, codex | supported | supported | supported | contested | supported | contested |
| C03 | Written logs for non-financial domains | claude, codex | supported | supported | supported | supported | supported | supported |
| C04 | Re-counting quantities when accuracy is uncertain | codex | supported | supported | supported | contested | supported | supported |
| C05 | Ordering as an end in itself | codex | supported | supported | not-shown | not-shown | not-shown | not-shown |
| C06 | Retiring systems that stop serving a use | claude, codex | supported | supported | supported | supported | supported | supported |
| C07 | Spatial planning by measurement and drawing | claude, codex | contested | contested | supported | supported | supported | supported |
| C08 | Money kept as an end in itself | claude, codex | supported | supported | not-shown | not-shown | not-shown | not-shown |
| C09 | Refusal to lend or give money | claude, codex | supported | supported | supported | not-shown | not-shown | not-shown |
| C10 | Full commercial prices regardless of relationship | claude, codex | not-shown | supported | supported | not-shown | not-shown | not-shown |
| C11 | Hard bargaining as a buyer | claude, codex | not-shown | supported | contested | not-shown | not-shown | not-shown |
| C12 | Selective spending on capability | codex | supported | supported | supported | supported | supported | supported |
| C13 | Independent verification of claims | claude, codex | supported | supported | supported | supported | supported | supported |
| C14 | Non-confrontational handling of disconfirming evidence | claude, codex | supported | supported | supported | supported | supported | supported |
| C15 | Curiosity about causal mechanism | claude, codex | supported | supported | supported | supported | supported | supported |
| C16 | Understanding stalls at the explanatory gap | claude | not-shown | supported | not-shown | not-shown | not-shown | not-shown |
| C17 | Learning abstractions through concrete cases | claude, codex | supported | supported | supported | supported | supported | supported |
| C18 | Self-directed deep technical study | claude, codex | contested | supported | supported | supported | supported | supported |
| C19 | Preference for inspectable mechanisms | claude, codex | not-shown | contested | supported | supported | supported | supported |
| C20 | Silent abandonment of difficult tasks | claude, codex | supported | supported | not-shown | not-shown | not-shown | not-shown |
| C21 | Effort allocated to chosen interests over schoolwork | codex | not-shown | supported | not-shown | not-shown | not-shown | not-shown |
| C22 | Persistence in formal study | claude, codex | not-shown | not-shown | supported | supported | contested | not-shown |
| C23 | Persistence through project setbacks | claude, codex | not-shown | not-shown | supported | contested | contested | supported |
| C24 | Converting failures into preventive procedures | claude, codex | supported | not-shown | supported | supported | supported | supported |
| C25 | Preserving evidence of failed and superseded work | claude, codex | supported | supported | supported | supported | supported | supported |
| C26 | Explicit uncertainty instead of guessing | claude, codex | supported | supported | supported | supported | supported | supported |
| C27 | Measurement integrity in certification | claude, codex | not-shown | not-shown | supported | supported | supported | supported |
| C28 | Accepting correction and conceding error | claude, codex | not-shown | not-shown | not-shown | supported | supported | supported |
| C29 | Sustained technical argument | claude, codex | not-shown | supported | supported | supported | supported | supported |
| C30 | Systematic fault diagnosis | claude, codex | not-shown | supported | supported | supported | supported | supported |
| C31 | Testing and documentation as part of completion | codex | not-shown | supported | supported | supported | supported | supported |
| C32 | Physical daring before peers | claude, codex | supported | supported | not-shown | not-shown | not-shown | not-shown |
| C33 | Solitary secret physical risk-taking | claude, codex | not-shown | not-shown | supported | not-shown | not-shown | not-shown |
| C34 | Local precautions within risky ventures | claude, codex | supported | supported | supported | supported | not-shown | contested |
| C35 | Declining recreational physical risk | claude, codex | not-shown | not-shown | not-shown | supported | supported | supported |
| C36 | Insistence on work safety procedure | claude, codex | not-shown | not-shown | not-shown | not-shown | supported | contested |
| C37 | Declining offered alcohol | claude, codex | not-shown | not-shown | supported | supported | not-shown | not-shown |
| C38 | Drinking as a way of coping | claude, codex | not-shown | not-shown | not-shown | not-shown | supported | not-shown |
| C39 | Concealing drinking and evading accountability | claude, codex | not-shown | not-shown | not-shown | not-shown | supported | not-shown |
| C40 | Sobriety maintained through refusals | claude, codex | not-shown | not-shown | not-shown | not-shown | not-shown | supported |
| C41 | Withdrawal from social gatherings | claude, codex | not-shown | not-shown | supported | supported | supported | supported |
| C42 | Seeking group belonging | claude, codex | supported | supported | not-shown | not-shown | not-shown | not-shown |
| C43 | Organizing peers from a non-leading position | claude, codex | supported | not-shown | not-shown | not-shown | not-shown | not-shown |
| C44 | Yielding to dominant others | claude, codex | supported | supported | supported | contested | supported | supported |
| C45 | Silently absorbing slights | claude, codex | supported | supported | supported | supported | supported | supported |
| C46 | Withholding prepared evidence in own-interest negotiations | claude, codex | not-shown | not-shown | not-shown | not-shown | supported | supported |
| C47 | Silent accommodation of domestic intrusion | claude, codex | supported | not-shown | supported | supported | contested | not-shown |
| C48 | Contesting with documented evidence | claude, codex | not-shown | not-shown | not-shown | supported | supported | supported |
| C49 | Deference to formal authority | claude, codex | supported | supported | supported | supported | supported | supported |
| C50 | Staying out of family conflict | claude, codex | not-shown | contested | not-shown | not-shown | not-shown | not-shown |
| C51 | Deferring to partner and family in close decisions | claude, codex | not-shown | supported | not-shown | supported | contested | supported |
| C52 | Self-initiated religious practice | claude, codex | supported | supported | not-shown | not-shown | not-shown | not-shown |
| C53 | Private religious gesture for remembrance | claude, codex | not-shown | supported | not-shown | not-shown | not-shown | not-shown |
| C54 | Attachment expressed through presence and practical acts | claude, codex | supported | supported | not-shown | supported | supported | supported |
| C55 | Hands-on fathering and teaching | claude, codex | not-shown | not-shown | not-shown | not-shown | supported | supported |
| C56 | Emotionally flat narration | claude | supported | supported | supported | supported | supported | supported |
| C57 | Rare evaluative words in narration | claude | supported | supported | supported | supported | supported | supported |
| C58 | Indirect approval from father and authorities | claude | supported | supported | supported | supported | not-shown | contested |
| C59 | Identification with father's exactness ethic | claude | supported | contested | not-shown | not-shown | supported | supported |
| C60 | Rivalry with older brother | claude | supported | supported | not-shown | not-shown | not-shown | not-shown |
| C61 | Reconciled warmth with brother | claude | not-shown | contested | not-shown | contested | not-shown | contested |
| C62 | Minimal rationed family contact | claude | not-shown | not-shown | supported | not-shown | not-shown | not-shown |
| C63 | Intimate life absent from the record | claude, codex | contested | not-shown | contested | not-shown | not-shown | contested |
| C64 | Concealment and partial truths | claude, codex | supported | supported | not-shown | contested | supported | contested |
| C65 | Defying protective instructions | claude | contested | not-shown | not-shown | not-shown | not-shown | not-shown |
| C66 | Material generosity without repayment | claude, codex | not-shown | not-shown | not-shown | supported | supported | supported |
| C67 | Explicit financial categories | claude, codex | not-shown | supported | supported | supported | supported | supported |
| C68 | Literal honesty about own labour and value | claude, codex | not-shown | supported | contested | supported | supported | supported |
| C69 | Applying rules to himself | claude, codex | not-shown | not-shown | not-shown | supported | not-shown | contested |
| C70 | Honoring underpriced commitments | claude, codex | not-shown | not-shown | not-shown | not-shown | contested | contested |
| C71 | Mentoring an overlooked learner | claude, codex | not-shown | not-shown | not-shown | contested | not-shown | contested |
| C72 | Loyal companionship with Person 24 | claude, codex | not-shown | not-shown | not-shown | not-shown | supported | supported |
| C73 | Hiring against the ledger's verdict | claude, codex | not-shown | not-shown | not-shown | not-shown | not-shown | supported |
| C74 | Redundant records and backups | claude, codex | not-shown | not-shown | supported | supported | contested | supported |
| C75 | Closing rituals of checking locks | claude | not-shown | not-shown | not-shown | not-shown | not-shown | supported |
| C76 | Clock and quota governance of effort | claude, codex | contested | contested | supported | supported | supported | supported |
| C77 | Resourcefulness with salvaged materials | codex | supported | supported | supported | contested | supported | not-shown |
| C78 | Learning by close observation | codex | supported | not-shown | not-shown | not-shown | not-shown | not-shown |
| C79 | Responsible handling of obligations | codex | supported | supported | supported | supported | contested | supported |

Supported: both lineages find the construct in the era. Contested: they disagree. Not-shown: neither finds it. One-lineage: one side has no verdict; never counted as supported. No-verdict: neither lineage has one (tied or missing runs).

## Over time

An era counts as observed for a construct when both lineages find it there, and as contradicted only when both find evidence against it there. Anything else (silence, a split, a missing verdict) is evidence neither way. A trait stated once and then taken for granted stops producing scenes, so an undecided era after an observation is held by assumption: listed in its own column, never counted as observed.

- Fades (observed, then contradicted): C08 e2 → e6, C09 e3 → e4, C10 e3 → e4, C16 e2 → e3, C20 e2 → e3, C21 e2 → e3, C32 e2 → e4, C37 e4 → e5, C38 e5 → e6, C39 e5 → e6, C42 e2 → e3.
- Emergences (contradicted, then observed): C22 e2 → e3, C23 e2 → e3, C35 e3 → e4, C38 e4 → e5, C39 e4 → e5, C41 e2 → e3, C62 e2 → e3, C66 e3 → e4.
- Now reads the last era of the record under that assumption: use it for who the writer was at the end of the record, and support in any era (what every comparison in this report uses) for lifelong traits. Now cannot establish who you are today; your questionnaire remains the present-day measure.
- Constructs with no observed or contradicted era, left out of the table: 5.

| Id | Construct | Observed in | Contradicted in | Held by assumption | Now |
|---|---|---|---|---|---|
| C01 | Labelled storage and inventory systems | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C02 | Financial ledger kept to the cent | e1, e2, e3, e5 | — | e4, e6 | held (last observed in e5) |
| C03 | Written logs for non-financial domains | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C04 | Re-counting quantities when accuracy is uncertain | e1, e2, e3, e5, e6 | — | e4 | observed in e6 |
| C05 | Ordering as an end in itself | e1, e2 | — | e3, e4, e5, e6 | held (last observed in e2) |
| C06 | Retiring systems that stop serving a use | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C07 | Spatial planning by measurement and drawing | e3, e4, e5, e6 | — | — | observed in e6 |
| C08 | Money kept as an end in itself | e1, e2 | e6 | e3, e4, e5 | faded in e6 |
| C09 | Refusal to lend or give money | e1, e2, e3 | e4, e5, e6 | — | faded in e4 |
| C10 | Full commercial prices regardless of relationship | e2, e3 | e4, e5, e6 | — | faded in e4 |
| C11 | Hard bargaining as a buyer | e2 | — | e3, e4, e5, e6 | held (last observed in e2) |
| C12 | Selective spending on capability | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C13 | Independent verification of claims | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C14 | Non-confrontational handling of disconfirming evidence | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C15 | Curiosity about causal mechanism | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C16 | Understanding stalls at the explanatory gap | e2 | e3, e4, e5, e6 | — | faded in e3 |
| C17 | Learning abstractions through concrete cases | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C18 | Self-directed deep technical study | e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C19 | Preference for inspectable mechanisms | e3, e4, e5, e6 | — | — | observed in e6 |
| C20 | Silent abandonment of difficult tasks | e1, e2 | e3, e4, e5, e6 | — | faded in e3 |
| C21 | Effort allocated to chosen interests over schoolwork | e2 | e3 | — | faded in e3 |
| C22 | Persistence in formal study | e3, e4 | e2 | e5, e6 | held (last observed in e4) |
| C23 | Persistence through project setbacks | e3, e6 | e1, e2 | e4, e5 | observed in e6 |
| C24 | Converting failures into preventive procedures | e1, e3, e4, e5, e6 | — | e2 | observed in e6 |
| C25 | Preserving evidence of failed and superseded work | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C26 | Explicit uncertainty instead of guessing | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C27 | Measurement integrity in certification | e3, e4, e5, e6 | — | — | observed in e6 |
| C28 | Accepting correction and conceding error | e4, e5, e6 | — | — | observed in e6 |
| C29 | Sustained technical argument | e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C30 | Systematic fault diagnosis | e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C31 | Testing and documentation as part of completion | e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C32 | Physical daring before peers | e1, e2 | e4, e5, e6 | e3 | faded in e4 |
| C33 | Solitary secret physical risk-taking | e3 | — | e4, e5, e6 | held (last observed in e3) |
| C34 | Local precautions within risky ventures | e1, e2, e3, e4 | — | e5, e6 | held (last observed in e4) |
| C35 | Declining recreational physical risk | e4, e5, e6 | e1, e2, e3 | — | observed in e6 |
| C36 | Insistence on work safety procedure | e5 | — | e6 | held (last observed in e5) |
| C37 | Declining offered alcohol | e3, e4 | e5 | — | faded in e5 |
| C38 | Drinking as a way of coping | e5 | e4, e6 | — | faded in e6 |
| C39 | Concealing drinking and evading accountability | e5 | e4, e6 | — | faded in e6 |
| C40 | Sobriety maintained through refusals | e6 | — | — | observed in e6 |
| C41 | Withdrawal from social gatherings | e3, e4, e5, e6 | e1, e2 | — | observed in e6 |
| C42 | Seeking group belonging | e1, e2 | e3, e4, e5, e6 | — | faded in e3 |
| C43 | Organizing peers from a non-leading position | e1 | — | e2, e3, e4, e5, e6 | held (last observed in e1) |
| C44 | Yielding to dominant others | e1, e2, e3, e5, e6 | — | e4 | observed in e6 |
| C45 | Silently absorbing slights | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C46 | Withholding prepared evidence in own-interest negotiations | e5, e6 | — | — | observed in e6 |
| C47 | Silent accommodation of domestic intrusion | e1, e3, e4 | — | e2, e5, e6 | held (last observed in e4) |
| C48 | Contesting with documented evidence | e4, e5, e6 | — | — | observed in e6 |
| C49 | Deference to formal authority | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C51 | Deferring to partner and family in close decisions | e2, e4, e6 | — | e3, e5 | observed in e6 |
| C52 | Self-initiated religious practice | e1, e2 | — | e3, e4, e5, e6 | held (last observed in e2) |
| C53 | Private religious gesture for remembrance | e2 | — | e3, e4, e5, e6 | held (last observed in e2) |
| C54 | Attachment expressed through presence and practical acts | e1, e2, e4, e5, e6 | — | e3 | observed in e6 |
| C55 | Hands-on fathering and teaching | e5, e6 | — | — | observed in e6 |
| C56 | Emotionally flat narration | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C57 | Rare evaluative words in narration | e1, e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C58 | Indirect approval from father and authorities | e1, e2, e3, e4 | — | e5, e6 | held (last observed in e4) |
| C59 | Identification with father's exactness ethic | e1, e5, e6 | — | e2, e3, e4 | observed in e6 |
| C60 | Rivalry with older brother | e1, e2 | — | e3, e4, e5, e6 | held (last observed in e2) |
| C62 | Minimal rationed family contact | e3 | e1, e2 | e4, e5, e6 | held (last observed in e3) |
| C63 | Intimate life absent from the record | — | e2, e4 | — | never observed |
| C64 | Concealment and partial truths | e1, e2, e5 | — | e3, e4, e6 | held (last observed in e5) |
| C66 | Material generosity without repayment | e4, e5, e6 | e1, e2, e3 | — | observed in e6 |
| C67 | Explicit financial categories | e2, e3, e4, e5, e6 | — | — | observed in e6 |
| C68 | Literal honesty about own labour and value | e2, e4, e5, e6 | — | e3 | observed in e6 |
| C69 | Applying rules to himself | e4 | — | e5, e6 | held (last observed in e4) |
| C72 | Loyal companionship with Person 24 | e5, e6 | — | — | observed in e6 |
| C73 | Hiring against the ledger's verdict | e6 | — | — | observed in e6 |
| C74 | Redundant records and backups | e3, e4, e6 | — | e5 | observed in e6 |
| C75 | Closing rituals of checking locks | e6 | — | — | observed in e6 |
| C76 | Clock and quota governance of effort | e3, e4, e5, e6 | — | — | observed in e6 |
| C77 | Resourcefulness with salvaged materials | e1, e2, e3, e5 | — | e4, e6 | held (last observed in e5) |
| C78 | Learning by close observation | e1 | — | e2, e3, e4, e5, e6 | held (last observed in e1) |
| C79 | Responsible handling of obligations | e1, e2, e3, e4, e6 | — | e5 | observed in e6 |

## Your predictions

- Predictions matched: 3 of 5 decided (60%); ambiguous (coders disagree, excluded): P2, P3, P4, P8.
- Supported constructs matched to a prediction: 3 of 73 (4%).
- Coder agreement on prediction-construct pairs: 93%.
  - P1: matched
  - P2: ambiguous
  - P3: ambiguous
  - P4: ambiguous
  - P5: unmatched
  - P6: partial
  - P7: matched
  - P8: ambiguous
  - P9: matched

## Observer estimate vs your IPIP-NEO-120

The observer estimate covers the whole record; your questionnaire describes you now. Both your predictions and the questionnaire are self-report, so this is not independent triangulation.

| Domain | Observer (1–7) | Band | IPIP (1–5) | Band | Same band |
|---|---|---|---|---|---|
| Neuroticism | 3.90 | mid | 2.92 | mid | yes |
| Extraversion | 4.17 | mid | 3.42 | mid | yes |
| Openness to Experience | n/a | n/a | 2.92 | mid | n/a |
| Agreeableness | 4.67 | mid | 3.25 | mid | yes |
| Conscientiousness | 5.83 | high | 3.54 | mid | no |

Same band in 75% of 4 domains compared.

### Facets, descriptive

The same comparison for each facet. Descriptive only, not a headline result: a facet rests on fewer scores than a domain, and the domain table above is the comparison this report stands on.

- Observer estimates missing for 4 of 30 facets; IPIP scores missing for 0 of 30. Same band in 31% of 26 facets compared.

| Facet | Observer (1–7) | Band | IPIP (1–5) | Band | Same band |
|---|---|---|---|---|---|
| N1 Anxiety | 4.50 | mid | 4.25 | high | no |
| N2 Anger | 3.50 | mid | 2.75 | mid | yes |
| N3 Depression | n/a | n/a | 3.00 | mid | n/a |
| N4 Self-Consciousness | 5.00 | high | 3.00 | mid | no |
| N5 Immoderation | 3.50 | mid | 1.75 | low | no |
| N6 Vulnerability | 3.00 | low | 2.75 | mid | no |
| E1 Friendliness | 3.50 | mid | 3.00 | mid | yes |
| E2 Gregariousness | 3.00 | low | 3.00 | mid | no |
| E3 Assertiveness | 3.50 | mid | 4.00 | high | no |
| E4 Activity Level | 7.00 | high | 3.25 | mid | no |
| E5 Excitement-Seeking | 4.00 | mid | 4.25 | high | no |
| E6 Cheerfulness | 4.00 | mid | 3.00 | mid | yes |
| O1 Imagination | n/a | n/a | 2.75 | mid | n/a |
| O2 Artistic Interests | n/a | n/a | 3.00 | mid | n/a |
| O3 Emotionality | 4.00 | mid | 2.75 | mid | yes |
| O4 Adventurousness | 4.50 | mid | 3.00 | mid | yes |
| O5 Intellect | 7.00 | high | 3.00 | mid | no |
| O6 Liberalism | n/a | n/a | 3.00 | mid | n/a |
| A1 Trust | 2.50 | low | 3.00 | mid | no |
| A2 Morality | 6.00 | high | 3.25 | mid | no |
| A3 Altruism | 4.00 | mid | 4.00 | high | no |
| A4 Cooperation | 5.00 | high | 3.25 | mid | no |
| A5 Modesty | 6.00 | high | 3.00 | mid | no |
| A6 Sympathy | 4.50 | mid | 3.00 | mid | yes |
| C1 Self-Efficacy | 6.50 | high | 3.25 | mid | no |
| C2 Orderliness | 7.00 | high | 4.50 | high | yes |
| C3 Dutifulness | 5.50 | high | 3.25 | mid | no |
| C4 Achievement-Striving | 6.00 | high | 4.25 | high | yes |
| C5 Self-Discipline | 5.00 | high | 3.00 | mid | no |
| C6 Cautiousness | 5.00 | high | 3.00 | mid | no |

## Constructs against your IPIP facets

A separate model mapped each construct to the questionnaire facets it bears on, from the construct's name and definition alone, with a direction (+ for the facet's high pole). Each supported construct's facets are set against your IPIP facet scores. A construct counts when it is supported in at least one era of the record, while the questionnaire describes you now, so a mismatch may be change over time. Narrative tends to over-read traits shown in charged scenes and to miss traits that show as absence.

- Construct–facet pairs: 24 consistent, 11 inconsistent, 63 neutral (mid band), 0 without a facet score.
- Supported constructs mapped to no facet: C06, C08, C17, C21, C37, C52, C53, C57, C58, C77.

| Construct | Facet | Direction | IPIP (1–5) | Band | Result |
|---|---|---|---|---|---|
| C01 Labelled storage and inventory systems | C2 Orderliness | + | 4.50 | high | consistent |
| C02 Financial ledger kept to the cent | C2 Orderliness | + | 4.50 | high | consistent |
| C03 Written logs for non-financial domains | C2 Orderliness | + | 4.50 | high | consistent |
| C04 Re-counting quantities when accuracy is uncertain | C6 Cautiousness | + | 3.00 | mid | neutral |
| C05 Ordering as an end in itself | C2 Orderliness | + | 4.50 | high | consistent |
| C07 Spatial planning by measurement and drawing | C2 Orderliness | + | 4.50 | high | consistent |
| C07 Spatial planning by measurement and drawing | C6 Cautiousness | + | 3.00 | mid | neutral |
| C09 Refusal to lend or give money | A3 Altruism | - | 4.00 | high | inconsistent |
| C10 Full commercial prices regardless of relationship | A6 Sympathy | - | 3.00 | mid | neutral |
| C11 Hard bargaining as a buyer | A4 Cooperation | - | 3.25 | mid | neutral |
| C12 Selective spending on capability | C6 Cautiousness | + | 3.00 | mid | neutral |
| C13 Independent verification of claims | A1 Trust | - | 3.00 | mid | neutral |
| C13 Independent verification of claims | C6 Cautiousness | + | 3.00 | mid | neutral |
| C14 Non-confrontational handling of disconfirming evidence | A4 Cooperation | + | 3.25 | mid | neutral |
| C14 Non-confrontational handling of disconfirming evidence | E3 Assertiveness | - | 4.00 | high | inconsistent |
| C15 Curiosity about causal mechanism | O5 Intellect | + | 3.00 | mid | neutral |
| C16 Understanding stalls at the explanatory gap | O5 Intellect | - | 3.00 | mid | neutral |
| C18 Self-directed deep technical study | C5 Self-Discipline | + | 3.00 | mid | neutral |
| C18 Self-directed deep technical study | O5 Intellect | + | 3.00 | mid | neutral |
| C19 Preference for inspectable mechanisms | O5 Intellect | + | 3.00 | mid | neutral |
| C20 Silent abandonment of difficult tasks | C3 Dutifulness | - | 3.25 | mid | neutral |
| C20 Silent abandonment of difficult tasks | C5 Self-Discipline | - | 3.00 | mid | neutral |
| C22 Persistence in formal study | C2 Orderliness | + | 4.50 | high | consistent |
| C22 Persistence in formal study | C4 Achievement-Striving | + | 4.25 | high | consistent |
| C22 Persistence in formal study | C5 Self-Discipline | + | 3.00 | mid | neutral |
| C23 Persistence through project setbacks | C5 Self-Discipline | + | 3.00 | mid | neutral |
| C24 Converting failures into preventive procedures | C2 Orderliness | + | 4.50 | high | consistent |
| C24 Converting failures into preventive procedures | C6 Cautiousness | + | 3.00 | mid | neutral |
| C25 Preserving evidence of failed and superseded work | C2 Orderliness | + | 4.50 | high | consistent |
| C26 Explicit uncertainty instead of guessing | A2 Morality | + | 3.25 | mid | neutral |
| C26 Explicit uncertainty instead of guessing | C6 Cautiousness | + | 3.00 | mid | neutral |
| C27 Measurement integrity in certification | A2 Morality | + | 3.25 | mid | neutral |
| C27 Measurement integrity in certification | C3 Dutifulness | + | 3.25 | mid | neutral |
| C28 Accepting correction and conceding error | A5 Modesty | + | 3.00 | mid | neutral |
| C29 Sustained technical argument | A4 Cooperation | - | 3.25 | mid | neutral |
| C29 Sustained technical argument | E3 Assertiveness | + | 4.00 | high | consistent |
| C30 Systematic fault diagnosis | C5 Self-Discipline | + | 3.00 | mid | neutral |
| C30 Systematic fault diagnosis | C6 Cautiousness | + | 3.00 | mid | neutral |
| C30 Systematic fault diagnosis | O5 Intellect | + | 3.00 | mid | neutral |
| C31 Testing and documentation as part of completion | C3 Dutifulness | + | 3.25 | mid | neutral |
| C31 Testing and documentation as part of completion | C5 Self-Discipline | + | 3.00 | mid | neutral |
| C32 Physical daring before peers | C6 Cautiousness | - | 3.00 | mid | neutral |
| C32 Physical daring before peers | E5 Excitement-Seeking | + | 4.25 | high | consistent |
| C33 Solitary secret physical risk-taking | E5 Excitement-Seeking | + | 4.25 | high | consistent |
| C34 Local precautions within risky ventures | C6 Cautiousness | + | 3.00 | mid | neutral |
| C35 Declining recreational physical risk | E5 Excitement-Seeking | - | 4.25 | high | inconsistent |
| C36 Insistence on work safety procedure | C3 Dutifulness | + | 3.25 | mid | neutral |
| C36 Insistence on work safety procedure | C6 Cautiousness | + | 3.00 | mid | neutral |
| C36 Insistence on work safety procedure | E3 Assertiveness | + | 4.00 | high | consistent |
| C38 Drinking as a way of coping | N5 Immoderation | + | 1.75 | low | inconsistent |
| C38 Drinking as a way of coping | N6 Vulnerability | + | 2.75 | mid | neutral |
| C39 Concealing drinking and evading accountability | A2 Morality | - | 3.25 | mid | neutral |
| C39 Concealing drinking and evading accountability | C3 Dutifulness | - | 3.25 | mid | neutral |
| C39 Concealing drinking and evading accountability | C6 Cautiousness | - | 3.00 | mid | neutral |
| C40 Sobriety maintained through refusals | C5 Self-Discipline | + | 3.00 | mid | neutral |
| C40 Sobriety maintained through refusals | N5 Immoderation | - | 1.75 | low | consistent |
| C41 Withdrawal from social gatherings | E2 Gregariousness | - | 3.00 | mid | neutral |
| C42 Seeking group belonging | E2 Gregariousness | + | 3.00 | mid | neutral |
| C43 Organizing peers from a non-leading position | C2 Orderliness | + | 4.50 | high | consistent |
| C43 Organizing peers from a non-leading position | E3 Assertiveness | - | 4.00 | high | inconsistent |
| C44 Yielding to dominant others | A4 Cooperation | + | 3.25 | mid | neutral |
| C44 Yielding to dominant others | E3 Assertiveness | - | 4.00 | high | inconsistent |
| C45 Silently absorbing slights | A4 Cooperation | + | 3.25 | mid | neutral |
| C45 Silently absorbing slights | E3 Assertiveness | - | 4.00 | high | inconsistent |
| C46 Withholding prepared evidence in own-interest negotiations | E3 Assertiveness | - | 4.00 | high | inconsistent |
| C47 Silent accommodation of domestic intrusion | A4 Cooperation | + | 3.25 | mid | neutral |
| C47 Silent accommodation of domestic intrusion | E3 Assertiveness | - | 4.00 | high | inconsistent |
| C48 Contesting with documented evidence | E3 Assertiveness | + | 4.00 | high | consistent |
| C49 Deference to formal authority | E3 Assertiveness | - | 4.00 | high | inconsistent |
| C51 Deferring to partner and family in close decisions | E3 Assertiveness | - | 4.00 | high | inconsistent |
| C54 Attachment expressed through presence and practical acts | A3 Altruism | + | 4.00 | high | consistent |
| C54 Attachment expressed through presence and practical acts | E1 Friendliness | + | 3.00 | mid | neutral |
| C55 Hands-on fathering and teaching | A3 Altruism | + | 4.00 | high | consistent |
| C55 Hands-on fathering and teaching | C3 Dutifulness | + | 3.25 | mid | neutral |
| C56 Emotionally flat narration | O3 Emotionality | - | 2.75 | mid | neutral |
| C59 Identification with father's exactness ethic | C2 Orderliness | + | 4.50 | high | consistent |
| C60 Rivalry with older brother | A4 Cooperation | - | 3.25 | mid | neutral |
| C62 Minimal rationed family contact | E1 Friendliness | - | 3.00 | mid | neutral |
| C64 Concealment and partial truths | A2 Morality | - | 3.25 | mid | neutral |
| C66 Material generosity without repayment | A3 Altruism | + | 4.00 | high | consistent |
| C66 Material generosity without repayment | A5 Modesty | + | 3.00 | mid | neutral |
| C66 Material generosity without repayment | A6 Sympathy | + | 3.00 | mid | neutral |
| C67 Explicit financial categories | A2 Morality | + | 3.25 | mid | neutral |
| C67 Explicit financial categories | C2 Orderliness | + | 4.50 | high | consistent |
| C68 Literal honesty about own labour and value | A2 Morality | + | 3.25 | mid | neutral |
| C68 Literal honesty about own labour and value | C3 Dutifulness | + | 3.25 | mid | neutral |
| C69 Applying rules to himself | A2 Morality | + | 3.25 | mid | neutral |
| C69 Applying rules to himself | C3 Dutifulness | + | 3.25 | mid | neutral |
| C72 Loyal companionship with Person 24 | E1 Friendliness | + | 3.00 | mid | neutral |
| C73 Hiring against the ledger's verdict | A3 Altruism | + | 4.00 | high | consistent |
| C73 Hiring against the ledger's verdict | A6 Sympathy | + | 3.00 | mid | neutral |
| C74 Redundant records and backups | C2 Orderliness | + | 4.50 | high | consistent |
| C74 Redundant records and backups | C6 Cautiousness | + | 3.00 | mid | neutral |
| C75 Closing rituals of checking locks | C6 Cautiousness | + | 3.00 | mid | neutral |
| C76 Clock and quota governance of effort | C2 Orderliness | + | 4.50 | high | consistent |
| C76 Clock and quota governance of effort | C5 Self-Discipline | + | 3.00 | mid | neutral |
| C78 Learning by close observation | C6 Cautiousness | + | 3.00 | mid | neutral |
| C79 Responsible handling of obligations | C3 Dutifulness | + | 3.25 | mid | neutral |

## Where the three views meet

Each questionnaire facet gets a direction (high or low) from three views. Blind: the supported constructs mapped to it, and the observer estimate (1–7). Self: your predictions, tagged to facets by both crosswalk coders and counted only where they agree. Test: your IPIP answers (1–5). Divergent facets come first: any two views pointing opposite ways, or a view whose own evidence points both ways (shown, not explained). "Only" compares the blind view with your predictions; the test column says whether the questionnaire agrees. Test-only facets are questionnaire signals neither other view raised, which is no evidence that either missed them.

- Facets: 14 divergent, 2 all three, 0 blind and self, 6 blind only, 1 self only, 1 test only.
- Prediction tags the two coders did not share (placed nowhere): P2 O4, P3 A4.

| View | Facet | Constructs | Observer | Blind | Predictions | Self | IPIP | Test |
|---|---|---|---|---|---|---|---|---|
| divergent | A2 Morality | C26+, C27+, C39−, C64−, C67+, C68+, C69+ | 6.00 high | conflict | — | — | 3.25 mid | — |
| divergent | A3 Altruism | C09−, C54+, C55+, C66+, C73+ | 4.00 mid | conflict | P7+ | high | 4.00 high | high |
| divergent | A4 Cooperation | C11−, C14+, C29−, C44+, C45+, C47+, C60− | 5.00 high | conflict | — | — | 3.25 mid | — |
| divergent | A6 Sympathy | C10−, C66+, C73+ | 4.50 mid | conflict | — | — | 3.00 mid | — |
| divergent | C3 Dutifulness | C20−, C27+, C31+, C36+, C39−, C55+, C68+, C69+, C79+ | 5.50 high | conflict | — | — | 3.25 mid | — |
| divergent | C5 Self-Discipline | C18+, C20−, C22+, C23+, C30+, C31+, C40+, C76+ | 5.00 high | conflict | P6+ | high | 3.00 mid | — |
| divergent | C6 Cautiousness | C04+, C07+, C12+, C13+, C24+, C26+, C30+, C32−, C34+, C36+, C39−, C74+, C75+, C78+ | 5.00 high | conflict | P2− | low | 3.00 mid | — |
| divergent | E1 Friendliness | C54+, C62−, C72+ | 3.50 mid | conflict | P4− | low | 3.00 mid | — |
| divergent | E2 Gregariousness | C41−, C42+ | 3.00 low | conflict | P4− | low | 3.00 mid | — |
| divergent | E3 Assertiveness | C14−, C29+, C36+, C43−, C44−, C45−, C46−, C47−, C48+, C49−, C51− | 3.50 mid | conflict | P3+ | high | 4.00 high | high |
| divergent | E5 Excitement-Seeking | C32+, C33+, C35− | 4.00 mid | conflict | P2+ | high | 4.25 high | high |
| divergent | N5 Immoderation | C38+, C40− | 3.50 mid | conflict | P9− | low | 1.75 low | low |
| divergent | N6 Vulnerability | C38+ | 3.00 low | conflict | — | — | 2.75 mid | — |
| divergent | O5 Intellect | C15+, C16−, C18+, C19+, C30+ | 7.00 high | conflict | P8+ | high | 3.00 mid | — |
| all three | C2 Orderliness | C01+, C02+, C03+, C05+, C07+, C22+, C24+, C25+, C43+, C59+, C67+, C74+, C76+ | 7.00 high | high | P1+ | high | 4.50 high | high |
| all three | C4 Achievement-Striving | C22+ | 6.00 high | high | P6+ | high | 4.25 high | high |
| blind only | A1 Trust | C13− | 2.50 low | low | — | — | 3.00 mid | — |
| blind only | A5 Modesty | C28+, C66+ | 6.00 high | high | — | — | 3.00 mid | — |
| blind only | C1 Self-Efficacy | — | 6.50 high | high | — | — | 3.25 mid | — |
| blind only | E4 Activity Level | — | 7.00 high | high | — | — | 3.25 mid | — |
| blind only | N4 Self-Consciousness | — | 5.00 high | high | — | — | 3.00 mid | — |
| blind only | O3 Emotionality | C56− | 4.00 mid | low | — | — | 2.75 mid | — |
| self only | O2 Artistic Interests | — | n/a | — | P5+ | high | 3.00 mid | — |
| test only | N1 Anxiety | — | 4.50 mid | — | — | — | 4.25 high | high |

## Limits

- Raters saw one era at a time, so patterns that only show across eras are not captured.
- Discovery used a fixed panel; saturation was not established.
- Narrative over-reads emotionally charged scenes and misses traits that show as absence.
- Models may already know a published text; on one, this run tests the method's plumbing, not its validity.

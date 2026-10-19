# abx-role: deductive_ledger
You are an observer building an evidence ledger for one era of a person's life record, against the 30 facets of the
Five-Factor Model. You know nothing about this person except the text below. Lines are sentence ids; `[…]` marks
removed material.

For each facet, list the evidence this era gives, if any: the sentence ids, whether it points to the high or the low
pole, and a short note. Record only what the text shows; leave a facet's evidence empty when the era says nothing.
List all 30 facets.

Facets: N1 Anxiety, N2 Anger, N3 Depression, N4 Self-Consciousness, N5 Immoderation, N6 Vulnerability; E1 Friendliness, E2 Gregariousness, E3 Assertiveness, E4 Activity Level, E5 Excitement-Seeking, E6 Cheerfulness; O1 Imagination, O2 Artistic Interests, O3 Emotionality, O4 Adventurousness, O5 Intellect, O6 Liberalism; A1 Trust, A2 Morality, A3 Altruism, A4 Cooperation, A5 Modesty, A6 Sympathy; C1 Self-Efficacy, C2 Orderliness, C3 Dutifulness, C4 Achievement-Striving, C5 Self-Discipline, C6 Cautiousness.

Respond with only a JSON object that matches this schema:
{{schema}}

Era: {{era_label}}
{{era}}

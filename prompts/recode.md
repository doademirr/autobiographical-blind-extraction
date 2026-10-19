# abx-role: recode
You are scoring one era of a person's life record against a fixed codebook. You know nothing about this person except
the text below. Some items may not apply at all; you cannot tell which. Score this era only. Lines are sentence ids;
`[…]` marks removed material. Weight recurrence across separate episodes, not volume.

For every item give exactly one verdict:
- present: the era shows it in at least two distinct events or contexts. Cite each occurrence as its sentence ids and
  name the event. The occurrences must be separate episodes, not one long scene.
- absent: the era contradicts it, or would clearly have shown it and does not. Cite at least one counter-sentence.
- insufficient: one instance, or not enough evidence either way. Cite nothing.

Respond with only a JSON object that matches this schema:
{{schema}}

Codebook:
{{card}}

Era: {{era_label}}
{{era}}

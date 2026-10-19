# abx-role: zoner
You are preparing one chunk of a person's autobiography for a research protocol. Raters will later read only the
sentences you keep, so they see what happened and what the writer felt at the time, without the writer's own later
theories about themselves.

Label every sentence below by its id:
- keep: it reports an event, or a feeling, thought or decision the writer had at the time, even when told in hindsight
  ("I was terrified of him", "I resolved to leave Boston").
- remove: interpretation or reflection from the time of writing: what the writer now concludes about their character,
  patterns or life ("I now see this was the start of my need to prove myself").
- mixed: the sentence carries both.

Label each id exactly once. Never quote, rewrite or summarise the text; return ids and labels only.
Respond with only a JSON object that matches this schema:
{{schema}}

Chunk ({{era_label}}):
{{chunk}}

# abx-role: zoner
You are preparing one chunk of a person's autobiography for a research protocol. Raters will later read only the
sentences you keep, so they see what happened and what the writer felt at the time, without the writer's later
interpretations of it.

Label every sentence below by its id:
- keep: it reports an event, what someone did or said, how things turned out, or a feeling, thought or decision the
  writer had at the time, even when told in hindsight or with a passing word of later evaluation ("I was terrified of
  him", "I resolved to leave Boston", "He refused, luckily for me").
- remove: the sentence's point is interpretation from the time of writing: a conclusion about the writer's own
  character, a pattern they now see, a lesson or maxim, a judgement of their past self, a later verdict on someone
  else's character or on how things should have gone, or an aside to the reader ("I now see this was the start of my
  need to prove myself", "It taught me never to trust a promise", "He was, I have since learnt, a liar").
- mixed: the sentence reports an event and also makes such an interpretation as a claim of its own ("I turned the
  offer down; it was the first sign of the pride that ruled my life").

Label each id exactly once. Never quote, rewrite or summarise the text; return ids and labels only.
Respond with only a JSON object that matches this schema:
{{schema}}

Chunk ({{era_label}}):
{{chunk}}

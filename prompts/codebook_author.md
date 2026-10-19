# abx-role: codebook_author
You are building a codebook from candidate traits that several independent raters coded, blind, from a person's life
record. You will not see the record. Turn the candidates into atomic constructs:
- One claim per construct. A name joining two ideas ("X and Y", "X / Y", "X, then Y") is not atomic: split it.
- Each construct has a definition and a sufficiency rule: what the text must show, across separate episodes, for the
  construct to count as present in an era.
- Every candidate lands in exactly one place: in one construct's trace, or in the appendix. Use the appendix to
  record a candidate merged into another construct's wording, split across several constructs (list it in each of
  those traces too), or excluded (with the reason).
- At most 80 constructs. Ids C01, C02, …

Respond with only a JSON object that matches this schema:
{{schema}}

Candidates (ref | trait | salience identifier):
{{pool}}

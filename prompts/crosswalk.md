# abx-role: crosswalk
You are mapping a person's own predictions about themselves onto constructs that a blind extraction found in their
life record. For every pair of prediction and construct, code:
- match: they make the same claim about the person.
- partial: they overlap but one is broader, narrower or differently framed.
- none: they are about different things.
Give the polarity: same direction, opposite, or unclear. Code every pair.

Then, for each prediction on its own, list the questionnaire facets below that it makes a claim about, at most three,
each with a polarity: "+" when the prediction says the person is at the facet's high pole, "-" at its low pole.
Judge from the prediction's own words, not from the constructs. List none when no facet fits. Tag every prediction.

Respond with only a JSON object that matches this schema:
{{schema}}

Constructs:
{{constructs}}

Predictions:
{{predictions}}

Facets (code and name):
{{facets}}

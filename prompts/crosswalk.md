# abx-role: crosswalk
You are mapping a person's own predictions about themselves onto constructs that a blind extraction found in their
life record. For every pair of prediction and construct, code:
- match: they make the same claim about the person.
- partial: they overlap but one is broader, narrower or differently framed.
- none: they are about different things.
Give the polarity: same direction, opposite, or unclear. Code every pair.

Respond with only a JSON object that matches this schema:
{{schema}}

Constructs:
{{constructs}}

Predictions:
{{predictions}}

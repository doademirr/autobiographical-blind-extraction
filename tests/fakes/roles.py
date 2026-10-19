"""Outputs the fake CLIs generate, by role, from the prompt they receive."""

import re

ROLE_LINE = re.compile(r"^# abx-role: ([a-z_]+)", re.M)


def role_of(prompt: str) -> str:
    m = ROLE_LINE.search(prompt)
    return m.group(1) if m else "unknown"


def respond(prompt: str, lineage: str, occurrence: int, leak: str | None):
    role = role_of(prompt)
    if role == "probe":
        return {"answer": leak or "NONE"}
    if role == "echo":
        return {"answer": f"{lineage}:{occurrence}"}
    raise SystemExit(f"fake: no response for role {role!r}")

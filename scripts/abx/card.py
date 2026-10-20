"""The recode card: what one item looks like to a rater, constructs and foils alike.

Item ids come from one hash space and every item renders through one line format, sorted by
id, so a rater cannot tell a foil from a construct.
"""

import hashlib
import re
from collections.abc import Iterable, Mapping

__all__ = ["COMPOUND_NAME", "MAX_CONSTRUCTS", "item_id", "line", "render"]

# Markers that always join two claims. "and", "or" and commas are left to the author's instruction: in a live run
# they mostly joined two objects or near-synonyms of one trait, and a lexical gate on them failed good codebooks.
COMPOUND_NAME = re.compile(r"[/&+;]|\bvs\.?\b|\bthen\b|\bfollowed by\b", re.I)
MAX_CONSTRUCTS = 80


def item_id(key: str, salt: str) -> str:
    return "K" + hashlib.sha256(f"{key}|{salt}".encode()).hexdigest()[:6]


def line(item: Mapping) -> str:
    """One card item as raters see it; the size check builds its largest possible card from this too."""
    return f"- {item['item_id']}: {item['name']}. {item['definition']} Present when: {item['sufficiency_rule']}\n"


def render(items: Iterable[Mapping]) -> str:
    return "".join(line(i) for i in sorted(items, key=lambda i: i["item_id"]))

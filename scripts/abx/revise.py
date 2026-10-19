"""`revise`: the authorised pre-unmask revision path, which this version does not implement.

A frozen artifact cannot be changed in place; until `revise` exists, a change means a new workspace.
"""

from pathlib import Path

from . import lifecycle
from .errors import UsageError

__all__ = ["STAGE"]


def _run(ws_path: Path, args) -> dict:
    raise UsageError("revise is not in this version; start a new workspace to change a frozen artifact")


STAGE = lifecycle.Stage("revise", 7, "authorised pre-unmask revision (not in this version)", _run,
                        creates_workspace=True, args=(lifecycle.Arg(("artifact",), {}),))

"""Typed failures. Each carries the process exit code SPEC § User Interface assigns it.

Exit 1 is a reported outcome, never a crash: Python's own uncaught-exception exit is
also 1, so `run.py` catches everything and maps unexpected exceptions elsewhere.
"""


__all__ = ["AbxError", "CallFailed", "GateFired", "IntegrityError", "IsolationError", "UsageError"]


class AbxError(Exception):
    exit_code = 99


class GateFired(AbxError):
    exit_code = 1


class UsageError(AbxError):
    """Bad arguments or a failed preflight, before any model call."""

    exit_code = 2


class IsolationError(AbxError):
    """A rater could reach something outside its prompt, or a leak was detected."""

    exit_code = 3


class IntegrityError(AbxError):
    """A frozen artifact, sealed file or fingerprint changed without authorisation."""

    exit_code = 4


class CallFailed(AbxError):
    """A model call failed or returned invalid output; rerunning the stage retries it."""

    exit_code = 5

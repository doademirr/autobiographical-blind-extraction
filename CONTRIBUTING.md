# Contributing

This project is finished. Bug reports and fixes are welcome; new features are unlikely to be merged.

## Reporting a bug

> [!WARNING]
> Never paste your own text, report, workspace files or call records into an issue. They hold your life record. Describe the problem, or reproduce it on `fixtures/franklin/` or `fixtures/synthetic-memoir/`.

Include:

- `python3 scripts/run.py --version`, `claude --version` and `codex --version`
- macOS and Python versions
- the stage you ran, its exit code and the last lines it printed
- `python3 scripts/run.py status <ws>`

## Changing the code

- macOS, Python 3.10+, standard library only. No dependencies.
- Run `python3 -m unittest` before opening a pull request; it runs offline, with fake CLIs plus model-free checks against the real binaries. `ruff check .` must pass.
- Scripts compute every number the report states; no model does arithmetic.
- A change to how a call is isolated bumps `ISOLATION_POLICY` in `scripts/abx/invoke.py`, and a change to how verdicts are coded, resampled or counted bumps `METHOD_VERSION`, so no old workspace is finished under new rules.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) describes the structure.

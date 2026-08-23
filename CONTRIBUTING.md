# Contributing

Thank you for considering a contribution — human and agent contributors alike are welcome.

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) for Python environment and dependency management:

```sh
uv sync
```

## Quality gates

Both gates must pass before a pull request is opened:

```sh
ruff format --check .
ruff check .
pytest
```

Apply formatting with `ruff format .` before pushing rather than arguing with the linter.

## Commits

Conventional Commits are recommended (not enforced): prefix subjects with `feat:`,
`fix:`, `docs:`, `refactor:`, or `chore:` so history stays scannable.

## Agent contributors

Coding agents are first-class contributors here. [AGENTS.md](AGENTS.md) is the operating
manual for any agent working in this repository — it defines the pipeline, the script-first
execution rules, and the open-source hygiene constraints. Human reviewers supervising an
agent should read it too.

Note in particular: JSON output schemas of `scripts/` CLIs are interfaces. Changing one is
a breaking change and must be flagged as such in your pull request.

## Decision history

Significant decisions are recorded as dated documents under [`plans/`](plans/). Read them
to understand why the project looks the way it does. Recorded decisions are changed by
writing a new dated plan document, never by silently editing around them.

# Contributing to Deckhand

Code, bug reports, documentation, accessibility feedback, and reviews are welcome.
Human and AI-assisted contributions follow the same review and safety standards.
Contributors must understand and verify everything they submit. Contributions
are made under the project's [MIT license](docs/license.md).

## Setup

Fork/clone the repository and create a focused branch. Python 3.11+ and Poetry
2.2+ are required; see [Poetry installation](https://python-poetry.org/docs/#installation).
Run from the project root:

```console
poetry install --with dev,docs --no-interaction
poetry run deckhand --demo
poetry run pytest
poetry run sphinx-build -W --keep-going -b html docs docs/_build/local-html
poetry check --lock
poetry build
```

Poetry manages the environment and installs the package in editable mode.
The docs group is optional; `poetry install --with dev` is enough for code work.
Commit poetry.lock with dependency changes and use `poetry lock` to refresh it.
Avoid unrelated lockfile upgrades. Released wheels remain installable with pip.

## Tests and native integration

Use synthetic cards, httpx.MockTransport, fake Hello providers, and temporary
directories. Never use a real nation password, existing vault, or live junk command
in tests. See [architecture](docs/architecture.md) for module boundaries and
[security](SECURITY.md) for reporting sensitive bugs.

Run targeted tests while editing, then the full suite before submitting code.
Add regression coverage for changes to bids, protections, account identity,
cancellation, uncertain writes, and credential failure. Headless tests do not
prove native Windows Hello, TPM, or desktop keyring compatibility; describe
manual platform checks and their limits. Use `--config-dir` with a disposable
private directory for manual UI checks. Demo mode is the default smoke check.

## Documentation

Sphinx builds Markdown through MyST with the Read the Docs theme. Edit docs/
and add new pages to docs/index.md's toctree. Root policy files are included in
the site to keep contributor and agent guidance in one place. Preview
docs/_build/local-html/index.html after a warnings-as-errors build. Update the
README when installation or the main user workflow changes.

## Pull requests and releases

Use the PR template to explain the problem, resulting behavior, checks run, and
platform limitations. Indicate AI assistance when used and verify its output.
Keep review discussion respectful and focused on the work.
Use [Conventional Commits](docs/commit-conventions.md).

Update CHANGELOG.md under Unreleased. Changes to shipped behavior, packaging,
dependencies, native integration, or release automation also bump the single
version in pyproject.toml. If the change set already bumps it, do not bump again.
Docs/templates alone may skip the bump. Follow the [release checklist](docs/releasing.md).
CI validates tests, docs, and distributions; it does not publish releases.

# Deckhand agent instructions

## Workflow

Deckhand is a Python 3.11+ NationStates card cleanup library and Textual TUI.
Read README.md, CONTRIBUTING.md, and relevant source before changing behavior.
Use Poetry 2.2+ for all dependency management, commands, and builds:

```console
poetry install --with dev,docs --no-interaction
poetry run pytest
poetry run sphinx-build -W --keep-going -b html docs docs/_build/local-html
poetry check --lock
poetry build
poetry run deckhand --demo
```

Commit poetry.lock. Change dependencies in pyproject.toml and run `poetry lock`;
do not hand-edit the lockfile or update unrelated dependencies. Never install
project dependencies globally. Report checks run, outcomes, and limitations.

## Code map

| Module in src/deckhand/ | Responsibility |
| --- | --- |
| models.py | Card identities, Decimal prices, policies, decisions, plans |
| api.py | Strict XML parsing, public reads, private commands, rate gate |
| service.py | Preview and sequential per-copy revalidation/execution |
| storage.py | Account metadata and atomic writes |
| credentials.py | Vault and credential backend selection |
| hello.py | Native Windows Passport/Hello |
| tui.py | Textual screens, workers, confirmation, plan lifecycle |

Tests live in tests/. Documentation lives in docs/.

## Safety contracts

- Use synthetic demo data, mocked HTTP, temporary paths, and fake native
  credential providers. Never junk live cards during checks.
- Never import browser passwords or other apps' credentials, or open existing
  user vaults. Never print passwords, PINs, prepare tokens, or secret headers.
- Keep preview separate from execution. Require selected nation confirmation;
  execution cannot exceed reviewed identities, seasons, or copy counts.
- Preserve collection/listing protection defaults and the strictly-greater-than
  bid comparison. Use Decimal for prices.
- Preserve cooperative stop and per-copy revalidation, including the bid read
  after preparation. Never automatically retry a write with uncertain outcome.
- Share a RateGate across account clients in one event loop. Public reads must
  not send credentials. Reject malformed or ambiguous responses.
- Credential backends fail closed: no silent downgrade from Hello or keyring.
  Plaintext requires explicit opt-in. Keep blocking native unlock and key
  derivation off the Textual event loop.
- Library plans are not intrinsically single-use; callers must consume them and
  rescan after execution. Do not claim atomic market protection.

## Change discipline

Add focused regression coverage for behavioral changes; docs-only changes need
a clean docs build. Update CHANGELOG.md and docs for user-facing changes.
For shipped behavior, packaging, dependencies, or release automation, bump the
version in pyproject.toml once per change set. It is the authoritative version;
do not add a second hard-coded package version. Docs/templates alone may skip
the bump. Follow .github/git-commit-instructions.md for commit wording.
Preserve unrelated local work. Do not publish packages or push tags unless asked.

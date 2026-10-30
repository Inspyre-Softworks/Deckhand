# Troubleshooting

## Poetry or dependencies

Use Poetry 2.2+ and a Python 3.11+ interpreter. If needed, select it with
`poetry env use PATH_TO_PYTHON`, then install again. After an update, rerun
`poetry install --with dev,docs --no-interaction`. The Windows launcher installs
runtime dependencies from the lockfile on each launch.

If Poetry itself reports a credential-manager access error while accessing
public package indexes, temporarily set POETRY_KEYRING_ENABLED=false in that
shell and retry. This controls Poetry's package-index credentials, not Deckhand's
credential storage. Do not change Deckhand vaults to diagnose a Poetry failure.

## Hello unlock or key creation fails

Configure Windows Hello for the current Windows user. The application fails
closed when mandatory authentication is unavailable. The 0.1.1 fix qualifies
Passport key names with the user SID and improves native error context; it does
not certify every Windows/TPM configuration. Select another storage method
explicitly if needed. Never share credential envelopes when reporting errors.

## System keyring unavailable

Linux needs a working desktop secret service and D-Bus session. Headless shells
may not provide one. Unknown/plaintext backends are intentionally rejected.
Choose session-only or password-encrypted storage explicitly if appropriate.

## Rate limit or malformed API response

Wait before rescanning after a rate limit; other apps share the IP allowance.
Unexpected XML or identity mismatches stop cleanup rather than guessing.

## Uncertain junk result

Stop and rescan the deck. Do not retry the command: it may already have succeeded.
A stop request lets the current request finish. Deckhand cannot recover cards
already junked.

## Layout or launch problems

Use a terminal at least 110 columns wide and scroll the sidebar on short screens.
Check `poetry run deckhand --demo` before diagnosing live account behavior.

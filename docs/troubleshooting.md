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

The status area distinguishes loading the deck/protections, checking bids
(current/total), waiting for the next request slot, and waiting for a server
response. Rate pacing displays a countdown refreshed each second.

After protections load, preview shows an approximate time remaining and the
number of bid checks left. The countdown uses current request spacing, measured
response time, and server backoff. It updates as responses arrive; before that,
it shows an estimating message. Slow responses can exceed the estimate, so it
is not a guaranteed completion time. Stop, completion, and errors clear it.

The [API limit](https://www.nationstates.net/pages/api.html#ratelimits) is
50 requests per 30 seconds, shared by IP, rather than a sustained two per second.
Deckhand starts at 0.65-second spacing and adjusts to response headers, remaining
budget, and retry deadlines. A 429 stops the operation without retrying writes.

Wait before rescanning after a rate limit; other apps share the IP allowance.
Unexpected XML or identity mismatches stop cleanup rather than guessing.

## Uncertain junk result

Stop and rescan the deck. Do not retry the command: it may already have succeeded.
A stop request lets the current request finish. Deckhand cannot recover cards
already junked.

## Layout or launch problems

Use a terminal at least 110 columns wide and scroll the sidebar on short screens.
Check `poetry run deckhand --demo` before diagnosing live account behavior.

## Garbled labels or punctuation

Earlier beta source contained incorrectly decoded punctuation in headings,
status messages, and missing-value placeholders. Update the source and restart
Deckhand. UI separators now use plain punctuation; no terminal font or code-page
change is needed for this fix. Unknown card names display `(unknown)` and absent
bids display `-`. Real nation names are preserved.

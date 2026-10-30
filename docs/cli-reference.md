# Command-line reference

```console
poetry run deckhand --help
poetry run deckhand [--demo] [--config-dir PATH]
```

| Option | Meaning |
| --- | --- |
| --demo | Synthetic preview, no network requests, execution disabled |
| --config-dir PATH | Override account/vault directory |
| -h, --help | Show usage and exit |

The module entry point is `poetry run python -m deckhand.tui`.
The Windows launcher accepts only `-Demo`; use the CLI for a custom config path.
There is no unattended junk command, background service, or installer in this
source distribution.

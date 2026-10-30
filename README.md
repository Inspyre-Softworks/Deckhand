# Deckhand

A Python library with a Textual terminal app for cleaning NationStates card decks.

**Status: working local beta.** Public API reads and response formats have been checked live. Cleanup is tested with mocked private commands; no real cards were junked during development. Native Windows Hello and Linux desktop keyring integration require testing on the target computer. Windows Hello uses a Passport-specific authentication policy which may not be supported on every Windows configuration; it fails closed without falling back to plaintext, keyring, or ordinary DPAPI.

## Run

Version 0.1.1 fixes Windows Hello error `0x80090027` during key creation by qualifying Passport key names with the current Windows user SID. Native errors now identify the failing operation/property. If updating an extracted copy, replace the source and run `Run-Deckhand.ps1`; the launcher runs the updated source even when its `.venv` already exists. For pip installations, reinstall the new wheel. Full native unlock still needs verification outside the development sandbox.

Version 0.1.2 makes the project Poetry-managed and adds contributor documentation.
Python 3.11+ and [Poetry 2.2+](https://python-poetry.org/docs/#installation) are
required when running from source. From this directory on Windows or Linux:

```console
poetry install --only main --no-interaction
poetry run deckhand --demo
poetry run deckhand
```

On Windows, the launcher installs locked runtime dependencies and starts the app:

```powershell
.\Run-Deckhand.ps1 -Demo
.\Run-Deckhand.ps1
```

Poetry installs the source in editable mode and uses poetry.lock. Built wheels
remain pip-installable without Poetry. Reinstall the new wheel when updating a
wheel installation.

`--demo` uses synthetic cards and disables execution. It makes no network requests and saves no account changes. A terminal at least 110 columns wide works best; the sidebar scrolls on short terminals. `Ctrl+S` previews, `Escape` requests a safe stop, and `Ctrl+Q` quits after work has stopped.

## Accounts and cleanup

1. Add each nation as a separate account. Choose its storage method; saving a password is optional.
2. Enter a contact nation or email for the API User-Agent.
3. Choose the maximum rarity and preview. Common is the initial cutoff. Collection and sale-listing protection start enabled and can independently be disabled. Settings are saved per account when you preview.
4. Review every unique card, copy count, best bid, junk value and decision. A bid **strictly above** junk value always protects the card. A bid equal to junk value does not. Market value and asks alone do not protect a card (your own sale listings are protected by the separate default setting).
5. Use **Credentials** to enter the selected account's password when ready. Session-only mode keeps it in memory until exit or Forget credentials.
6. Choose **Junk reviewed cards**, type the exact selected nation name, and unlock the chosen credential store if prompted.

Multiple accounts have separate credentials, labels and cleanup preferences. Runs are deliberately sequential: switch accounts between runs. Previewing needs no login. Accounts are never imported from your browser or another app.

Execution rechecks deck ownership, protections and bids for each copy; it checks bids again after preparing the private command. It never adds unreviewed cards or exceeds the reviewed quantity. A rising bid causes the card to be skipped. All copies of a protected card identity/season are kept. Disable protection explicitly to include those copies; the app does not cancel sale listings for you, and NationStates can reject junking a committed card.

The API has no atomic "junk only if no better bid" transaction. A bid or collection can still change between the final read and execution. Use Stop to finish the current request and prevent the next command. On an uncertain write result the run stops without retrying; rescan to reconcile the deck. Junking is permanent.

## Credential storage

| Method | Behavior |
| --- | --- |
| Session only | Never persists the password. Re-enter after restarting. |
| Password encrypted | Scrypt (N=131072, r=8, p=1) derives an AES-256-GCM key from a separate vault password, with random salt and nonce. The master password is never saved. |
| Windows Hello | Default selection on Windows. A random AES key encrypts the password; a non-exported RSA key in the Microsoft Passport key storage provider wraps the AES key. Unlock requires the provider's authentication-mandatory policy. No weaker fallback. Windows Hello must already be configured. |
| System keyring | Default selection on Linux (also available on Windows/macOS). Supports Secret Service, KWallet, Windows Credential Locker and macOS Keychain through Python keyring. Rejects unknown/plaintext backends. Linux needs a working desktop secret service / D-Bus session. |
| Plaintext | Explicit opt-in and warnings on save. Anyone able to read the file or its backups can obtain the nation password. |

The storage selector defaults to Hello on Windows and keyring elsewhere; **adding an account never saves credentials**. Missing/unavailable secure storage is an error, never a reason to downgrade automatically. Use a different storage method explicitly if required. Storage method is selected when adding the account; to change it in this beta, forget its credentials, remove the account, and add it again with the desired method.

Account metadata is in `accounts.json` under the platform's user config directory (`platformdirs.user_config_path("ns-deckhand", appauthor=False)`). File credentials live under `credentials/` keyed by account UUID. Use `--config-dir PATH` for a portable location. POSIX files use owner-only permissions; on Windows, files inherit their parent directory's ACL, so keep portable directories private. The OS keyring and Hello keys remain OS-bound rather than portable.

Passwords, session PINs and prepare tokens are never logged. Python cannot guarantee erasure of immutable secret strings from process memory. Forgotten files may remain in filesystem snapshots/backups. Losing a master password or resetting Hello can make saved credentials unrecoverable; you can always enter the nation password again. Hello storage is a local unlock mechanism, not a replacement for NationStates password authentication.

## Library

The UI imports the same public API as other Python clients:

```python
import asyncio
from deckhand import NationStates, Cleaner, Policy, Rarity, RateGate

async def preview():
    gate = RateGate()  # share this across clients/accounts in one event loop
    async with NationStates("your_nation", "your_contact_nation", gate=gate) as api:
        cleaner = Cleaner(api)
        plan = await cleaner.preview(Policy(maximum=Rarity.RARE))
        print(plan.copies, plan.proceeds)
        for decision in plan.decisions:
            print(decision.card.key, decision.reason)
        # Only after the caller obtains explicit confirmation:
        # result = await cleaner.execute(plan, password,
        #     confirmed_nation=plan.nation, stop=asyncio.Event())

asyncio.run(preview())
```

`Vault`, `Account`, and `Settings` are available in their respective modules for custom frontends. Credential backends are local and synchronous; the TUI uses `asyncio.to_thread` so native unlock prompts and password derivation do not block rendering.

Use a plan only once. The TUI consumes it and demands a rescan after execution or an uncertain result. Library callers must enforce the same workflow. The rate gate serializes requests and observes the API's limit/remaining/reset and retry headers; clients stop on rate-limit errors instead of retrying writes. Other running programs/processes on the same IP still share NationStates' rate allowance.

## Development and verification

See [CONTRIBUTING.md](CONTRIBUTING.md) for the human contribution workflow,
[AGENTS.md](AGENTS.md) for coding-agent guidance, [docs](docs/index.md) for the
full documentation, [CHANGELOG.md](CHANGELOG.md) for changes, and
[SECURITY.md](SECURITY.md) for private vulnerability reporting. Deckhand is
licensed under the [MIT license](LICENSE).

```console
poetry install --with dev,docs --no-interaction
poetry run pytest
poetry run sphinx-build -W --keep-going -b html docs docs/_build/local-html
poetry check --lock
poetry build
```

Tests cover exact price comparisons, default protections and overrides, duplicates by season, changed bids/protections, account mismatch, cancellation, uncertain writes, XML parsing, session isolation, encrypted-file tampering, plaintext opt-in, and Textual previews/account switching. Hello envelope tests use an injected fake provider and do not certify native Windows/TPM behavior. No credential-store integration test touches your existing secrets.

Implementation references: [NationStates API](https://www.nationstates.net/pages/api.html), [Textual workers](https://textual.textualize.io/guide/workers/), [Python keyring](https://keyring.readthedocs.io/en/stable/), [Microsoft Windows Hello](https://learn.microsoft.com/en-us/windows/apps/develop/security/windows-hello), [Passport policy implementation reference](https://github.com/sirAndros/KeePassWinHello/blob/master/src/AuthProviders/WinHelloProvider.cs).

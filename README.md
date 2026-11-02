# Deckhand

A Python library with a Textual terminal app for cleaning NationStates card decks.

**Status: working local beta.** Public API reads and response formats have been checked live. The maintainer has successfully junked and gifted real cards using Deckhand. Automated tests use mocked private commands and synthetic cards. Native Windows Hello and Linux desktop keyring integration require testing on the target computer. Windows Hello uses a Passport-specific authentication policy which may not be supported on every Windows configuration; it fails closed without falling back to plaintext, keyring, or ordinary DPAPI.

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

1. Open **Manage nations...** and add each nation as a separate account. Choose its storage method; the credential dialog opens immediately. You can cancel and enter credentials later.
2. Open **API settings...** and save a contact nation or email for the API User-Agent.
3. Choose the maximum rarity and preview. Common is the initial cutoff. Collection and sale-listing protection start enabled and can independently be disabled. Settings are saved per account when you preview.
4. Review every unique card, copy count, best bid, junk value and decision. A bid **strictly above** junk value always protects the card. A bid equal to junk value does not. Market value and asks alone do not protect a card (your own sale listings are protected by the separate default setting).
5. Use **Manage nations... > Set credentials** to enter or replace the selected nation's password. Session-only mode keeps it in memory until exit or Forget credentials.
6. Choose **Junk reviewed cards**, type the exact selected nation name, and unlock the chosen credential store if prompted.

Multiple accounts have separate credentials, labels and cleanup preferences. Runs are deliberately sequential: switch accounts between runs. Previewing needs no login. Accounts are never imported from your browser or another app.

Use the selector above the preview table to show **All cards**, **Eligible cards**,
or **Ineligible cards**. The count describes visible unique cards. This changes
only the view: the cleanup summary and confirmation still cover every eligible
copy in the reviewed plan. Changing rarity or protection settings requires a new preview.

Selecting a saved nation automatically loads its cards using public reads, even
without saved credentials. This quick load uses names supplied by the deck or
already in the local catalog, without fetching missing names. **Resolve card
names** opens a progress dialog to fetch missing names separately. **Cancel** or
Escape interrupts the public lookup immediately and keeps completed names in
the table and catalog; resolve again to continue. A lookup failure also keeps
completed names. Name resolution clears any reviewed preview, so preview again
before junking.
Cards initially show **Not checked**. Click **Preview
cleanup** to check protections and bids and enable eligibility filtering. Policy
changes keep the cards visible but clear the reviewed plan until you preview again.

Decks and completed previews are cached per account in memory until you quit.
Switching back restores the cards, eligibility results, and display filter without
API requests. A cache timestamp identifies the snapshot. **Refresh deck** fetches
the live card list and clears eligibility; **Preview cleanup** always runs fresh
checks. Policy changes discard that account's cached preview. Cleanup consumes
the preview and evicts its deck snapshot, including uncertain write outcomes;
execution performs the checks required by the reviewed execution mode. Cleanup snapshots stay in memory; public card metadata is saved separately in the local catalog.

By default, execution rechecks deck ownership, protections and bids for each copy; it checks bids again after preparing the private command. It never adds unreviewed cards or exceeds the reviewed quantity. A rising bid causes the card to be skipped. All copies of a protected card identity/season are kept. Disable protection explicitly to include those copies; the app does not cancel sale listings for you, and NationStates can reject junking a committed card.

**Faster execution** is optional, off by default, and can be changed after review.
It trusts the reviewed queue and sends only prepare/execute commands: two requests
per successful copy, with no deck, collection, listing, name, or bid rechecks.
It never adds unreviewed identities or exceeds reviewed copy counts. Changes
since review, including new bids or protections, will not be detected. Standard
execution keeps its live per-copy checks. Switching modes preserves the review
and display filter; the mode is saved immediately and stated in confirmation.
Both modes retain shared rate limiting, cooperative Stop, and no uncertain-write
retries. Source totals may refresh after a junking run has ended.

The API has no atomic "junk only if no better bid" transaction. A bid or collection can still change between the final read and execution. Use Stop to finish the current request and prevent the next command. On an uncertain write result the run stops without retrying; rescan to reconcile the deck. Junking is permanent.

## Name protection and API usage

### Manual sale review

After preview, buttons appear when qualifying cards have bids **equal to junk
value** or **above junk value**. These groups respect the rarity cutoff and every
enabled protection, including protected nation names. Display filters do not
change the groups. Each review lists the snapshot's bids and owned copies with
links to the card market pages. Verify the signed-in nation and current price,
then match bids manually on NationStates. A bid need not cover all owned copies.
Refresh preview after manual sales. Deckhand does not submit asks, match bids,
or auction cards: the documented API has no selling command.

### Protected nation names

**Protect my nations** is enabled by default and keeps cards named after any
nation configured in Deckhand, across all seasons and copies. Disable it explicitly
for an account to allow those cards through the remaining cleanup rules.

Use **Protected name rules...** to enter exact nation names or literal text that
a card's nation name contains, one entry per line. These lists are saved per
account. Matching ignores case and treats spaces and underscores alike; blank
lines are ignored. For example, exact `Silver Harbour` protects that nation,
while contains `Harbour` protects every card name containing that text.
Display labels are not nation names. Custom name rules remain active even if
Protect my nations is turned off. Rule changes invalidate the cached preview.
Missing deck names are resolved from live card information before eligibility
is decided; standard execution checks the live name again, including after preparation.

### API usage counters

The bottom-left sidebar shows requests attempted this session and a saved lifetime
total. Both include failed HTTP attempts, public reads, and private commands;
cached views and demo mode do not increment them. The lifetime count starts when
this feature is first used and lives in `api_usage.sqlite3` in the configuration
directory. It survives restarts, supports concurrent increments, and contains
only aggregate counts. A different `--config-dir` has its own lifetime total.
If the usage database cannot be accessed, the lifetime display says unavailable
and API operations continue.

## Credential storage

| Method | Behavior |
| --- | --- |
| Session only | Never persists the password. Re-enter after restarting. |
| Password encrypted | Scrypt (N=131072, r=8, p=1) derives an AES-256-GCM key from a separate vault password, with random salt and nonce. The master password is never saved. |
| Windows Hello | Default selection on Windows. A random AES key encrypts the password; a non-exported RSA key in the Microsoft Passport key storage provider wraps the AES key. Unlock requires the provider's authentication-mandatory policy. No weaker fallback. Windows Hello must already be configured. |
| System keyring | Default selection on Linux (also available on Windows/macOS). Supports Secret Service, KWallet, Windows Credential Locker and macOS Keychain through Python keyring. Rejects unknown/plaintext backends. Linux needs a working desktop secret service / D-Bus session. |
| Plaintext | Explicit opt-in and warnings on save. Anyone able to read the file or its backups can obtain the nation password. |

The storage selector defaults to Hello on Windows and keyring elsewhere; **adding an account prompts for credentials immediately; saving still requires submitting that dialog**. Missing/unavailable secure storage is an error, never a reason to downgrade automatically. Use a different storage method explicitly if required. Storage method is selected when adding the account; to change it in this beta, forget its credentials, remove the account, and add it again with the desired method.

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

During API work, the status area shows the current stage and bid-check count,
plus whether Deckhand is waiting for a request slot, pacing requests (with a
countdown), or waiting for the server response. Requests start at 0.65-second
spacing and slow down according to the server's shared-budget and retry headers.

After deck/protection reads finish, preview also shows an estimated time remaining
and bid checks left. Junking also shows an estimated time remaining and copies
left, accounting for per-copy safety requests and copies skipped by live checks.
The countdown starts after confirmation and credential unlock. It counts down and revises with observed response times and
rate-limit backoff; slow server responses can make it take longer than estimated.

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

## Local card catalog

**Find card locally** searches previously fetched cards by exact nation name or
card number, showing each known season. Name lookup ignores case and treats
spaces and underscores alike. Loading decks and checking markets automatically
update `cards.sqlite3` in the configuration directory. Unknown cards are absent
until fetched; this is not a complete NationStates card database. Demo mode does
not populate or search the catalog.

The catalog persists public number, season, name, and rarity only. Results are
metadata, not owned copies or current prices. Cleanup always performs its live
safety reads. Remove `cards.sqlite3` to reset the catalog while Deckhand is closed.

## UI controls

The main view keeps nation selection and card tools in bordered groups.
**Manage nations...** holds adding/removing nations and setting/forgetting
credentials. **API settings...** holds the API contact nation or email. Press
Enter in a single-line dialog input to submit; multiline protection lists retain
normal Enter-to-newline behavior.

Preview and cleanup display progress, request pacing, and ETA in modal dialogs.
Their **Stop** button or Escape requests a cooperative stop after the current
request. Name resolution has its own immediate public-read cancellation and
keeps partial names. The main deck panel has no progress bar.

Select a card row (click or press Enter), then choose **Protect selected card**
to save its exact nation name for the current account, across seasons. Unknown
names are fetched first. Saving invalidates the preview; preview again to see
the new protection. Card names are shared in the local catalog across all
nations, including when revisiting cached deck views.

**Use flag colors** is optional and saved per account. It derives readable
accents from that nation's flag while retaining a dark background and clear
warning/error colors. The first use per nation per session makes one public
flag-information request and one image download, both paced and counted through
the shared gate. The accent is cached for the session; failed downloads use the
default theme. Demo makes no flag requests.

**About Deckhand** shows the TUI version and backend package version from
installed package metadata. Both ship together in `ns-deckhand`.

## Gift cards between saved nations

Choose **Gift cards...**, select a different saved recipient, and enter the
minimum bank to leave in the sending nation. **Review gifts** loads fresh
ownership and estimated market values, then lists cards highest value first
(ties use card number and season). All rarities and cleanup-protected cards are
included; listed cards are excluded. Each copy's gifting fee equals its junk
value. The review shows the current bank, floor, per-copy fees, and estimated
number affordable. It does not send anything.

Continue and type both nation names to confirm. Only the sender's credentials
are used. Gifts execute sequentially in reviewed market-value order with only
prepare/execute commands. There are no additional bank, ownership, listing, or
market reads during execution. The floor is enforced locally against reviewed
bank minus confirmed gift fees. Other spending or changed fees can make the
actual bank differ or cross the floor; refresh before review if needed.

The queue stops before the next modeled fee would cross the reviewed floor,
rather than sending cheaper cards out of order. Server rejections and uncertain
writes stop without retry. Stop/Escape finishes the current request and prevents
the next command. Both nations' cached decks and totals are discarded after an
attempted run. The shown bank afterward is explicitly an estimate; use Refresh
deck for current bank and deck value. Library callers must consume gift plans
and rescan as well. Transfers cannot be undone by Deckhand.

The maintainer has successfully gifted real cards using Deckhand. Automated
gifting tests use mocked HTTP, synthetic cards, and temporary credentials.

## Table sorting and deck overview

Click any card-table column heading to sort ascending; click it again to reverse.
Money and copy counts sort numerically, rarity follows its rarity order, and
missing values remain last. Sorting the display does not change the reviewed
cleanup quantities or the gift execution order. The main table shows estimated
market value per copy alongside bids and junk value. Values come from the live
deck response, remain in session snapshots, and are not stored as current prices
in the name catalog. Missing values display `-`.

The compact Bank and Deck value fields show the selected nation's public card
information. This adds one shared-rate-gated public request on first load,
refresh, preview, and after junking; returning to a session snapshot labels
its totals as cached. Refresh deck updates them. Failed reads show Unavailable.
Deck value is an estimate, not a guaranteed sale price.

About Deckhand also includes the Python version/implementation, interpreter
path, operating system, and the original Python process launch command. The
command is selectable text; it identifies the Python process rather than
reconstructing a parent PowerShell/Poetry launcher command.

Confirmation names accept capitalization and spaces in place of underscores;
they still must identify the selected sender/recipient. Inline field guidance
explains mismatches. Escape cancels without submitting a private command.

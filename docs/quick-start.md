# Quick start

Install Python 3.11+ and Poetry 2.2+. In the extracted project or checkout:

```console
poetry install --only main --no-interaction
poetry run deckhand --demo
```

Demo mode uses synthetic data, makes no network requests, and disables execution.
For the real application:

```console
poetry run deckhand
```

On Windows, `./Run-Deckhand.ps1 -Demo` installs runtime dependencies through
Poetry and starts demo mode; omit `-Demo` for the real app. The launcher requires
Poetry on PATH. From a built wheel, pip installation is also supported; Poetry is
the source checkout workflow, not an application runtime dependency.

1. Add each nation as a separate account; saving a password is optional.
2. Set a contact nation or email for the API User-Agent.
3. Select the maximum rarity and preview. Common is the initial cutoff;
   collection and sale-listing protections start enabled.
4. Review identities, seasons, copies, bids, junk values, and decisions.
5. Use Credentials to enter the selected account's password.
6. Choose Junk reviewed cards and type the exact selected nation name.

A bid strictly above junk value protects the card; an equal bid does not.
Market value and asks alone do not protect it. Runs are sequential and limited
to reviewed quantities. Stop allows the current request to finish and prevents
the next write. Junking is permanent; after an uncertain result, rescan instead
of retrying. A bid can change between the last read and execution.

Use a terminal at least 110 columns wide. Ctrl+S previews, Escape requests a
safe stop, and Ctrl+Q quits after work has stopped.

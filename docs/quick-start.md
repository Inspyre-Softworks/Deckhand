# Quick start

After preview, sale-review buttons appear if unprotected cards within the rarity
cutoff have bids equal to junk value or above it. Reviews list snapshot bids and
owned copies with links to market pages. Confirm the signed-in nation and current
price before matching a bid manually. Bids may disappear or cover fewer copies.
Reviewing does not send sale commands or consume the cleanup plan; preview again
after manual sales. No selling/auction command is documented in the API.

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

1. Open Manage nations, add a nation, and submit or cancel the immediate credential prompt.
2. Open API settings and save a contact nation or email for the API User-Agent.
3. Select the maximum rarity and preview. Common is the initial cutoff;
   collection and sale-listing protections start enabled.
4. Review identities, seasons, copies, bids, junk values, and decisions.
5. Use Manage nations > Set credentials to enter the selected account's password.
6. Choose Junk reviewed cards and type the exact selected nation name.

Selecting a nation loads its public deck automatically without unlocking stored
credentials. Cards show Not checked until you click Preview cleanup. Eligibility
filtering and junking stay disabled until a successful preview. Changing policy
keeps the cards visible and requires another preview.

During the same session, switching back restores that account's cached deck and
completed preview without network requests. The status shows the cache time.
Use Refresh deck for a fresh card list (clears eligibility), or Preview cleanup
for fresh protections and bids. Policy changes invalidate the cached preview;
cleanup consumes it and evicts the cached deck. Cache contents disappear on exit.

The selector above the table switches between All cards, Eligible cards, and
Ineligible cards. A visible count and empty-state message describe the current
view. This display filter does not alter the plan, eligible-copy total, or
execution confirmation. Rarity/protection changes still require a fresh preview.

A bid strictly above junk value protects the card; an equal bid does not.
Market value and asks alone do not protect it. Runs are sequential and limited
to reviewed quantities. Stop allows the current request to finish and prevents
the next write. Junking is permanent; after an uncertain result, rescan instead
of retrying. A bid can change between the last read and execution.

Use a terminal at least 110 columns wide. Ctrl+S previews, Escape requests a
safe stop, and Ctrl+Q quits after work has stopped.

Preview and junking progress now appear in dialogs with Stop buttons. Enter
submits single-line inputs. Select a card row and use Protect selected card to
save an exact name protection, then preview again. Appearance & help includes
optional flag colors and About Deckhand with both component versions.

Progress dialogs separate the current task, checked-card count, and estimated
time remaining. A quieter status line shows server waits or the next check;
Stop or Escape retains the same cooperative stop behavior.

The progress dialog centers headings above a recessed panel containing the
current status and progress bar, with counts and estimated time below.

For transfers, choose Gift cards, select another saved nation, and set the
sender's bank floor. Review the descending market-value list and fees, then type
both exact nation names to confirm. Cleanup-protected cards are included and
listed cards skipped. Stop/Escape ends after the current request. Refresh both
nations afterward; avoid other bank activity during gifting.

Click card-table headers to sort; a second click reverses the order. Market
value is shown per copy, and the selected nation's Bank and estimated Deck
value appear above the table. Returning to a session snapshot marks totals
cached; Refresh deck updates them. About includes runtime and startup details.

Nation-name confirmations accept ordinary capitalization and spaces as well as
the internal underscore form. Both gift fields must still match the selected
nations. Enter in the sender field advances to an empty recipient field; Enter
in the recipient field submits. Escape cancels confirmation. Card tables use
vertical separators to distinguish columns without affecting sorting.

Faster junking and gifting trust their reviewed queues and use only prepare/execute
commands during execution. Gifting tracks bank locally from reviewed balance
and fees; no live bank or ownership rechecks run. Refresh manually afterward.

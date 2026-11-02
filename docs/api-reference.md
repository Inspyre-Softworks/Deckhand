# Library reference

The supported top-level imports are Card, CardKey, Decision, Plan, Policy,
Rarity, NationStates, RateGate, Cleaner, and RunResult.

```python
import asyncio
from deckhand import Cleaner, NationStates, Policy, Rarity, RateGate

async def preview():
    gate = RateGate()
    async with NationStates("your_nation", "your_contact_nation", gate=gate) as api:
        plan = await Cleaner(api).preview(Policy(maximum=Rarity.RARE))
        for decision in plan.decisions:
            print(decision.card.key, decision.reason)
        print(plan.copies, plan.proceeds)

asyncio.run(preview())
```

This example performs public reads; it never authenticates or executes writes.
Provide a meaningful contact and share a RateGate among clients in one event
loop. Other processes on the same IP share the service's allowance.

| Object | Contract |
| --- | --- |
| CardKey(card_id, season) | Positive card identity and season; seasons are distinct |
| Card | Identity, rarity, copy count, optional name |
| Policy | Maximum rarity; collection/listing/own-nation protection enabled by default; own_nations, protected_names, protected_substrings tuples |
| Decision | Card, eligibility, reason, optional highest bid |
| Plan | Nation, policy, decisions, creation time; candidates/copies/proceeds properties |
| Cleaner.preview(policy, progress=None, stop=None, status=None, estimate=None) | Complete reviewed plan; cancellation rejects an incomplete preview |
| Cleaner.execute(plan, password, confirmed_nation=..., stop=None, progress=None, estimate=None) | Sequential revalidation and junking, capped to reviewed quantities |
| RunResult | Junked/skipped counters, proceeds, stopped flag |

Optional arguments after policy/plan/password are keyword-only. The UI handles
the optional estimate callback as `(completed_bid_checks, total_bid_checks,
estimated_seconds_remaining)`. It starts after deck/protection reads, excludes
cards that need no market lookup, and reports zero when checks finish.
The estimate uses the current gate spacing, pending delay, and smoothed HTTP
response duration. It is approximate and may change with server conditions.

The UI handles
confirmation and consumes its plan. Library callers must obtain explicit human
confirmation, prevent plan reuse, and demand a new preview after execution or an
uncertain outcome. execute does not enforce single use across calls.

APIError and UncertainExecution are in deckhand.api. An uncertain write must
stop execution without retrying. A rescan is required to reconcile state.
Settings and Account are in deckhand.storage; Vault is in deckhand.credentials.
Settings.policy_for(account) includes all configured nation names. Standalone
library callers should populate Policy.own_nations with their other nations;
Cleaner automatically includes the selected nation. Custom exact/contains name
rules apply during preview and standard-mode live execution revalidation.
Credential operations are synchronous; async frontends should offload blocking
work with asyncio.to_thread. Do not log credentials or private command data.

Execution optionally reports `(completed_copies, total_copies, estimated_seconds_remaining)`
through `estimate`. Completed copies include copies removed from consideration by
live protections or missing ownership. The TUI shows a countdown and copies left
after confirmation and unlock, revising for observed request timing and backoff.
Estimates are approximate; slow responses can extend the run. Stop, completion,
and errors clear the countdown.

## Persistent card catalog

`CardCatalog` is a top-level library export. Pass a catalog to
`NationStates(..., catalog=catalog)` to record validated deck and market metadata.
The TUI uses `cards.sqlite3` under its configuration directory automatically.

```python
from deckhand import CardCatalog

catalog = CardCatalog("cards.sqlite3")
by_name = catalog.lookup(name="Silver Harbour")
by_number = catalog.lookup(card_id=42)
one_season = catalog.lookup(card_id=42, season=3)
```

Supply exactly one of `name` or `card_id`; names match exactly after case and
space/underscore normalization. All known seasons are returned unless filtered.
Unknown cards return an empty list. `record(cards)` upserts by number and season;
an unnamed observation preserves a known name. Returned Cards have `copies=1`
as a metadata placeholder, never an ownership count. The catalog stores no bids,
credentials, eligibility, or account ownership. It is an incomplete, possibly
stale catalog of fetched cards and never replaces live cleanup checks.
Synchronous catalog operations can be offloaded with `asyncio.to_thread`.
Catalog write failures surface as APIError; lookup database failures are shown
in the lookup dialog. Demo mode leaves the catalog untouched.

## Execution check frequency

`Policy(fast_execution=True)` trusts the reviewed cleanup candidates and sends
only prepare/execute commands, without public revalidation reads. The default
`False` retains live per-copy checks, including the post-prepare market read.
Changing mode preserves the reviewed decisions. Both modes cap work to reviewed
identities/seasons/counts, require confirmation, support cooperative stop, and
never retry uncertain writes. Fast execution does not detect changed ownership,
bids, listings, names, or collections; its confirmation states this tradeoff.
ETA uses two requests per copy in fast mode.

## Quick deck loads and optional names

`NationStates.deck(resolve_names=False, stop=None)` returns live ownership with
names from the response or exact card-number/season catalog matches. By default,
it performs no extra network calls for missing names. Copy counts and rarity
always come from live ownership data.

`resolve_card_names(cards, stop=None, progress=None)` fetches missing names with
public `card info` reads. `progress(completed, total, card)` reports each completed
card, including cache hits. A cooperative stop returns the complete list with
partial names; untouched entries remain unchanged. Invalid/failed reads raise,
and callers can retain progress-callback results. Completed network lookups are
persisted immediately. `deck(resolve_names=True)` remains an explicit convenience
for loading and resolving together. `card_info(key)` returns validated metadata.

The TUI offers **Resolve card names** with a progress dialog. Cancel/Escape
cancels the public worker, including an in-flight request or rate wait, keeps
completed results, and closes the dialog. Failed lookups leave the dialog open
with a Close button and retain partial results. A later resolve skips known
names. Resolving invalidates any reviewed plan. Preview can independently fetch
market information required for cleanup safety; it does not require resolving
all display names first. Execution retains its live market name checks.

Custom API adapters passed to Cleaner should accept `stop` and `resolve_names`
keywords on `deck`. `CardCatalog.names_for(keys)` returns cached names for exact
identities without loading ownership or bids.

## Reviewed gifting

Top-level exports include `GiftItem`, `GiftPlan`, `GiftResult`, and `Gifter`.
`await Gifter(api).preview(recipient, minimum_bank, stop=None, progress=None)`
returns a read-only preview sorted by descending estimated market value, with
listed cards excluded and all other cleanup protections intentionally ignored.
Bank amounts and market values use Decimal. `GiftPlan.projected` returns the
estimated affordable copy count and remaining bank. `GiftPlan.copies` includes
all reviewed copies; execution may stop earlier at the floor.

`execute(plan, password, confirmed_source=..., confirmed_recipient=..., stop=None,
progress=None, estimate=None)` requires both exact nation confirmations. The
sender API nation must match the plan. Gifts run sequentially in the preview's
order using only prepare/execute requests, without additional public reads.
The floor is tracked locally as starting bank minus confirmed per-copy fees;
`GiftResult.bank` is an estimate, not a fresh server balance. External spending
and changed fees can violate the actual floor. A rejection or uncertain result
stops without retry. ETA uses two requests per remaining copy.

`progress(gifted, reviewed_copies, card)` reports confirmed writes;
`estimate(processed, reviewed_copies, seconds)` includes skipped copies and
uses the shared gate's timing. `GiftResult` contains gifted/skipped counts,
estimated bank, and reason. Cancellation is cooperative. Callers must prevent
plan reuse and invalidate both nations' deck snapshots after any attempted run.
The TUI restricts recipients to another saved nation and consumes its plan.

API methods: `bank()` reads public `cards info`; `gift_deck()` reads live
ownership and market values, fetching individual card information only when
market values are absent; `prepare_gift(key, recipient, password)` and
`execute_gift(key, recipient, token, pin)` implement the documented two-step
private command. Public reads never send private headers. Missing, nonfinite,
negative, conflicting, or ambiguous money data is rejected.

`Card.market_value` is optional Decimal snapshot metadata from a public deck
response. It is preserved through name resolution and previews, never used
instead of live bid/protection checks, and not persisted in the name catalog.
`NationStates.deck_totals()` returns `(bank, estimated_deck_value)` as Decimals
from a single public `cards info` read. Missing/ambiguous/nonfinite/negative
values fail closed. The frontend displays Unavailable if this read fails.

## Reusable progress windows

`deckhand.progress.ProgressWindow` provides the shared Textual modal layout and
its own `DEFAULT_CSS`, so it can be used without Deckhand's App stylesheet.
Centered headings sit above a recessed panel containing only status and a
full-width progress bar. Counts, ETA, request detail, and a quiet Stop/Cancel
footer remain outside the inset.

```python
import asyncio
from deckhand.progress import ProgressWindow

stop = asyncio.Event()
window = ProgressWindow(
    "Checking cards", on_stop=stop.set, status="Loading deck...",
    total=100, action_label="Stop", help_text="Stops after the current request.",
)
# Inside an async Textual handler or worker:
# await app.push_screen(window)
# window.update_progress(total=100, progress=25, unit="cards checked")
# window.set_status("Checking market bids")
# window.set_estimate("About 20s remaining")
# window.set_detail("Waiting for NationStates")
```

`on_stop` is a required synchronous callback that signals/cancels the caller's
worker. The base class does not own workers, perform requests, or decide whether
to stop immediately versus cooperatively. Stop and Escape disable the action
and invoke it once. The caller closes the modal when work ends.
`set_action("Close", callback)` can replace/reset the action after an error.
Pass `total=None` for indeterminate progress. Other constructor options include
`eyebrow`, `count`, and `estimate`.

`OperationProgress` and `NameResolution` in deckhand.tui subclass this base;
neither duplicates its composition or layout CSS. Name resolution retains
immediate cancellation and partial results; junking/gifting retain cooperative
stop and reviewed-queue execution.

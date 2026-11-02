# Architecture and safety

The Textual frontend consumes the same library interface as custom callers.

- models.py defines immutable card/policy/plan values and uses Decimal prices.
- api.py owns strict XML parsing, HTTP, rate limiting, and private commands.
- service.py separates preview from execution and applies the reviewed check frequency.
- storage.py persists account metadata with atomic writes.
- credentials.py selects explicit vault backends; hello.py handles native Passport.
- progress.py owns reusable modal progress layout, styling, and stop signaling.
- tui.py owns account switching, workers, confirmation, and plan invalidation.

Preview reads deck ownership, enabled protections, and relevant markets. Execution
checks the account and confirmation, limits work to reviewed candidates, refreshes
deck/protections/market per copy by default, prepares a private command, refreshes the bid,
and executes only if still eligible and not stopped.

The API offers no atomic conditional junk operation. A collection or bid can
change between reads and execution. A plan is not a transaction or an
authorization to retry a failed write. The service lock prevents concurrent runs
on one Cleaner; it is not a cross-process lock. RateGate coordinates requests
within one event loop and honors limit/retry headers.

Tests in test_core.py cover policy/API/execution, test_vault.py covers storage,
test_hello.py covers fake-provider envelopes, and test_tui.py covers headless UI.
Native OS credential integration remains a separate target-machine check.

Opt-in `Policy.fast_execution` trusts the reviewed queue and sends only
prepare/execute commands. Standard execution retains live per-copy checks.
Gifting likewise executes the reviewed queue without additional public reads,
with the bank floor tracked from reviewed bank minus confirmed fees. Review
limits, confirmation, stop handling, and uncertain-write no-retry behavior
remain in both paths.

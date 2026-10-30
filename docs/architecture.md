# Architecture and safety

The Textual frontend consumes the same library interface as custom callers.

- models.py defines immutable card/policy/plan values and uses Decimal prices.
- api.py owns strict XML parsing, HTTP, rate limiting, and private commands.
- service.py separates preview from execution and rechecks each reviewed copy.
- storage.py persists account metadata with atomic writes.
- credentials.py selects explicit vault backends; hello.py handles native Passport.
- tui.py owns account switching, workers, confirmation, and plan invalidation.

Preview reads deck ownership, enabled protections, and relevant markets. Execution
checks the account and confirmation, limits work to reviewed candidates, refreshes
deck/protections/market per copy, prepares a private command, refreshes the bid,
and executes only if still eligible and not stopped.

The API offers no atomic conditional junk operation. A collection or bid can
change between reads and execution. A plan is not a transaction or an
authorization to retry a failed write. The service lock prevents concurrent runs
on one Cleaner; it is not a cross-process lock. RateGate coordinates requests
within one event loop and honors limit/retry headers.

Tests in test_core.py cover policy/API/execution, test_vault.py covers storage,
test_hello.py covers fake-provider envelopes, and test_tui.py covers headless UI.
Native OS credential integration remains a separate target-machine check.

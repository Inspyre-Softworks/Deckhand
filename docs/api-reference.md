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
| Policy | Maximum rarity; collection/listing protection enabled by default |
| Decision | Card, eligibility, reason, optional highest bid |
| Plan | Nation, policy, decisions, creation time; candidates/copies/proceeds properties |
| Cleaner.preview(policy, progress=None, stop=None) | Complete reviewed plan; cancellation rejects an incomplete preview |
| Cleaner.execute(plan, password, confirmed_nation=..., stop=None, progress=None) | Sequential revalidation and junking, capped to reviewed quantities |
| RunResult | Junked/skipped counters, proceeds, stopped flag |

Optional arguments after policy/plan/password are keyword-only. The UI handles
confirmation and consumes its plan. Library callers must obtain explicit human
confirmation, prevent plan reuse, and demand a new preview after execution or an
uncertain outcome. execute does not enforce single use across calls.

APIError and UncertainExecution are in deckhand.api. An uncertain write must
stop execution without retrying. A rescan is required to reconcile state.
Settings and Account are in deckhand.storage; Vault is in deckhand.credentials.
Credential operations are synchronous; async frontends should offload blocking
work with asyncio.to_thread. Do not log credentials or private command data.

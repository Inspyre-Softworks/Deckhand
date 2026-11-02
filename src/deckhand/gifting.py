"""Reviewed, sequential gifts with local fee-budget accounting."""
import asyncio
from dataclasses import dataclass
from decimal import Decimal
import time
from .api import APIError
from .models import Card, nation_id


def amount(value):
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ValueError("Enter a finite, nonnegative bank amount")
    return value


@dataclass(frozen=True)
class GiftItem:
    card: Card
    market_value: Decimal

    def __post_init__(self):
        amount(self.market_value)

    @property
    def fee(self):
        return self.card.rarity.junk


@dataclass(frozen=True)
class GiftPlan:
    source: str
    recipient: str
    minimum_bank: Decimal
    starting_bank: Decimal
    items: tuple[GiftItem, ...]
    created: float
    listed_copies: int = 0

    def __post_init__(self):
        object.__setattr__(self, "source", nation_id(self.source))
        object.__setattr__(self, "recipient", nation_id(self.recipient))
        if self.source == self.recipient:
            raise ValueError("Select a different recipient nation")
        amount(self.minimum_bank)
        amount(self.starting_bank)
        items = tuple(self.items)
        if len({i.card.key for i in items}) != len(items):
            raise ValueError("Duplicate gift identities")
        object.__setattr__(self, "items", tuple(sorted(items, key=lambda i: (-i.market_value, i.card.key))))

    @property
    def copies(self):
        return sum(i.card.copies for i in self.items)

    @property
    def projected(self):
        bank, copies = self.starting_bank, 0
        for item in self.items:
            affordable = max(0, int((bank - self.minimum_bank) // item.fee))
            count = min(item.card.copies, affordable)
            bank -= count * item.fee
            copies += count
            if count < item.card.copies:
                break
        return copies, bank


@dataclass(frozen=True)
class GiftResult:
    gifted: int
    skipped: int
    bank: Decimal
    reason: str


class Gifter:
    """Callers confirm both nations, consume each plan, and rescan after a run."""
    def __init__(self, api):
        self.api = api
        self._lock = asyncio.Lock()

    async def preview(self, recipient, minimum_bank, *, stop=None, progress=None):
        recipient = nation_id(recipient)
        amount(minimum_bank)
        if recipient == self.api.nation:
            raise ValueError("Select a different recipient nation")
        items = await self.api.gift_deck(stop=stop, progress=progress)
        listed = await self.api.listings()
        bank = await self.api.bank()
        if stop and stop.is_set():
            raise APIError("Gift preview canceled")
        return GiftPlan(self.api.nation, recipient, minimum_bank, bank,
            tuple(i for i in items if i.card.key not in listed), time.time(),
            sum(i.card.copies for i in items if i.card.key in listed))

    async def execute(self, plan, password, *, confirmed_source, confirmed_recipient,
                      stop=None, progress=None, estimate=None):
        if self._lock.locked():
            raise ValueError("A gifting run is already active")
        if (plan.source != self.api.nation or confirmed_source != plan.source
            or confirmed_recipient != plan.recipient):
            raise ValueError("Gift confirmation does not match sender and recipient")
        if not password:
            raise ValueError("A sender password is required")
        gifted = skipped = 0
        bank = plan.starting_bank
        def result(reason):
            return GiftResult(gifted, skipped, bank, reason)
        def report_estimate():
            if estimate:
                gate = getattr(self.api, "gate", None)
                wait = max(0, getattr(gate, "next_request", 0) - time.monotonic())
                duration = getattr(gate, "interval", .65) + getattr(gate, "response_seconds", .25)
                remaining = plan.copies - gifted - skipped
                estimate(gifted + skipped, plan.copies, wait + remaining * 2 * duration if remaining else 0)
        async with self._lock:
            report_estimate()
            for item in plan.items:
                for _ in range(item.card.copies):
                    if stop and stop.is_set():
                        return result("Stopped")
                    if bank - item.fee < plan.minimum_bank:
                        return result("Reviewed bank floor reached")
                    token, pin = await self.api.prepare_gift(item.card.key, plan.recipient, password)
                    if stop and stop.is_set():
                        return result("Stopped")
                    await self.api.execute_gift(item.card.key, plan.recipient, token, pin)
                    gifted += 1
                    bank -= item.fee
                    if progress:
                        progress(gifted, plan.copies, item.card)
                    report_estimate()
            return result("Finished")

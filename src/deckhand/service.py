"""Planning and execution are separate, with per-copy revalidation."""
import asyncio
from dataclasses import dataclass
from decimal import Decimal
from .api import APIError
from .models import Card, Decision, Plan, decide


@dataclass(frozen=True)
class RunResult:
    junked: int
    skipped: int
    proceeds: Decimal
    stopped: bool


class Cleaner:
    def __init__(self, api):
        self.api = api
        self._run_lock = asyncio.Lock()

    async def protections(self, policy):
        collections = await self.api.collections() if policy.protect_collections else set()
        listings = await self.api.listings() if policy.protect_listings else set()
        return collections, listings

    async def preview(self, policy, *, progress=None, stop=None):
        deck = await self.api.deck()
        collections, listings = await self.protections(policy)
        decisions = []
        for index, card in enumerate(deck):
            if stop and stop.is_set():
                raise APIError("Preview canceled. Scan again to create a complete plan.")
            base = decide(card, policy, collections, listings, None)
            if base.eligible:
                rarity, bid, name = await self.api.market(card.key)
                if rarity != card.rarity:
                    raise APIError("Deck and market rarity disagree")
                card = Card(card.key, rarity, card.copies, name)
                base = decide(card, policy, collections, listings, bid)
            decisions.append(base)
            if progress:
                progress(index + 1, len(deck), base)
        return Plan.create(self.api.nation, policy, decisions)

    async def execute(self, plan, password, *, confirmed_nation, stop=None, progress=None):
        """Only reviewed candidates, capped to reviewed quantities. Never retry writes.

        Stop is cooperative: an in-flight execute is allowed to finish, and its
        outcome is reported. The API cannot atomically lock the order book.
        """
        if self._run_lock.locked():
            raise ValueError("A cleanup is already running")
        if plan.nation != self.api.nation or confirmed_nation != plan.nation:
            raise ValueError("Confirmation does not match the plan's nation")
        if not password:
            raise ValueError("A nation password is required")
        done = skipped = 0
        proceeds = Decimal(0)
        async with self._run_lock:
            for card in plan.candidates:
                for _ in range(card.copies):
                    if stop and stop.is_set():
                        return RunResult(done, skipped, proceeds, True)
                    deck = {c.key: c for c in await self.api.deck()}
                    current = deck.get(card.key)
                    if current is None:
                        skipped += 1
                        break
                    collections, listings = await self.protections(plan.policy)
                    rarity, bid, _ = await self.api.market(card.key)
                    if rarity != card.rarity or current.rarity != card.rarity:
                        raise APIError("Rarity changed; cleanup stopped")
                    decision = decide(current, plan.policy, collections, listings, bid)
                    if not decision.eligible:
                        skipped += 1
                        if progress:
                            progress(done, skipped, decision.reason)
                        break
                    if stop and stop.is_set():
                        return RunResult(done, skipped, proceeds, True)
                    token, pin = await self.api.prepare_junk(card.key, password)
                    # Refresh the bid after preparation as well, immediately before execute.
                    _, bid, _ = await self.api.market(card.key)
                    if bid is not None and bid > card.rarity.junk:
                        skipped += 1
                        break
                    if stop and stop.is_set():
                        return RunResult(done, skipped, proceeds, True)
                    await self.api.execute_junk(card.key, token, pin)
                    done += 1
                    proceeds += card.rarity.junk
                    if progress:
                        progress(done, skipped, f"Junked #{card.key.card_id} / S{card.key.season}")
        return RunResult(done, skipped, proceeds, False)

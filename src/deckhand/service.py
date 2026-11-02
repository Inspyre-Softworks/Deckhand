"""Planning and execution are separate, with selectable execution revalidation."""
import asyncio
from dataclasses import dataclass, replace
from decimal import Decimal
import time
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

    async def protections(self, policy, *, status=None):
        if status:
            status("Loading collection and sale-listing protections…")
        collections = await self.api.collections() if policy.protect_collections else set()
        listings = await self.api.listings() if policy.protect_listings else set()
        return collections, listings

    async def preview(self, policy, *, progress=None, stop=None, status=None, estimate=None):
        policy = replace(policy, own_nations=tuple(dict.fromkeys((*policy.own_nations, self.api.nation))))
        if status:
            status("Loading current deck…")
        deck = await self.api.deck(stop=stop)
        collections, listings = await self.protections(policy, status=status)
        market_total = sum(decide(card, policy, collections, listings, None).eligible for card in deck)
        market_current = 0
        def report_estimate(completed):
            if estimate:
                gate = getattr(self.api, "gate", None)
                spacing = getattr(gate, "interval", 0.65)
                response = getattr(gate, "response_seconds", 0.25)
                wait = max(0, getattr(gate, "next_request", 0) - time.monotonic())
                remaining = market_total - completed
                seconds = wait + remaining * (spacing + response) if remaining else 0
                estimate(completed, market_total, seconds)
        report_estimate(0)
        decisions = []
        for index, card in enumerate(deck):
            if stop and stop.is_set():
                raise APIError("Preview canceled. Scan again to create a complete plan.")
            base = decide(card, policy, collections, listings, None)
            if base.eligible:
                market_current += 1
                if status:
                    status(f"Checking bids: {market_current}/{market_total} unique cards…")
                rarity, bid, name = await self.api.market(card.key)
                report_estimate(market_current)
                if rarity != card.rarity:
                    raise APIError("Deck and market rarity disagree")
                card = replace(card, rarity=rarity, name=name)
                base = decide(card, policy, collections, listings, bid)
            decisions.append(base)
            if progress:
                progress(index + 1, len(deck), base)
        return Plan.create(self.api.nation, policy, decisions)

    async def execute(self, plan, password, *, confirmed_nation, stop=None, progress=None, estimate=None):
        """Only reviewed candidates, capped to reviewed quantities. Never retry writes.

        Stop is cooperative: an in-flight execute is allowed to finish, and its
        outcome is reported. Fast execution trusts the reviewed candidates and performs only prepare/execute
        commands. Standard execution retains live per-copy market/protection checks.
        The API cannot atomically lock the order book.
        """
        if self._run_lock.locked():
            raise ValueError("A cleanup is already running")
        if plan.nation != self.api.nation or confirmed_nation != plan.nation:
            raise ValueError("Confirmation does not match the plan's nation")
        if not password:
            raise ValueError("A nation password is required")
        plan = replace(plan, policy=replace(plan.policy,
            own_nations=(*plan.policy.own_nations, self.api.nation)))
        done = skipped = 0
        proceeds = Decimal(0)
        remaining = plan.copies
        requests_per_copy = (2 if plan.policy.fast_execution else
            5 + int(plan.policy.protect_collections) + int(plan.policy.protect_listings))

        def report_estimate():
            if estimate:
                gate = getattr(self.api, "gate", None)
                spacing = getattr(gate, "interval", 0.65)
                response = getattr(gate, "response_seconds", 0.25)
                wait = max(0, getattr(gate, "next_request", 0) - time.monotonic())
                seconds = wait + (remaining * requests_per_copy) * (spacing + response) if remaining else 0
                estimate(plan.copies - remaining, plan.copies, seconds)

        async with self._run_lock:
            report_estimate()
            if stop and stop.is_set():
                return RunResult(done, skipped, proceeds, True)
            for card in plan.candidates:
                for copy_index in range(card.copies):
                    if stop and stop.is_set():
                        return RunResult(done, skipped, proceeds, True)
                    if plan.policy.fast_execution:
                        token, pin = await self.api.prepare_junk(card.key, password)
                        if stop and stop.is_set():
                            return RunResult(done, skipped, proceeds, True)
                        await self.api.execute_junk(card.key, token, pin)
                    else:
                        deck = {c.key: c for c in await self.api.deck(resolve_names=False)}
                        current = deck.get(card.key)
                        if current is None:
                            skipped += 1
                            remaining -= card.copies - copy_index
                            report_estimate()
                            break
                        collections, listings = await self.protections(plan.policy)
                        rarity, bid, name = await self.api.market(card.key)
                        if rarity != card.rarity or current.rarity != card.rarity:
                            raise APIError("Rarity changed; cleanup stopped")
                        current = Card(current.key, current.rarity, current.copies, name)
                        decision = decide(current, plan.policy, collections, listings, bid)
                        if not decision.eligible:
                            skipped += 1
                            if progress:
                                progress(done, skipped, decision.reason)
                            remaining -= card.copies - copy_index
                            report_estimate()
                            break
                        if stop and stop.is_set():
                            return RunResult(done, skipped, proceeds, True)
                        token, pin = await self.api.prepare_junk(card.key, password)
                        # Refresh the bid after preparation as well, immediately before execute.
                        final_rarity, bid, name = await self.api.market(card.key)
                        final_card = Card(card.key, final_rarity, current.copies, name)
                        if final_rarity != card.rarity:
                            raise APIError("Rarity changed; cleanup stopped")
                        if not decide(final_card, plan.policy, collections, listings, bid).eligible:
                            skipped += 1
                            remaining -= card.copies - copy_index
                            report_estimate()
                            break
                        if stop and stop.is_set():
                            return RunResult(done, skipped, proceeds, True)
                        await self.api.execute_junk(card.key, token, pin)
                    done += 1
                    remaining -= 1
                    report_estimate()
                    proceeds += card.rarity.junk
                    if progress:
                        progress(done, skipped, f"Junked #{card.key.card_id} / S{card.key.season}")
        return RunResult(done, skipped, proceeds, False)

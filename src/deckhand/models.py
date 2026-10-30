from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum
import re
import time


def nation_id(value: str) -> str:
    value = value.strip().lower().replace(" ", "_")
    if not re.fullmatch(r"[a-z0-9_-]{1,80}", value):
        raise ValueError("Enter a NationStates nation name (letters, numbers, spaces, hyphens).")
    return value


class Rarity(IntEnum):
    COMMON = 0
    UNCOMMON = 1
    RARE = 2
    ULTRA_RARE = 3
    EPIC = 4
    LEGENDARY = 5

    @classmethod
    def parse(cls, value: str):
        return cls[value.strip().upper().replace("-", "_").replace(" ", "_")]

    @property
    def label(self):
        return self.name.replace("_", " ").title()

    @property
    def junk(self) -> Decimal:
        return tuple(map(Decimal, ("0.01", "0.05", "0.10", "0.20", "0.50", "1.00")))[self.value]


@dataclass(frozen=True, order=True)
class CardKey:
    card_id: int
    season: int

    def __post_init__(self):
        if self.card_id < 1 or self.season < 1:
            raise ValueError("Invalid card identity")


@dataclass(frozen=True)
class Card:
    key: CardKey
    rarity: Rarity
    copies: int = 1
    name: str = ""

    def __post_init__(self):
        if self.copies < 1:
            raise ValueError("Invalid copy count")


@dataclass(frozen=True)
class Policy:
    maximum: Rarity = Rarity.COMMON
    protect_collections: bool = True
    protect_listings: bool = True


@dataclass(frozen=True)
class Decision:
    card: Card
    eligible: bool
    reason: str
    highest_bid: Decimal | None = None


@dataclass(frozen=True)
class Plan:
    nation: str
    policy: Policy
    decisions: tuple[Decision, ...]
    created: float

    @classmethod
    def create(cls, nation, policy, decisions):
        return cls(nation_id(nation), policy, tuple(decisions), time.time())

    @property
    def candidates(self):
        return tuple(d.card for d in self.decisions if d.eligible)

    @property
    def copies(self):
        return sum(c.copies for c in self.candidates)

    @property
    def proceeds(self):
        return sum((c.rarity.junk * c.copies for c in self.candidates), Decimal(0))


def decide(card, policy, collections, listings, highest_bid):
    if card.rarity > policy.maximum:
        reason = "Above rarity cutoff"
    elif policy.protect_collections and card.key in collections:
        reason = "Protected collection"
    elif policy.protect_listings and card.key in listings:
        reason = "Listed for sale"
    elif highest_bid is not None and highest_bid > card.rarity.junk:
        reason = "Bid exceeds junk value"
    else:
        return Decision(card, True, "Eligible", highest_bid)
    return Decision(card, False, reason, highest_bid)

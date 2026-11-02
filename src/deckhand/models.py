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
    market_value: Decimal | None = None

    def __post_init__(self):
        if self.copies < 1:
            raise ValueError("Invalid copy count")
        if self.market_value is not None and (not isinstance(self.market_value, Decimal)
            or not self.market_value.is_finite() or self.market_value < 0):
            raise ValueError("Invalid market value")


@dataclass(frozen=True)
class Policy:
    maximum: Rarity = Rarity.COMMON
    protect_collections: bool = True
    protect_listings: bool = True
    protect_own_nations: bool = True
    own_nations: tuple[str, ...] = ()
    protected_names: tuple[str, ...] = ()
    protected_substrings: tuple[str, ...] = ()
    fast_execution: bool = False

    def __post_init__(self):
        if type(self.fast_execution) is not bool:
            raise ValueError("fast_execution must be a boolean")
        for field in ("own_nations", "protected_names", "protected_substrings"):
            values = tuple(dict.fromkeys(name_match(value) for value in getattr(self, field) if name_match(value)))
            object.__setattr__(self, field, values)


def name_match(value):
    return re.sub(r"[\s_]+", " ", value.strip().casefold())


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

    def sale_candidates(self, *, above_junk=False):
        """Reviewed cards with bids, excluding every non-bid protection."""
        return tuple(d for d in self.decisions
            if (d.eligible or d.reason == "Bid exceeds junk value")
            and d.highest_bid is not None
            and (d.highest_bid > d.card.rarity.junk if above_junk
                else d.highest_bid == d.card.rarity.junk))


def decide(card, policy, collections, listings, highest_bid):
    name = name_match(card.name)
    if card.rarity > policy.maximum:
        reason = "Above rarity cutoff"
    elif policy.protect_collections and card.key in collections:
        reason = "Protected collection"
    elif policy.protect_listings and card.key in listings:
        reason = "Listed for sale"
    elif policy.protect_own_nations and name and name in policy.own_nations:
        reason = "Protected own nation"
    elif name and name in policy.protected_names:
        reason = "Protected nation name"
    elif name and any(part in name for part in policy.protected_substrings):
        reason = "Protected name contains match"
    elif highest_bid is not None and highest_bid > card.rarity.junk:
        reason = "Bid exceeds junk value"
    else:
        return Decision(card, True, "Eligible", highest_bid)
    return Decision(card, False, reason, highest_bid)

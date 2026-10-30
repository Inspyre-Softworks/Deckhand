"""Small, strict API adapter. Public reads never send private credentials."""
import asyncio
from collections import Counter
from decimal import Decimal, InvalidOperation
import time
import httpx
from defusedxml import ElementTree as ET
from .models import Card, CardKey, Rarity, nation_id

ENDPOINT = "https://www.nationstates.net/cgi-bin/api.cgi"


class APIError(RuntimeError):
    pass


class UncertainExecution(APIError):
    """Execution may have succeeded; never automatically retry it."""


def required(root, path):
    node = root.find(path)
    if node is None:
        raise APIError(f"API response is missing {path}; refusing to guess.")
    return node


def value(root, path):
    result = required(root, path).text
    if result is None or not result.strip():
        raise APIError(f"API response has an empty {path}.")
    return result.strip()


def key_of(node):
    return CardKey(int(value(node, "CARDID")), int(value(node, "SEASON")))


class RateGate:
    """Share one gate across all account clients within a process/event loop."""
    def __init__(self, interval=1.0):
        self.interval = max(0.65, interval)
        self.next_request = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        await asyncio.sleep(max(0, self.next_request - time.monotonic()))
        self.next_request = time.monotonic() + self.interval

    def observe(self, headers):
        try:
            limit = float(headers.get("RateLimit-Limit", 0))
            reset = float(headers.get("RateLimit-Reset", 0))
            remaining = float(headers.get("RateLimit-Remaining", -1))
            if limit > 0 and reset > 0:
                self.interval = max(self.interval, reset / limit + 0.05)
            if remaining == 0:
                self.next_request = max(self.next_request, time.monotonic() + reset + 0.2)
            retry = float(headers.get("Retry-After", headers.get("X-Retry-After", 0)))
            self.next_request = max(self.next_request, time.monotonic() + retry)
        except (TypeError, ValueError):
            self.next_request = max(self.next_request, time.monotonic() + 30)


class NationStates:
    def __init__(self, nation, contact, *, gate=None, transport=None):
        self.nation = nation_id(nation)
        if not contact.strip() or any(c in contact for c in "\r\n"):
            raise ValueError("A contact nation or email is required for the API User-Agent.")
        self.gate = gate or RateGate()
        self._pin = None
        self.http = httpx.AsyncClient(
            headers={"User-Agent": f"Deckhand/0.1 (contact: {contact.strip()})"},
            timeout=30, follow_redirects=False, transport=transport,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self._pin = None
        await self.http.aclose()

    async def request(self, params, *, password=None, pin=None, execute=False):
        headers = {}
        if pin:
            headers["X-Pin"] = pin
        elif password:
            headers["X-Password"] = password
        method = "POST" if "c" in params else "GET"
        async with self.gate.lock:
            await self.gate.wait()
            try:
                response = await self.http.request(
                    method, ENDPOINT, headers=headers,
                    **({"data": params} if method == "POST" else {"params": params}),
                )
            except httpx.TransportError:
                if execute:
                    raise UncertainExecution("Connection lost during junking. Outcome unknown; rescan before continuing.") from None
                raise APIError("Could not contact NationStates. No junk command was sent.") from None
            self.gate.observe(response.headers)
            if response.status_code == 429:
                self.gate.next_request = max(self.gate.next_request, time.monotonic() + 30)
                raise APIError("NationStates rate limit reached. Wait before rescanning.")
            if response.status_code != 200:
                if execute:
                    raise UncertainExecution("Junk request returned an unexpected HTTP status. Rescan; do not retry automatically.")
                raise APIError(f"NationStates returned HTTP {response.status_code}.")
            try:
                root = ET.fromstring(response.content)
                if root.tag == "ERROR" or root.find(".//ERROR") is not None:
                    # Do not echo arbitrary server content into logs containing secrets.
                    raise APIError("NationStates rejected the request. Check the account and current card state.")
                return root, response.headers.get("X-Pin")
            except APIError:
                raise
            except Exception:
                if execute:
                    raise UncertainExecution("Unrecognized junk response. Outcome unknown; rescan before continuing.") from None
                raise APIError("Malformed API response; no cleanup will proceed.") from None

    async def public(self, q, **params):
        root, _ = await self.request({"q": q, **params})
        return root

    async def deck(self):
        root = await self.public("cards deck", nationname=self.nation)
        deck = required(root, "DECK")
        cards = {}
        counts = Counter()
        for node in deck:
            if node.tag != "CARD":
                raise APIError("Unexpected deck entry")
            key = key_of(node)
            rarity = Rarity.parse(value(node, "CATEGORY"))
            if key in cards and cards[key].rarity != rarity:
                raise APIError("Conflicting rarity in deck")
            cards[key] = Card(key, rarity, name=node.findtext("NAME", ""))
            counts[key] += 1  # API emits one CARD per copy.
        return [Card(k, c.rarity, counts[k], c.name) for k, c in cards.items()]

    async def collections(self):
        root = await self.public("cards collections", nationname=self.nation)
        keys = set()
        for item in required(root, "COLLECTIONS"):
            collection_id = int(value(item, "COLLECTIONID"))
            result = await self.public("cards collection", collectionid=collection_id)
            collection = required(result, "COLLECTION")
            if nation_id(value(collection, "NATION")) != self.nation:
                raise APIError("Collection owner did not match selected nation")
            keys.update(key_of(c) for c in required(collection, "DECK"))
        return keys

    async def listings(self):
        root = await self.public("cards asksbids", nationname=self.nation)
        return {key_of(item) for item in required(root, "ASKS")}

    async def market(self, key):
        root = await self.public("card info markets", cardid=key.card_id, season=key.season)
        if root.tag != "CARD" or key_of(root) != key:
            raise APIError("Card identity did not match the market request")
        rarity = Rarity.parse(value(root, "CATEGORY"))
        prices = []
        for market in required(root, "MARKETS"):
            kind = value(market, "TYPE")
            if kind not in ("bid", "ask"):
                raise APIError("Unrecognized market order type")
            try:
                price = Decimal(value(market, "PRICE"))
                if not price.is_finite() or price < 0:
                    raise ValueError()
            except (InvalidOperation, ValueError):
                raise APIError("Unrecognized market price") from None
            if kind == "bid":
                prices.append(price)
        return rarity, max(prices, default=None), value(root, "NAME")

    async def prepare_junk(self, key, password):
        root, pin = await self.request({"nation": self.nation, "c": "junkcard",
            "cardid": key.card_id, "season": key.season, "mode": "prepare"}, password=password, pin=self._pin)
        success = root if root.tag == "SUCCESS" else required(root, "SUCCESS")
        token = success.text.strip() if success.text else ""
        if not token:
            raise APIError("NationStates did not provide an execution token.")
        self._pin = pin or self._pin
        if not self._pin:
            raise APIError("NationStates did not provide an execution PIN.")
        return token, self._pin

    async def execute_junk(self, key, token, pin):
        root, _ = await self.request({"nation": self.nation, "c": "junkcard",
            "cardid": key.card_id, "season": key.season, "mode": "execute", "token": token},
            pin=pin, execute=True)
        if root.tag != "SUCCESS" and root.find("SUCCESS") is None:
            raise UncertainExecution("Junk response was not a confirmed success. Rescan before continuing.")

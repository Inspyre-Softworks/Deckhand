"""Small, strict API adapter. Public reads never send private credentials."""
import asyncio
from collections import Counter
from dataclasses import replace
from decimal import Decimal, InvalidOperation
import time
import math
import sqlite3
from urllib.parse import urlsplit, urljoin
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


def money(text):
    try:
        amount = Decimal(text)
        if not amount.is_finite() or amount < 0:
            raise ValueError()
        return amount
    except (InvalidOperation, ValueError):
        raise APIError("Unrecognized card money value") from None


def optional_money(root, path):
    nodes = root.findall(path)
    if len(nodes) > 1:
        raise APIError(f"Ambiguous {path}")
    return money(value(root, path)) if nodes else None


class RateGate:
    """Share one gate across all account clients within a process/event loop."""
    def __init__(self, interval=0.65):
        self.interval = max(0.65, interval)
        self.minimum_interval = self.interval
        self.response_seconds = 0.25
        self.on_request = None
        self.next_request = 0.0
        self.lock = asyncio.Lock()

    async def wait(self, on_wait=None):
        while (delay := self.next_request - time.monotonic()) > 0:
            if on_wait:
                on_wait(delay)
            await asyncio.sleep(min(delay, 1.0))
        self.next_request = time.monotonic() + self.interval

    def observe(self, headers):
        try:
            limit = float(headers.get("RateLimit-Limit", 0))
            reset = float(headers.get("RateLimit-Reset", 0))
            remaining = float(headers.get("RateLimit-Remaining", -1))
            retry = float(headers.get("Retry-After", headers.get("X-Retry-After", 0)))
            if not all(math.isfinite(n) for n in (limit, reset, remaining, retry)):
                raise ValueError("Non-finite rate header")
            if limit < 0 or reset < 0 or remaining < -1 or retry < 0:
                raise ValueError("Invalid rate header")
            if limit > 0 and reset > 0:
                self.interval = max(self.minimum_interval, reset / limit + 0.05,
                    reset / remaining + 0.05 if remaining > 0 else 0)
                self.next_request = max(self.next_request, time.monotonic() + self.interval)
            if remaining == 0:
                self.next_request = max(self.next_request, time.monotonic() + reset + 0.2)
            self.next_request = max(self.next_request, time.monotonic() + retry)
        except (TypeError, ValueError):
            self.next_request = max(self.next_request, time.monotonic() + 30)


class NationStates:
    def __init__(self, nation, contact, *, gate=None, transport=None, status=None, catalog=None):
        self.nation = nation_id(nation)
        if not contact.strip() or any(c in contact for c in "\r\n"):
            raise ValueError("A contact nation or email is required for the API User-Agent.")
        self.gate = gate or RateGate()
        self._pin = None
        self.status = status
        self.catalog = catalog
        self._card_names = {}
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
        # Fixed labels keep private request data out of status messages.
        label = {
            "cards deck": "Loading deck", "cards collections": "Loading collection list",
            "cards collection": "Loading collection contents", "cards asksbids": "Loading sale listings",
            "card info markets": "Checking market bids",
            "card info": "Loading card name",
        }.get(params.get("q"), "Sending private command" if "c" in params else "Reading API data")
        def report(message):
            if self.status:
                self.status(message)
        headers = {}
        if pin:
            headers["X-Pin"] = pin
        elif password:
            headers["X-Password"] = password
        method = "POST" if "c" in params else "GET"
        report(f"{label} - waiting for API request slot...")
        async with self.gate.lock:
            await self.gate.wait(lambda delay: report(
                f"{label} - rate-limit pacing: waiting {delay:.1f}s"))
            report(f"{label} - waiting for NationStates response...")
            started = time.monotonic()
            try:
                if self.gate.on_request:
                    self.gate.on_request()
                response = await self.http.request(
                    method, ENDPOINT, headers=headers,
                    **({"data": params} if method == "POST" else {"params": params}),
                )
            except httpx.TransportError:
                if execute:
                    raise UncertainExecution("Connection lost during card command. Outcome unknown; rescan before continuing.") from None
                raise APIError("Could not contact NationStates. No junk command was sent.") from None
            elapsed = max(0, time.monotonic() - started)
            self.gate.response_seconds = 0.7 * self.gate.response_seconds + 0.3 * elapsed
            self.gate.observe(response.headers)
            report(f"{label} - response received")
            if response.status_code == 429:
                self.gate.next_request = max(self.gate.next_request, time.monotonic() + 30)
                raise APIError("NationStates rate limit reached. Wait before rescanning.")
            if response.status_code != 200:
                if execute:
                    raise UncertainExecution("Card command returned an unexpected HTTP status. Rescan; do not retry automatically.")
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
                    raise UncertainExecution("Unrecognized card command response. Outcome unknown; rescan before continuing.") from None
                raise APIError("Malformed API response; no cleanup will proceed.") from None

    async def public(self, q, **params):
        root, _ = await self.request({"q": q, **params})
        return root

    async def remember_cards(self, cards):
        if self.catalog is not None:
            try:
                await asyncio.to_thread(self.catalog.record, cards)
            except (OSError, sqlite3.Error):
                raise APIError("Could not update the local card catalog.") from None

    async def deck(self, *, resolve_names=False, stop=None):
        """Load live ownership plus cached names; network name resolution is opt-in."""
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
            name = node.findtext("NAME", "").strip()
            previous = cards.get(key)
            if previous and previous.name and name and previous.name != name:
                raise APIError("Conflicting names in deck")
            market_value = optional_money(node, "MARKET_VALUE")
            if previous and previous.market_value != market_value:
                raise APIError("Conflicting market values in deck")
            cards[key] = Card(key, rarity, name=name or (previous.name if previous else ""), market_value=market_value)
            counts[key] += 1  # API emits one CARD per copy.
        result = [replace(c, copies=counts[k]) for k, c in cards.items()]
        await self.remember_cards(result)
        if resolve_names:
            return await self.resolve_card_names(result, stop=stop)
        known = await self.cached_names(cards)
        return [replace(c, name=c.name or known.get(c.key, "")) for c in result]

    async def cached_names(self, keys):
        known = dict(self._card_names)
        if self.catalog is not None:
            try:
                known.update(await asyncio.to_thread(self.catalog.names_for, keys))
            except (OSError, sqlite3.Error):
                raise APIError("Could not read the local card catalog.") from None
        return known

    async def resolve_card_names(self, cards, *, stop=None, progress=None):
        """Resolve names sequentially; return partial results on cooperative stop.

        progress(completed, total, card) reports each completed card, including
        cache hits. Callers can retain these results if a later read fails.
        """
        result = list(cards)
        known = await self.cached_names(c.key for c in result)
        total = len(result)
        for index, card in enumerate(result):
            if stop and stop.is_set():
                break
            name = card.name or known.get(card.key, "")
            market_value = card.market_value
            if not name:
                label = f"Resolving card names: {index + 1}/{total}"
                if self.status:
                    self.status(label)
                info = await self.card_info(card.key)
                if info.rarity != card.rarity:
                    raise APIError("Deck and card information rarity disagree")
                name = info.name
                if market_value is None:
                    market_value = info.market_value
            resolved = replace(card, name=name, market_value=market_value)
            result[index] = resolved
            self._card_names[card.key] = name
            if progress:
                progress(index + 1, total, resolved)
        return result

    async def card_info(self, key):
        """Read validated public metadata, without requesting market orders."""
        root = await self.public("card info", cardid=key.card_id, season=key.season)
        if root.tag != "CARD" or key_of(root) != key:
            raise APIError("Card identity did not match the information request")
        card = Card(key, Rarity.parse(value(root, "CATEGORY")), name=value(root, "NAME"),
            market_value=optional_money(root, "MARKET_VALUE"))
        await self.remember_cards([card])
        self._card_names[key] = card.name
        return card

    async def flag_image(self):
        """Read this nation's public flag and download a bounded same-site image."""
        root = await self.public("flag", nation=self.nation)
        if root.tag != "NATION" or nation_id(root.get("id", "")) != self.nation:
            raise APIError("Flag response did not match selected nation")
        url = urljoin("https://www.nationstates.net/", value(root, "FLAG"))
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in ("nationstates.net", "www.nationstates.net")
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or not parsed.path.startswith("/images/flags/") or parsed.query or parsed.fragment):
            raise APIError("Unrecognized flag image location")
        async with self.gate.lock:
            await self.gate.wait()
            if self.gate.on_request:
                self.gate.on_request()
            try:
                async with self.http.stream("GET", url) as response:
                    self.gate.observe(response.headers)
                    if response.status_code != 200:
                        raise APIError("Could not load the flag image")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 2_000_000:
                            raise APIError("Flag image exceeds the size limit")
                    return bytes(data)
            except httpx.TransportError:
                raise APIError("Could not load the flag image") from None

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
        name = value(root, "NAME")
        await self.remember_cards([Card(key, rarity, name=name)])
        return rarity, max(prices, default=None), name

    async def deck_totals(self):
        """Read current bank and estimated deck value with one public request."""
        root = await self.public("cards info", nationname=self.nation)
        if root.tag != "CARDS" or len(root.findall("INFO")) != 1:
            raise APIError("Missing or ambiguous deck information")
        info = required(root, "INFO")
        bank = optional_money(info, "BANK")
        deck_value = optional_money(info, "DECK_VALUE")
        if bank is None or deck_value is None:
            raise APIError("Deck information is missing bank or deck value")
        return bank, deck_value

    async def bank(self):
        root = await self.public("cards info", nationname=self.nation)
        if root.tag != "CARDS" or len(root.findall("INFO/BANK")) != 1:
            raise APIError("Missing or ambiguous card bank balance")
        return money(value(root, "INFO/BANK"))

    async def gift_deck(self, *, stop=None, progress=None):
        """Fresh ownership and market values, independent of cleanup eligibility."""
        from .gifting import GiftItem
        root = await self.public("cards deck", nationname=self.nation)
        if root.tag != "CARDS":
            raise APIError("Unexpected card deck response")
        cards, prices, counts = {}, {}, Counter()
        for node in required(root, "DECK"):
            if node.tag != "CARD":
                raise APIError("Unexpected deck entry")
            key = key_of(node)
            card = Card(key, Rarity.parse(value(node, "CATEGORY")), name=node.findtext("NAME", "").strip())
            if len(node.findall("MARKET_VALUE")) > 1:
                raise APIError("Ambiguous card market value")
            price = money(value(node, "MARKET_VALUE")) if node.find("MARKET_VALUE") is not None else None
            if key in cards and (cards[key].rarity != card.rarity or prices[key] != price):
                raise APIError("Conflicting card data in gift deck")
            cards[key], prices[key] = card, price
            counts[key] += 1
        # Establish the catalog table without storing ownership/market values.
        await self.remember_cards(cards.values())
        names = await self.cached_names(cards)
        result = []
        for index, (key, card) in enumerate(cards.items(), 1):
            if stop and stop.is_set():
                raise APIError("Gift preview canceled")
            price = prices[key]
            name = card.name or names.get(key, "")
            if price is None:
                info = await self.public("card info", cardid=key.card_id, season=key.season)
                if info.tag != "CARD" or key_of(info) != key or Rarity.parse(value(info, "CATEGORY")) != card.rarity:
                    raise APIError("Card information disagrees with gift deck")
                if len(info.findall("MARKET_VALUE")) != 1:
                    raise APIError("Missing or ambiguous card market value")
                price, name = money(value(info, "MARKET_VALUE")), value(info, "NAME")
            card = Card(key, card.rarity, counts[key], name)
            await self.remember_cards([card])
            result.append(GiftItem(card, price))
            if progress:
                progress(index, len(cards), card)
        return result

    async def prepare_gift(self, key, recipient, password):
        recipient = nation_id(recipient)
        if recipient == self.nation:
            raise ValueError("Select a different recipient nation")
        root, pin = await self.request({"nation": self.nation, "c": "giftcard",
            "cardid": key.card_id, "season": key.season, "to": recipient, "mode": "prepare"},
            password=password, pin=self._pin)
        success = root if root.tag == "SUCCESS" else required(root, "SUCCESS")
        token = success.text.strip() if success.text else ""
        if not token or not (pin or self._pin):
            raise APIError("Gift preparation did not return a token and PIN")
        self._pin = pin or self._pin
        return token, self._pin

    async def execute_gift(self, key, recipient, token, pin):
        recipient = nation_id(recipient)
        if recipient == self.nation:
            raise ValueError("Select a different recipient nation")
        root, _ = await self.request({"nation": self.nation, "c": "giftcard",
            "cardid": key.card_id, "season": key.season, "to": recipient,
            "mode": "execute", "token": token}, pin=pin, execute=True)
        if root.tag != "SUCCESS" and root.find("SUCCESS") is None:
            raise UncertainExecution("Gift was not a confirmed success. Rescan both decks; do not retry.")

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

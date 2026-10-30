import asyncio
from decimal import Decimal as D
import httpx
import pytest
from deckhand import Card, CardKey, Cleaner, NationStates, Plan, Policy, Rarity
from deckhand.models import decide
from deckhand.api import APIError, RateGate, UncertainExecution

KEY = CardKey(10, 4)


@pytest.mark.parametrize("bid,eligible", [(None, True), (D('0.009'), True), (D('0.01'), True), (D('0.0101'), False)])
def test_bid_comparison(bid, eligible):
    assert decide(Card(KEY, Rarity.COMMON), Policy(), set(), set(), bid).eligible == eligible


def test_protections_and_cutoff():
    card = Card(KEY, Rarity.COMMON)
    assert not decide(card, Policy(), {KEY}, set(), None).eligible
    assert not decide(card, Policy(), set(), {KEY}, None).eligible
    assert decide(card, Policy(protect_collections=False, protect_listings=False), {KEY}, {KEY}, None).eligible
    assert not decide(Card(KEY, Rarity.RARE), Policy(), set(), set(), None).eligible
    assert decide(Card(KEY, Rarity.RARE), Policy(Rarity.RARE), set(), set(), None).eligible


class FakeAPI:
    nation = 'alpha'
    def __init__(self):
        self.cards = [Card(KEY, Rarity.COMMON, 2)]
        self.bid = None
        self.collection = set()
        self.listed = set()
        self.writes = 0
        self.prepared = 0
        self.raise_after_prepare = False
        self.uncertain = False

    async def deck(self): return self.cards
    async def collections(self): return self.collection
    async def listings(self): return self.listed
    async def market(self, key): return Rarity.COMMON, self.bid, 'Card'
    async def prepare_junk(self, key, password):
        self.prepared += 1
        if self.raise_after_prepare:
            self.bid = D('1')
        return 'token', 'pin'
    async def execute_junk(self, key, token, pin):
        self.writes += 1
        if self.uncertain:
            raise UncertainExecution('Unknown')


async def test_preview_readonly_and_copy_cap():
    api = FakeAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy())
    assert plan.copies == 2 and plan.proceeds == D('.02') and api.writes == 0
    api.cards = [Card(KEY, Rarity.COMMON, 5), Card(CardKey(20,4), Rarity.COMMON)]
    result = await cleaner.execute(plan, 'secret', confirmed_nation='alpha')
    assert result.junked == 2 and api.writes == 2


@pytest.mark.parametrize('changed', ['bid', 'collection', 'listed'])
async def test_revalidation_skips_new_protection(changed):
    api = FakeAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy())
    if changed == 'bid': api.bid = D('.02')
    elif changed == 'collection': api.collection = {KEY}
    else: api.listed = {KEY}
    result = await cleaner.execute(plan, 'secret', confirmed_nation='alpha')
    assert result.junked == api.writes == 0


async def test_bid_rises_after_prepare():
    api = FakeAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy())
    api.raise_after_prepare = True
    result = await cleaner.execute(plan, 'secret', confirmed_nation='alpha')
    assert result.junked == api.writes == 0 and api.prepared == 1


async def test_wrong_account_and_stop():
    api = FakeAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy())
    with pytest.raises(ValueError):
        await cleaner.execute(plan, 'secret', confirmed_nation='beta')
    other = Plan.create('beta', plan.policy, plan.decisions)
    with pytest.raises(ValueError):
        await cleaner.execute(other, 'secret', confirmed_nation='beta')
    stop = asyncio.Event(); stop.set()
    result = await cleaner.execute(plan, 'secret', confirmed_nation='alpha', stop=stop)
    assert result.stopped and api.writes == 0


async def test_uncertain_execution_stops_without_retry():
    api = FakeAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy())
    api.uncertain = True
    with pytest.raises(UncertainExecution):
        await cleaner.execute(plan, 'secret', confirmed_nation='alpha')
    assert api.writes == 1


def client(xml, *, headers=None, status=200):
    def respond(request):
        return httpx.Response(status, text=xml, headers=headers, request=request)
    return NationStates('alpha', 'contact_nation', transport=httpx.MockTransport(respond))


async def test_deck_duplicates_and_seasons():
    card = '<CARD><CARDID>10</CARDID><SEASON>{}</SEASON><CATEGORY>common</CATEGORY></CARD>'
    async with client('<CARDS><DECK>'+card.format(1)*2+card.format(2)+'</DECK></CARDS>') as api:
        deck = await api.deck()
        assert [c.copies for c in deck] == [2,1]
        assert deck[0].key != deck[1].key


@pytest.mark.parametrize('xml', ['<CARDS/>', '<CARDS><ERROR>private details</ERROR></CARDS>', '<html>',
    '<!DOCTYPE a [<!ENTITY x SYSTEM "file:///secrets">]><CARDS>&x;</CARDS>'])
async def test_fail_closed_xml(xml):
    async with client(xml) as api:
        with pytest.raises(APIError): await api.deck()


@pytest.mark.parametrize('price', ['NaN', 'Infinity', '-1', 'oops'])
async def test_bad_prices(price):
    xml = f'<CARD><CARDID>10</CARDID><SEASON>4</SEASON><CATEGORY>common</CATEGORY><NAME>A</NAME><MARKETS><MARKET><TYPE>bid</TYPE><PRICE>{price}</PRICE></MARKET></MARKETS></CARD>'
    async with client(xml) as api:
        with pytest.raises(APIError): await api.market(KEY)


async def test_private_two_step_and_public_no_auth():
    requests = []
    def respond(request):
        requests.append(request)
        if request.method == 'GET': return httpx.Response(200, text='<CARDS><DECK/></CARDS>')
        return httpx.Response(200, text='<NATION><SUCCESS>token</SUCCESS></NATION>', headers={'X-Pin':'pin'})
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(respond)) as api:
        api.gate.interval = 0
        token, pin = await api.prepare_junk(KEY, 'secret')
        await api.execute_junk(KEY, token, pin)
        await api.deck()
    assert requests[0].headers['X-Password'] == 'secret'
    assert requests[1].headers['X-Pin'] == 'pin' and 'X-Password' not in requests[1].headers
    assert 'X-Pin' not in requests[2].headers and 'X-Password' not in requests[2].headers
    assert all('secret' not in str(r.url) for r in requests)


async def test_timeout_execute_uncertain():
    def respond(request): raise httpx.ReadTimeout('hidden', request=request)
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(respond)) as api:
        with pytest.raises(UncertainExecution): await api.execute_junk(KEY, 'token', 'pin')


async def test_session_pin_reused_for_subsequent_prepares():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, text='<SUCCESS>token</SUCCESS>',
            headers={'X-Pin':'pin'} if len(requests) == 1 else {})
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(respond)) as api:
        api.gate.interval = 0
        await api.prepare_junk(KEY, 'secret')
        token, pin = await api.prepare_junk(KEY, 'secret')
    assert pin == 'pin'
    assert requests[1].headers['X-Pin'] == 'pin'
    assert 'X-Password' not in requests[1].headers


def test_rate_headers():
    gate = RateGate()
    gate.observe({'RateLimit-Limit': '10', 'RateLimit-Reset':'30', 'RateLimit-Remaining':'0'})
    assert gate.interval >= 3 and gate.next_request > 0

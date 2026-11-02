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


@pytest.mark.parametrize('name,policy,reason', [
    ('MY_NATION', Policy(own_nations=('My Nation',)), 'Protected own nation'),
    ('Friend Nation', Policy(protected_names=('friend_nation',)), 'Protected nation name'),
    ('New Silver Harbour', Policy(protected_substrings=('SILVER_',)), 'Protected name contains match'),
])
def test_name_protections(name, policy, reason):
    result = decide(Card(KEY, Rarity.COMMON, 3, name), policy, set(), set(), None)
    assert not result.eligible and result.reason == reason


def test_name_protections_can_be_disabled_and_exact_names_are_exact():
    assert decide(Card(KEY, Rarity.COMMON, name='Alpha'),
        Policy(protect_own_nations=False, own_nations=('alpha',)), set(), set(), None).eligible
    assert decide(Card(KEY, Rarity.COMMON, name='New Alpha'),
        Policy(protected_names=('alpha',), protected_substrings=('', '  ')), set(), set(), None).eligible


def test_sale_groups_preserve_all_protections_and_exact_price_comparison():
    policy = Policy(own_nations=('alpha',), protected_names=('friend',),
        protected_substrings=('harbour',))
    cases = [
        ('Equal', Rarity.COMMON, D('.01'), set(), set()),
        ('Higher', Rarity.COMMON, D('.0101'), set(), set()),
        ('Lower', Rarity.COMMON, D('.0099'), set(), set()),
        ('No bid', Rarity.COMMON, None, set(), set()),
        ('Alpha', Rarity.COMMON, D('1'), set(), set()),
        ('Friend', Rarity.COMMON, D('.01'), set(), set()),
        ('New Harbour', Rarity.COMMON, D('1'), set(), set()),
        ('Rare', Rarity.RARE, D('1'), set(), set()),
        ('Collection', Rarity.COMMON, D('1'), {KEY}, set()),
        ('Listing', Rarity.COMMON, D('.01'), set(), {KEY}),
    ]
    decisions = [decide(Card(KEY, rarity, 2, name), policy, collections, listings, bid)
        for name, rarity, bid, collections, listings in cases]
    plan = Plan.create('alpha', policy, decisions)
    assert [d.card.name for d in plan.sale_candidates()] == ['Equal']
    assert [d.card.name for d in plan.sale_candidates(above_junk=True)] == ['Higher']


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

    async def deck(self, **kwargs): return self.cards
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


async def test_missing_deck_name_resolves_to_protected_own_nation():
    api = FakeAPI()

    async def market(key):
        return Rarity.COMMON, None, 'ALPHA'

    api.market = market
    plan = await Cleaner(api).preview(Policy())
    assert plan.copies == 0 and plan.decisions[0].reason == 'Protected own nation'


@pytest.mark.parametrize('after_prepare', [False, True])
async def test_live_market_name_protection_prevents_execution(after_prepare):
    api = FakeAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy(protected_substrings=('friend',)))

    async def market(key):
        name = 'Old Friend' if not after_prepare or api.prepared else 'Ordinary Nation'
        return Rarity.COMMON, None, name

    api.market = market
    result = await cleaner.execute(plan, 'test-only', confirmed_nation='alpha')
    assert result.junked == api.writes == 0
    assert api.prepared == int(after_prepare)


@pytest.mark.parametrize('failure', [False, True])
async def test_api_counter_counts_attempts_including_transport_failure(failure):
    calls = []

    def respond(request):
        if failure:
            raise httpx.ConnectError('test-only', request=request)
        return httpx.Response(200, text='<CARDS><DECK/></CARDS>')

    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(respond)) as api:
        api.gate.on_request = lambda: calls.append(1)
        if failure:
            with pytest.raises(APIError):
                await api.deck()
        else:
            await api.deck()
    assert calls == [1]


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
        deck = await api.deck(resolve_names=False)
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


async def test_rate_wait_countdown_and_shared_budget(monkeypatch):
    now = [100.0]
    waits = []
    monkeypatch.setattr('deckhand.api.time.monotonic', lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    monkeypatch.setattr('deckhand.api.asyncio.sleep', sleep)
    gate = RateGate()
    starts = []
    for _ in range(51):
        await gate.wait()
        starts.append(now[0])
    assert starts[50] - starts[0] >= 30
    gate.observe({'RateLimit-Limit': '50', 'RateLimit-Remaining': '2',
        'RateLimit-Reset': '10'})
    assert gate.interval >= 5
    await gate.wait(waits.append)
    assert len(waits) >= 5 and waits[0] > waits[-1] > 0
    gate.observe({'RateLimit-Limit': '50', 'RateLimit-Remaining': '49',
        'RateLimit-Reset': '30'})
    assert gate.interval < 0.7
    gate.observe({'Retry-After': '12'})
    before = now[0]
    await gate.wait()
    assert now[0] - before >= 12


@pytest.mark.parametrize('headers', [{'Retry-After': 'NaN'}, {'RateLimit-Reset': '-1'},
    {'RateLimit-Remaining': 'oops'}])
def test_invalid_rate_headers_back_off(headers, monkeypatch):
    monkeypatch.setattr('deckhand.api.time.monotonic', lambda: 100.0)
    gate = RateGate()
    gate.observe(headers)
    assert gate.next_request >= 130


async def test_request_status_has_waits_and_no_secrets(monkeypatch):
    now = [100.0]
    messages = []
    monkeypatch.setattr('deckhand.api.time.monotonic', lambda: now[0])

    async def sleep(delay):
        now[0] += delay

    monkeypatch.setattr('deckhand.api.asyncio.sleep', sleep)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text='<SUCCESS/>'))
    async with NationStates('alpha', 'contact', transport=transport, status=messages.append) as api:
        api.gate.next_request = 102
        await api.execute_junk(KEY, 'private-token', 'private-pin')
    assert any('waiting 2.0s' in m for m in messages)
    assert any('waiting for NationStates response' in m for m in messages)
    assert not any('private-token' in m or 'private-pin' in m for m in messages)


async def test_preview_reports_stages_before_market_requests():
    stages = []
    api = FakeAPI()
    original_market = api.market

    async def market(key):
        assert stages[-1] == 'Checking bids: 1/1 unique cards…'
        return await original_market(key)

    api.market = market
    plan = await Cleaner(api).preview(Policy(), status=stages.append)
    assert stages[:2] == ['Loading current deck…', 'Loading collection and sale-listing protections…']
    assert plan.copies == 2


async def test_preview_estimate_counts_market_checks_and_backoff(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('deckhand.service.time.monotonic', lambda: now[0])
    api = FakeAPI()
    api.gate = RateGate()
    api.cards += [Card(CardKey(11, 4), Rarity.COMMON), Card(CardKey(12, 4), Rarity.EPIC)]
    estimates = []
    original_market = api.market

    async def market(key):
        api.gate.interval = 10
        api.gate.next_request = now[0] + 20
        return await original_market(key)

    api.market = market
    await Cleaner(api).preview(Policy(), estimate=lambda *args: estimates.append(args))
    assert estimates[0][:2] == (0, 2)  # Copies and above-cutoff cards do not inflate ETA.
    assert estimates[1][:2] == (1, 2)
    assert estimates[1][2] > estimates[0][2]  # New backoff revises ETA upward.
    assert estimates[-1] == (2, 2, 0)


async def test_empty_preview_estimate():
    api = FakeAPI()
    api.cards = []
    estimates = []
    await Cleaner(api).preview(Policy(), estimate=lambda *args: estimates.append(args))
    assert estimates == [(0, 0, 0)]


@pytest.mark.parametrize("mode", ["junk", "missing", "protected", "after_prepare"])
async def test_execution_estimate_tracks_all_reviewed_copies(mode):
    api = FakeAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy())
    if mode == "missing":
        api.cards = []
    elif mode == "protected":
        api.bid = D("1")
    elif mode == "after_prepare":
        api.raise_after_prepare = True
    estimates = []
    result = await cleaner.execute(plan, "test-only", confirmed_nation="alpha",
        estimate=lambda *args: estimates.append(args))
    assert estimates[0][:2] == (0, 2)
    assert estimates[0][2] > 0
    assert estimates[-1] == (2, 2, 0)
    assert result.junked == (2 if mode == "junk" else 0)


class CountingAPI(FakeAPI):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def deck(self, **kwargs):
        self.calls.append('deck')
        return await super().deck()

    async def collections(self):
        self.calls.append('collections')
        return await super().collections()

    async def listings(self):
        self.calls.append('listings')
        return await super().listings()

    async def market(self, key):
        self.calls.append('market')
        return await super().market(key)

    async def prepare_junk(self, key, password):
        self.calls.append('prepare')
        return await super().prepare_junk(key, password)

    async def execute_junk(self, key, token, pin):
        self.calls.append('execute')
        return await super().execute_junk(key, token, pin)


@pytest.mark.parametrize('fast', [False, True])
async def test_execution_mode_request_sequence(fast):
    api = CountingAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy(fast_execution=fast))
    api.calls.clear()
    estimates = []
    result = await cleaner.execute(plan, 'test', confirmed_nation='alpha',
        estimate=lambda *args: estimates.append(args))
    assert result.junked == 2
    if fast:
        assert api.calls == ['prepare', 'execute'] * 2
        assert estimates[0][2] == pytest.approx(4 * .9)
    else:
        assert api.calls == ['deck', 'collections', 'listings', 'market', 'prepare', 'market', 'execute'] * 2
    assert estimates[-1] == (2, 2, 0)


@pytest.mark.parametrize('owned', [0, 1, 5])
async def test_fast_execution_caps_to_review_without_reloading_ownership(owned):
    api = CountingAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy(fast_execution=True))
    api.cards = [Card(KEY, Rarity.COMMON, owned)] if owned else []
    api.cards.append(Card(CardKey(99, 2), Rarity.COMMON, 4))
    result = await cleaner.execute(plan, 'test', confirmed_nation='alpha')
    assert result.junked == api.writes == 2


async def test_fast_execution_performs_no_public_rechecks():
    api = CountingAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy(fast_execution=True))
    async def forbidden(*args, **kwargs):
        raise AssertionError('No public reads allowed after review')
    api.deck = api.collections = api.listings = api.market = forbidden
    result = await cleaner.execute(plan, 'synthetic', confirmed_nation='alpha')
    assert result.junked == 2 and api.prepared == api.writes == 2


async def test_fast_mode_ignores_later_protection_changes():
    api = CountingAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy(fast_execution=True))
    original = api.execute_junk
    async def execute(key, token, pin):
        await original(key, token, pin)
        api.collection.add(KEY)
        api.listed.add(KEY)
    api.execute_junk = execute
    result = await cleaner.execute(plan, 'test', confirmed_nation='alpha')
    assert result.junked == 2  # reviewed-queue execution ignores later protection changes


@pytest.mark.parametrize('failure', ['stop', 'uncertain', 'wrong_account', 'prepare_failure'])
async def test_fast_mode_stop_and_failure_contracts(failure):
    api = CountingAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy(fast_execution=True))
    api.calls.clear()
    stop = asyncio.Event()
    if failure == 'stop':
        original = api.prepare_junk
        async def prepare(key, password):
            response = await original(key, password)
            stop.set()
            return response
        api.prepare_junk = prepare
        result = await cleaner.execute(plan, 'test', confirmed_nation='alpha', stop=stop)
        assert result.stopped and api.writes == 0
    elif failure == 'wrong_account':
        with pytest.raises(ValueError):
            await cleaner.execute(plan, 'test', confirmed_nation='beta')
        assert api.calls == []
    else:
        if failure == 'uncertain':
            api.uncertain = True
        else:
            async def prepare(key, password):
                api.prepared += 1
                raise APIError('Preparation rejected')
            api.prepare_junk = prepare
        with pytest.raises(APIError):
            await cleaner.execute(plan, 'test', confirmed_nation='alpha')
        assert api.writes == (1 if failure == 'uncertain' else 0)
        assert api.prepared == 1


async def test_fast_mode_has_no_public_protection_reads():
    api = CountingAPI()
    cleaner = Cleaner(api)
    plan = await cleaner.preview(Policy(fast_execution=True, protect_collections=False, protect_listings=False))
    api.calls.clear()
    await cleaner.execute(plan, 'test', confirmed_nation='alpha')
    assert api.calls == ['prepare', 'execute'] * 2


async def test_deck_market_values_and_totals_are_decimal_and_public():
    def handle(request):
        assert 'X-Password' not in request.headers and 'X-Pin' not in request.headers
        if request.url.params['q'] == 'cards info':
            return httpx.Response(200, text='<CARDS><INFO><BANK>12.34</BANK><DECK_VALUE>99.99</DECK_VALUE></INFO></CARDS>')
        return httpx.Response(200, text='<CARDS><DECK><CARD><CARDID>10</CARDID><SEASON>4</SEASON><CATEGORY>common</CATEGORY><MARKET_VALUE>2.10</MARKET_VALUE></CARD></DECK></CARDS>')
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(handle)) as api:
        api.gate.interval = 0
        deck = await api.deck()
        assert deck[0].market_value == D('2.10')
        assert await api.deck_totals() == (D('12.34'), D('99.99'))


@pytest.mark.parametrize('price', ['NaN', '-1', 'Infinity'])
async def test_bad_deck_market_value_fails_closed(price):
    xml = f'<CARDS><DECK><CARD><CARDID>10</CARDID><SEASON>4</SEASON><CATEGORY>common</CATEGORY><MARKET_VALUE>{price}</MARKET_VALUE></CARD></DECK></CARDS>'
    async with client(xml) as api:
        with pytest.raises(APIError): await api.deck()

import asyncio
from dataclasses import replace
from decimal import Decimal as D
import httpx
import pytest
from deckhand import Card, CardKey, Rarity, Gifter, GiftItem, GiftPlan, NationStates
from deckhand.api import APIError, UncertainExecution


class GiftAPI:
    nation = 'alpha'
    def __init__(self):
        self.items = [GiftItem(Card(CardKey(1, 1), Rarity.LEGENDARY), D('100')),
            GiftItem(Card(CardKey(2, 2), Rarity.COMMON, 2), D('50')),
            GiftItem(Card(CardKey(3, 1), Rarity.RARE, 2), D('1'))]
        self.balance = D('1.15')
        self.listed = set()
        self.sent = []
        self.prepared = []
        self.on_prepare = None
        self.uncertain = False
    async def gift_deck(self, **kwargs): return self.items
    async def listings(self): return set(self.listed)
    async def bank(self): return self.balance
    async def deck(self, **kwargs): return [i.card for i in self.items if i.card.copies]
    async def prepare_gift(self, key, recipient, password):
        self.prepared.append((key, recipient))
        if self.on_prepare: self.on_prepare()
        return 'synthetic-token', 'synthetic-pin'
    async def execute_gift(self, key, recipient, token, pin):
        self.sent.append((key, recipient))
        if self.uncertain: raise UncertainExecution('test-only outcome unknown')
        for i, item in enumerate(self.items):
            if item.card.key == key:
                self.balance -= item.fee
                if item.card.copies == 1:
                    self.items.pop(i)
                else:
                    self.items[i] = replace(item, card=replace(item.card, copies=item.card.copies - 1))
                break


async def run(api, plan, **kwargs):
    return await Gifter(api).execute(plan, 'synthetic-password', confirmed_source='alpha',
        confirmed_recipient='beta', **kwargs)


async def test_gifts_descending_market_value_and_stops_before_floor():
    api = GiftAPI()
    api.items.reverse()
    plan = await Gifter(api).preview('beta', D('.10'))
    assert [i.market_value for i in plan.items] == [D('100'), D('50'), D('1')]
    assert plan.projected == (3, D('.13'))
    assert not api.prepared and not api.sent
    estimates = []
    result = await run(api, plan, estimate=lambda *args: estimates.append(args))
    assert result.gifted == 3 and result.bank == D('.13')
    assert result.reason == 'Reviewed bank floor reached'
    assert [key.card_id for key, _ in api.sent] == [1, 2, 2]
    assert all(target == 'beta' for _, target in api.sent)
    assert estimates[0][:2] == (0, 5)


async def test_exact_bank_floor_is_allowed_but_not_crossed():
    api = GiftAPI()
    api.items = [GiftItem(Card(CardKey(2, 2), Rarity.COMMON, 2), D('50'))]
    api.balance = D('.11')
    plan = await Gifter(api).preview('beta', D('.10'))
    result = await run(api, plan)
    assert result.gifted == 1 and result.bank == D('.10')


@pytest.mark.parametrize('change', ['bank', 'ownership', 'listing', 'stop'])
async def test_gift_stop_is_honored_but_live_changes_are_not_rechecked(change):
    api = GiftAPI()
    plan = await Gifter(api).preview('beta', D('.10'))
    stop = asyncio.Event()
    def changed():
        if change == 'bank': api.balance = D('.10')
        elif change == 'ownership': api.items = []
        elif change == 'listing': api.listed = {i.card.key for i in api.items}
        else: stop.set()
    api.on_prepare = changed
    await run(api, plan, stop=stop)
    assert len(api.sent) == (0 if change == 'stop' else 3)


async def test_listed_cards_excluded_and_new_inventory_never_added():
    api = GiftAPI()
    api.listed = {CardKey(1, 1)}
    plan = await Gifter(api).preview('beta', D('0'))
    assert plan.listed_copies == 1 and plan.copies == 4
    api.balance = D('100')
    api.items.append(GiftItem(Card(CardKey(99, 4), Rarity.LEGENDARY), D('9999')))
    result = await run(api, plan)
    assert result.gifted == 4
    assert len(api.sent) == 4 and all(k.card_id != 99 for k, _ in api.sent)


async def test_uncertain_gift_is_not_retried():
    api = GiftAPI()
    plan = await Gifter(api).preview('beta', D('0'))
    api.uncertain = True
    with pytest.raises(UncertainExecution): await run(api, plan)
    assert len(api.sent) == len(api.prepared) == 1


async def test_confirmation_requires_both_nations_and_nonempty_password():
    api = GiftAPI()
    gifter = Gifter(api)
    plan = await gifter.preview('beta', D('0'))
    for source, target, password in [('wrong', 'beta', 'test'), ('alpha', 'wrong', 'test'), ('alpha', 'beta', '')]:
        with pytest.raises(ValueError):
            await gifter.execute(plan, password, confirmed_source=source, confirmed_recipient=target)
    assert not api.prepared
    with pytest.raises(ValueError): await gifter.preview('alpha', D('0'))


@pytest.mark.parametrize('minimum', [D('-1'), D('NaN'), D('Infinity')])
async def test_bad_bank_floor_is_rejected(minimum):
    with pytest.raises(ValueError): await Gifter(GiftAPI()).preview('beta', minimum)


async def test_api_bank_values_and_gift_inventory():
    requests = []
    def handle(request):
        requests.append(request)
        q = request.url.params['q']
        assert 'X-Password' not in request.headers and 'X-Pin' not in request.headers
        if q == 'cards info': return httpx.Response(200, text='<CARDS><INFO><BANK>12.34</BANK></INFO></CARDS>')
        return httpx.Response(200, text='<CARDS><DECK>' + '<CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>rare</CATEGORY><MARKET_VALUE>99.10</MARKET_VALUE></CARD>' * 2 + '</DECK></CARDS>')
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(handle)) as api:
        api.gate.interval = 0
        assert await api.bank() == D('12.34')
        cards = await api.gift_deck()
        assert cards[0].card.copies == 2 and cards[0].market_value == D('99.10')
    assert len(requests) == 2


@pytest.mark.parametrize('xml', ['<CARDS><INFO/></CARDS>', '<CARDS><INFO><BANK>NaN</BANK></INFO></CARDS>',
    '<CARDS><INFO><BANK>-1</BANK></INFO></CARDS>', '<CARDS><INFO><BANK>1</BANK><BANK>2</BANK></INFO></CARDS>'])
async def test_bank_fails_closed(xml):
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(lambda r: httpx.Response(200, text=xml))) as api:
        with pytest.raises(APIError): await api.bank()


async def test_gift_api_two_step_and_recipient_binding():
    from urllib.parse import parse_qs
    seen = []
    def handle(request):
        params = parse_qs(request.content.decode())
        seen.append(params)
        assert params['to'] == ['beta'] and params['c'] == ['giftcard']
        if params['mode'] == ['prepare']:
            return httpx.Response(200, text='<SUCCESS>synthetic-token</SUCCESS>', headers={'X-Pin':'synthetic-pin'})
        assert 'X-Password' not in request.headers and request.headers['X-Pin'] == 'synthetic-pin'
        return httpx.Response(200, text='<SUCCESS>1</SUCCESS>')
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(handle)) as api:
        api.gate.interval = 0
        token, pin = await api.prepare_gift(CardKey(42, 1), 'beta', 'synthetic-password')
        await api.execute_gift(CardKey(42, 1), 'beta', token, pin)
    assert len(seen) == 2


@pytest.mark.parametrize('finish', ['send', 'cancel'])
async def test_gift_window_reviews_confirms_and_consumes_only_on_send(tmp_path, monkeypatch, finish):
    import deckhand.tui as tui
    from deckhand.storage import Settings, Account
    from deckhand import Plan, Policy
    from textual.widgets import Input, Static
    clients = []
    class Client(GiftAPI):
        def __init__(self, nation, contact, **kwargs):
            super().__init__()
            self.nation = nation
            self.gate = kwargs.get('gate')
            clients.append(self)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(tui, 'NationStates', Client)
    settings = Settings(tmp_path)
    settings.contact = 'contact'
    settings.add(Account('alpha', backend='session'))
    settings.add(Account('beta', backend='session'))
    review_ready, confirm_ready = asyncio.Event(), asyncio.Event()
    original = tui.GiftReview.on_mount
    def mounted(screen):
        original(screen)
        review_ready.set()
    monkeypatch.setattr(tui.GiftReview, 'on_mount', mounted)
    monkeypatch.setattr(tui.GiftConfirm, 'on_mount', lambda screen: confirm_ready.set(), raising=False)
    app = tui.Deckhand(settings=settings)
    async with app.run_test(size=(130, 50)) as pilot:
        await app.workers.wait_for_complete()
        app.vault.session[app.account.id] = 'synthetic-password'
        old_plan = Plan.create('alpha', Policy(), [])
        app.plan = old_plan
        app.plan_cache[app.account.id] = old_plan
        app.open_gifts()
        await pilot.pause()
        assert isinstance(app.screen, tui.GiftSetup)
        minimum = app.screen.query_one('#gift-minimum', Input)
        minimum.value = '.10'
        minimum.focus()
        await pilot.press('enter')
        await asyncio.wait_for(review_ready.wait(), 5)
        await pilot.pause()
        assert isinstance(app.screen, tui.GiftReview)
        assert not clients[-1].sent and not clients[-1].prepared
        if finish == 'cancel':
            await pilot.click('#cancel-gift-review')
            await app.workers.wait_for_complete()
            assert app.plan is old_plan and not clients[-1].sent
            return
        await pilot.click('#accept-gifts')
        await asyncio.wait_for(confirm_ready.wait(), 5)
        await pilot.pause()
        assert isinstance(app.screen, tui.GiftConfirm)
        source = app.screen.query_one('#gift-source-confirm', Input)
        target = app.screen.query_one('#gift-target-confirm', Input)
        source.value = 'alpha'
        target.value = 'wrong'
        target.focus()
        await pilot.press('enter')
        await pilot.pause()
        assert 'Both nation names' in str(app.screen.query_one('#gift-confirm-error', Static).render())
        assert not clients[-1].sent
        target.value = 'beta'
        await pilot.press('enter')
        await app.workers.wait_for_complete()
        await pilot.pause()
        sent_client = next(c for c in clients if c.sent)
        assert len(sent_client.sent) == 3
        assert all(target == 'beta' for _, target in sent_client.sent)
        assert sent_client.balance == D('.13')
        assert not app.busy and app.plan is None
        assert not any(a.id in app.deck_cache or a.id in app.plan_cache for a in settings.accounts)


async def test_gift_floor_uses_reviewed_balance_without_inventory_recheck():
    api = GiftAPI()
    plan = await Gifter(api).preview('beta', D('.10'))
    api.items = api.items[1:]
    api.balance = D('.12')
    result = await run(api, plan)
    assert result.gifted == 3 and result.bank == D('.13')
    assert [k.card_id for k, _ in api.sent] == [1, 2, 2]


@pytest.mark.parametrize('market', ['<MARKET_VALUE>1</MARKET_VALUE><MARKET_VALUE>2</MARKET_VALUE>', '<MARKET_VALUE>NaN</MARKET_VALUE>', '<MARKET_VALUE>-1</MARKET_VALUE>'])
async def test_gift_inventory_rejects_bad_or_ambiguous_values(market):
    xml = f'<CARDS><DECK><CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY>{market}</CARD></DECK></CARDS>'
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(lambda r: httpx.Response(200, text=xml))) as api:
        with pytest.raises(APIError): await api.gift_deck()


async def test_missing_deck_value_fetches_card_info_and_validates_identity():
    calls = []
    def handle(request):
        q = request.url.params['q']
        calls.append(q)
        if q == 'cards deck':
            return httpx.Response(200, text='<CARDS><DECK><CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY></CARD></DECK></CARDS>')
        return httpx.Response(200, text='<CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY><MARKET_VALUE>42.00</MARKET_VALUE><NAME>Resolved</NAME></CARD>')
    async with NationStates('alpha', 'contact', transport=httpx.MockTransport(handle)) as api:
        api.gate.interval = 0
        items = await api.gift_deck()
    assert calls == ['cards deck', 'card info']
    assert items[0].market_value == D('42') and items[0].card.name == 'Resolved'


async def test_gifting_execute_only_prepares_and_executes_reviewed_queue():
    api = GiftAPI()
    plan = await Gifter(api).preview('beta', D('.10'))
    async def forbidden(*args, **kwargs):
        raise AssertionError('Gifting must not perform additional reads')
    api.bank = api.deck = api.listings = api.gift_deck = forbidden
    result = await run(api, plan)
    assert result.gifted == 3 and result.bank == D('.13')
    assert len(api.sent) == len(api.prepared) == 3


async def test_gift_prepare_rejection_stops_without_retry():
    api = GiftAPI()
    plan = await Gifter(api).preview('beta', D('0'))
    attempts = []
    async def reject(*args):
        attempts.append(1)
        raise APIError('Gift preparation rejected')
    api.prepare_gift = reject
    with pytest.raises(APIError): await run(api, plan)
    assert attempts == [1] and api.sent == []

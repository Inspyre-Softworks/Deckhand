import httpx
import pytest
from deckhand import Card, CardCatalog, CardKey, NationStates, Rarity
from deckhand.api import APIError


def test_persistence_seasons_normalization_and_updates(tmp_path):
    path = tmp_path / "cards.sqlite3"
    catalog = CardCatalog(path)
    assert catalog.lookup(card_id=42) == []
    catalog.record([Card(CardKey(42, 1), Rarity.RARE, 9, "Silver Harbour"),
                    Card(CardKey(42, 2), Rarity.COMMON, name="Silver Harbour")])
    reopened = CardCatalog(path)
    assert len(reopened.lookup(name=" SILVER_harbour ")) == 2
    assert len(reopened.lookup(card_id=42, season=2)) == 1
    assert all(c.copies == 1 for c in reopened.lookup(card_id=42))
    reopened.record([Card(CardKey(42, 1), Rarity.EPIC)])
    assert reopened.lookup(card_id=42, season=1)[0].name == "Silver Harbour"
    reopened.record([Card(CardKey(42, 1), Rarity.EPIC, name="Renamed")])
    assert len(reopened.lookup(name="Silver Harbour")) == 1
    assert reopened.lookup(name="Renamed")[0].rarity == Rarity.EPIC
    assert reopened.lookup(name="Silver") == []
    assert reopened.lookup(name="' OR 1=1 --") == []


@pytest.mark.parametrize("kwargs", [{}, {"card_id": 0}, {"card_id": True},
    {"name": " "}, {"name": "a", "card_id": 1}, {"card_id": 1, "season": 0}])
def test_invalid_lookup(tmp_path, kwargs):
    with pytest.raises(ValueError):
        CardCatalog(tmp_path / "cards.sqlite3").lookup(**kwargs)


@pytest.mark.asyncio
async def test_public_reads_populate_catalog_and_market_stays_live(tmp_path):
    catalog = CardCatalog(tmp_path / "cards.sqlite3")
    requests = []
    def handle(request):
        requests.append(request)
        assert "X-Password" not in request.headers and "X-Pin" not in request.headers
        if request.url.params["q"] == "cards deck":
            return httpx.Response(200, text="<CARDS><DECK><CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY></CARD></DECK></CARDS>")
        return httpx.Response(200, text="<CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY><NAME>Alpha</NAME><MARKETS/></CARD>")
    async with NationStates("test", "contact", transport=httpx.MockTransport(handle), catalog=catalog) as api:
        await api.deck()
        await api.market(CardKey(42, 1))
        await api.market(CardKey(42, 1))
    assert len(requests) == 3
    assert catalog.lookup(name="alpha")[0].key == CardKey(42, 1)


@pytest.mark.asyncio
async def test_rejected_response_does_not_populate(tmp_path):
    catalog = CardCatalog(tmp_path / "cards.sqlite3")
    async with NationStates("test", "contact", catalog=catalog,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<CARD><CARDID>99</CARDID><SEASON>1</SEASON></CARD>"))) as api:
        with pytest.raises(APIError):
            await api.market(CardKey(42, 1))
    assert not catalog.path.exists()


@pytest.mark.asyncio
async def test_lookup_dialog(tmp_path):
    from deckhand.storage import Settings
    from deckhand.tui import CardLookup, Deckhand
    from textual.widgets import Input, Select, Static
    settings = Settings(tmp_path)
    app = Deckhand(settings=settings)
    app.catalog.record([Card(CardKey(42, 2), Rarity.RARE, name="Alpha")])
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.pause()
        app.query_one("#sidebar-content").scroll_end(animate=False)
        await pilot.pause()
        await pilot.click("#lookup-card")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CardLookup)
        screen.query_one("#lookup-query", Input).value = "ALPHA"
        await pilot.click("#lookup-search")
        await pilot.pause()
        assert "#42 / S2" in str(screen.query_one("#lookup-results", Static).render())
        screen.query_one("#lookup-kind", Select).value = "number"
        screen.query_one("#lookup-query", Input).value = "42"
        await pilot.click("#lookup-search")
        await pilot.pause()
        assert "Alpha" in str(screen.query_one("#lookup-results", Static).render())


@pytest.mark.asyncio
async def test_deck_resolves_all_names_then_reuses_catalog_across_clients(tmp_path):
    catalog = CardCatalog(tmp_path / 'cards.sqlite3')
    catalog.record([Card(CardKey(42, 1), Rarity.COMMON, name='Cached')])
    requests, statuses = [], []
    def handle(request):
        requests.append(request.url.params['q'])
        assert not any(h in request.headers for h in ('X-Password', 'X-Pin'))
        if request.url.params['q'] == 'cards deck':
            entries = ''.join(f'<CARD><CARDID>{number}</CARDID><SEASON>{season}</SEASON><CATEGORY>rare</CATEGORY>{name}</CARD>'
                for number, season, name in [(42, 1, ''), (42, 2, ''), (42, 2, ''), (99, 1, '<NAME>Supplied</NAME>')])
            return httpx.Response(200, text=f'<CARDS><DECK>{entries}</DECK></CARDS>')
        assert request.url.params['q'] == 'card info'
        assert request.url.params['season'] == '2'
        return httpx.Response(200, text='<CARD><CARDID>42</CARDID><SEASON>2</SEASON><CATEGORY>rare</CATEGORY><NAME>Fetched</NAME></CARD>')
    for _ in range(2):
        async with NationStates('test', 'contact', catalog=catalog, status=statuses.append,
            transport=httpx.MockTransport(handle)) as api:
            api.gate.interval = 0
            deck = await api.deck(resolve_names=True)
            assert [c.name for c in deck] == ['Cached', 'Fetched', 'Supplied']
            assert [c.copies for c in deck] == [1, 2, 1]
            assert all(c.rarity == Rarity.RARE for c in deck)  # live rarity, not cached rarity
    assert requests == ['cards deck', 'card info', 'cards deck']
    assert any('Resolving card names: 2/3' in status for status in statuses)
    assert catalog.lookup(card_id=42, season=2)[0].name == 'Fetched'


@pytest.mark.asyncio
async def test_execution_deck_read_skips_name_hydration():
    calls = []
    def handle(request):
        calls.append(request.url.params['q'])
        return httpx.Response(200, text='<CARDS><DECK><CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY></CARD></DECK></CARDS>')
    async with NationStates('test', 'contact', transport=httpx.MockTransport(handle)) as api:
        deck = await api.deck(resolve_names=False)
    assert calls == ['cards deck'] and deck[0].name == ''


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [
    '<CARD><CARDID>99</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY><NAME>Wrong</NAME></CARD>',
    '<CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY><NAME> </NAME></CARD>',
    '<CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>rare</CATEGORY><NAME>Different rarity</NAME></CARD>',
])
async def test_deck_rejects_unresolved_or_mismatched_information(payload):
    def handle(request):
        if request.url.params['q'] == 'cards deck':
            return httpx.Response(200, text='<CARDS><DECK><CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY></CARD></DECK></CARDS>')
        return httpx.Response(200, text=payload)
    async with NationStates('test', 'contact', transport=httpx.MockTransport(handle)) as api:
        api.gate.interval = 0
        with pytest.raises(APIError):
            await api.deck(resolve_names=True)


@pytest.mark.asyncio
async def test_name_resolution_cooperative_stop_between_requests():
    import asyncio
    stop = asyncio.Event()
    calls = []
    def handle(request):
        calls.append(request.url.params['q'])
        if request.url.params['q'] == 'cards deck':
            entries = ''.join(f'<CARD><CARDID>{i}</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY></CARD>' for i in (42, 43))
            return httpx.Response(200, text=f'<CARDS><DECK>{entries}</DECK></CARDS>')
        stop.set()
        return httpx.Response(200, text='<CARD><CARDID>42</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY><NAME>First</NAME></CARD>')
    async with NationStates('test', 'contact', transport=httpx.MockTransport(handle)) as api:
        api.gate.interval = 0
        cards = await api.deck(resolve_names=True, stop=stop)
        assert [c.name for c in cards] == ['First', '']
    assert calls == ['cards deck', 'card info']


@pytest.mark.asyncio
async def test_quick_deck_uses_cached_names_without_information_requests(tmp_path):
    catalog = CardCatalog(tmp_path / 'cards.sqlite3')
    catalog.record([Card(CardKey(42, 1), Rarity.COMMON, name='Cached')])
    calls = []
    def handle(request):
        calls.append(request.url.params['q'])
        entries = ''.join(f'<CARD><CARDID>{i}</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY></CARD>' for i in (42, 43))
        return httpx.Response(200, text=f'<CARDS><DECK>{entries}</DECK></CARDS>')
    async with NationStates('test', 'contact', catalog=catalog, transport=httpx.MockTransport(handle)) as api:
        cards = await api.deck()
    assert calls == ['cards deck']
    assert [c.name for c in cards] == ['Cached', '']


@pytest.mark.asyncio
@pytest.mark.parametrize('outcome', ['cancel', 'error'])
async def test_resolution_dialog_keeps_partial_results_and_resumes(tmp_path, monkeypatch, outcome):
    import asyncio
    import deckhand.tui as tui
    from deckhand.storage import Settings, Account
    from textual.widgets import Static, ProgressBar
    settings = Settings(tmp_path)
    settings.contact = 'contact'
    settings.add(Account('test'))
    second_started = asyncio.Event()
    block = asyncio.Event()
    calls = []
    first_run = True
    async def handle(request):
        nonlocal first_run
        q = request.url.params['q']
        calls.append((q, request.url.params.get('cardid')))
        assert request.method == 'GET'
        assert 'X-Password' not in request.headers and 'X-Pin' not in request.headers
        if q == 'cards info':
            return httpx.Response(200, text='<CARDS><INFO><BANK>1.15</BANK><DECK_VALUE>100</DECK_VALUE></INFO></CARDS>')
        if q == 'cards deck':
            entries = ''.join(f'<CARD><CARDID>{i}</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY></CARD>' for i in (42, 43))
            return httpx.Response(200, text=f'<CARDS><DECK>{entries}</DECK></CARDS>')
        number = int(request.url.params['cardid'])
        if number == 43 and first_run:
            second_started.set()
            if outcome == 'cancel':
                await block.wait()
            else:
                return httpx.Response(503)
        return httpx.Response(200, text=f'<CARD><CARDID>{number}</CARDID><SEASON>1</SEASON><CATEGORY>common</CATEGORY><NAME>Name {number}</NAME></CARD>')
    def client(*args, **kwargs):
        return NationStates(*args, **kwargs, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(tui, 'NationStates', client)
    app = tui.Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        app.gate.interval = 0
        await app.workers.wait_for_complete()
        assert sorted(calls) == sorted([('cards deck', None), ('cards info', None)])
        app.resolve_names()
        await asyncio.wait_for(second_started.wait(), 5)
        await pilot.pause()
        dialog = app.screen
        assert isinstance(dialog, tui.NameResolution)
        assert dialog.query_one('#progress', ProgressBar).progress == 1
        assert '1 / 2' in str(dialog.query_one('#operation-count', Static).render())
        await pilot.click('#operation-stop')
        await pilot.pause()
        assert not isinstance(app.screen, tui.NameResolution)
        assert not app.busy
        assert [c.name for c in app.deck] == ['Name 42', '']
        assert app.catalog.lookup(card_id=42)[0].name == 'Name 42'
        assert app.plan is None
        first_run = False
        app.resolve_names()
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert not isinstance(app.screen, tui.NameResolution)
        assert [c.name for c in app.deck] == ['Name 42', 'Name 43']
        assert sum(cardid == '42' for q, cardid in calls) == 1
        assert app.deck_cache[settings.accounts[0].id] == app.deck

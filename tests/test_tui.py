from textual.widgets import Button, Checkbox, DataTable, Select, Input
from deckhand.storage import Settings, Account
from deckhand.tui import Deckhand


async def test_demo_preview_and_filter_invalidation(tmp_path):
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        app.action_scan()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.plan.copies == 3
        assert app.query_one(DataTable).row_count == 6
        assert app.query_one('#execute', Button).disabled
        app.query_one('#collections', Checkbox).value = False
        await pilot.pause()
        assert app.plan is None


async def test_account_switch_invalidates_preview(tmp_path):
    settings = Settings(tmp_path)
    settings.add(Account('alpha'))
    settings.add(Account('beta', maximum='RARE', protect_collections=False))
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        app.plan = object()
        app.query_one('#accounts', Select).value = settings.accounts[1].id
        await pilot.pause()
        assert app.account.nation == 'beta' and app.plan is None
        assert app.query_one('#rarity', Select).value == 'RARE'
        assert not app.query_one('#collections', Checkbox).value


async def test_add_account_and_session_credential_modal(tmp_path):
    app = Deckhand(settings=Settings(tmp_path))
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        await pilot.click('#add-account')
        app.screen.query_one('#nation', Input).value = 'alpha'
        app.screen.query_one('#mode', Select).value = 'session'
        await pilot.click('#add')
        await pilot.pause()
        assert app.account.nation == 'alpha'
        await pilot.click('#credentials')
        await pilot.pause()
        app.screen.query_one('#secret', Input).value = 'test-only-password'
        await pilot.click('#continue')
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.vault.load(app.account) == 'test-only-password'
        assert not (tmp_path / 'credentials').exists()

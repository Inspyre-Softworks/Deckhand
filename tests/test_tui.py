from textual.widgets import Button, Checkbox, DataTable, Select, Input, Static, TextArea, Link, Label
from deckhand.storage import Settings, Account
from deckhand.tui import Deckhand
from deckhand.models import Plan
from deckhand import Card, CardKey, Rarity
import asyncio
import pytest
import time
from decimal import Decimal
from urllib.parse import urlparse, parse_qs


@pytest.fixture(autouse=True)
def public_deck_api(monkeypatch):
    class PublicAPI:
        deck_calls = []
        def __init__(self, nation, contact, **kwargs):
            self.nation = nation

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def deck(self, **kwargs):
            self.deck_calls.append(self.nation)
            return [Card(CardKey(10 if self.nation == 'alpha' else 20, 4),
                Rarity.COMMON, name=self.nation)]

    monkeypatch.setattr('deckhand.tui.NationStates', PublicAPI)
    return PublicAPI


async def test_session_cache_restores_preview_and_refreshes_on_request(tmp_path, monkeypatch, public_deck_api):
    from deckhand.tui import demo_plan
    previews = []

    async def preview(cleaner, policy, **kwargs):
        previews.append(cleaner.api.nation)
        return demo_plan(cleaner.api.nation, policy)

    monkeypatch.setattr('deckhand.tui.Cleaner.preview', preview)
    settings = Settings(tmp_path)
    settings.contact = 'contact'
    settings.add(Account('alpha'))
    settings.add(Account('beta'))
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        app.action_scan()
        await app.workers.wait_for_complete()
        plan = app.plan
        app.query_one('#card-filter', Select).value = 'eligible'
        await pilot.pause()
        accounts = app.query_one('#accounts', Select)
        accounts.value = settings.accounts[1].id
        await pilot.pause()
        await app.workers.wait_for_complete()
        accounts.value = settings.accounts[0].id
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert public_deck_api.deck_calls == ['alpha', 'beta']
        assert previews == ['alpha']
        assert app.plan is plan
        assert app.query_one(DataTable).row_count == 1
        assert app.query_one('#card-filter', Select).value == 'eligible'
        assert not app.query_one('#execute', Button).disabled
        assert 'Session cache' in str(app.query_one('#status', Static).render())
        app.refresh_deck()
        await app.workers.wait_for_complete()
        assert public_deck_api.deck_calls == ['alpha', 'beta', 'alpha']
        assert app.plan is None and settings.accounts[0].id not in app.plan_cache
        assert app.query_one('#execute', Button).disabled
        app.action_scan()
        await app.workers.wait_for_complete()
        assert previews == ['alpha', 'alpha']
        app.query_one('#collections', Checkbox).value = False
        await pilot.pause()
        assert app.plan is None
        accounts.value = settings.accounts[1].id
        await pilot.pause()
        accounts.value = settings.accounts[0].id
        await pilot.pause()
        assert app.plan is None
        assert not app.query_one('#collections', Checkbox).value
        assert public_deck_api.deck_calls == ['alpha', 'beta', 'alpha']


async def test_uncertain_execution_evicts_cached_plan(tmp_path, monkeypatch):
    from deckhand.tui import demo_plan
    from deckhand import Policy
    from deckhand.api import UncertainExecution
    settings = Settings(tmp_path)
    settings.contact = 'contact'
    settings.add(Account('alpha'))
    app = Deckhand(settings=settings)

    async def confirm(screen):
        return True

    async def execute(cleaner, *args, **kwargs):
        raise UncertainExecution('Rescan required')

    monkeypatch.setattr(app, 'push_screen_wait', confirm)
    monkeypatch.setattr('deckhand.tui.Cleaner.execute', execute)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        account = app.account
        app.plan = demo_plan(account.nation, Policy())
        app.plan_cache[account.id] = app.plan
        app.vault.session[account.id] = 'test-only'
        app.start_execution()
        await app.workers.wait_for_complete()
        assert app.plan is None
        assert account.id not in app.plan_cache and account.id not in app.deck_cache
        assert app.query_one('#execute', Button).disabled
        app.show_account()
        await app.workers.wait_for_complete()
        assert app.plan is None


async def test_preview_eta_updates_and_clears_on_stop(tmp_path):
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        await app.open_progress("Preview cleanup")
        app.preview_estimate(2, 10, 65)
        label = app.operation.query_one('#preview-eta', Static)
        assert '1m' in str(label.render())
        assert '2 / 10 cards checked' in str(app.operation.query_one('#operation-count', Static).render())
        app.eta_deadline = time.monotonic() - 1
        app.update_preview_eta()
        assert 'Taking longer' in str(label.render())
        app.set_busy(True)
        app.action_stop()
        assert app.eta_deadline is None and not str(label.render())
        app.set_busy(False)


async def test_name_rule_editor_and_session_lifetime_counts(tmp_path):
    settings = Settings(tmp_path)
    settings.add(Account('alpha'))
    settings.add(Account('beta'))
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.query_one('#own-nations', Checkbox).value
        assert app.policy().own_nations == ('alpha', 'beta')
        app.edit_name_rules()
        await pilot.pause()
        app.screen.query_one('#protected-names', TextArea).text = 'Friend Nation\n\nAnother Friend'
        app.screen.query_one('#protected-substrings', TextArea).text = 'Silver\nHarbour'
        await pilot.click('#save-rules')
        await pilot.pause()
        assert app.policy().protected_names == ('friend nation', 'another friend')
        assert app.policy().protected_substrings == ('silver', 'harbour')
        assert app.plan is None
        assert Settings(tmp_path).accounts[0].protected_names == ['Friend Nation', 'Another Friend']
        app.record_api_call()
        app.record_api_call()
        assert app.session_api_calls == 2 and app.total_api_calls == 2
        assert 'session: 2' in str(app.query_one('#api-counts', Static).render())
    restarted = Deckhand(settings=Settings(tmp_path))
    assert restarted.session_api_calls == 0 and restarted.total_api_calls == 2


async def test_conditional_sale_review_is_read_only(tmp_path):
    from deckhand import Policy
    from deckhand.models import decide
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert not app.query_one('#sale-actions').display
        policy = Policy()
        cards = [Card(CardKey(101, 4), Rarity.COMMON, 2, 'Equal'),
            Card(CardKey(102, 3), Rarity.COMMON, 1, 'Higher')]
        app.plan = Plan.create(app.account.nation, policy,
            [decide(card, policy, set(), set(), bid) for card, bid in
                zip(cards, (Decimal('.01'), Decimal('.02')))])
        plan = app.plan
        app.set_busy(False)
        await pilot.pause()
        assert app.query_one('#sale-actions').display
        assert app.query_one('#sell-equal', Button).display
        assert app.query_one('#sell-above', Button).display
        await pilot.click('#sell-above')
        await pilot.pause()
        links = list(app.screen.query(Link))
        assert len(links) == 1
        url = urlparse(links[0].url)
        assert url.path == '/page=deck/card=102/season=3'
        assert 'Deckhand' in parse_qs(url.query)['generated_by'][0]
        assert not any(key in url.query for key in ('token=', 'password=', 'pin='))
        await pilot.click('#close-sales')
        await pilot.pause()
        assert app.plan is plan and app.session_api_calls == 0
        app.set_busy(True)
        assert not app.query_one('#sale-actions').display
        app.set_busy(False)
        app.invalidate()
        assert not app.query_one('#sale-actions').display


async def test_demo_preview_and_filter_invalidation(tmp_path):
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.query_one(DataTable).row_count == 6
        assert app.plan is None
        assert app.query_one('#card-filter', Select).disabled
        app.action_scan()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.plan.copies == 3
        assert app.query_one(DataTable).row_count == 6
        assert app.query_one('#execute', Button).disabled
        app.query_one('#collections', Checkbox).value = False
        await pilot.pause()
        assert app.plan is None
        assert app.query_one(DataTable).row_count == 6
        assert app.query_one('#card-filter', Select).disabled


async def test_card_display_filter_preserves_reviewed_plan(tmp_path):
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        selector = app.query_one('#card-filter', Select)
        assert selector.disabled
        selector.value = 'eligible'  # A stale display choice cannot hide raw cards.
        await pilot.pause()
        assert app.query_one(DataTable).row_count == 6
        app.action_scan()
        await app.workers.wait_for_complete()
        await pilot.pause()
        plan = app.plan
        table = app.query_one(DataTable)
        assert table.row_count == 1
        assert table.get_row_at(0)[0] == '#101 / S4'
        # Use a non-demo execution state without issuing network requests.
        app.demo = False
        app.set_busy(False)
        assert not app.query_one('#execute', Button).disabled
        for mode, expected in [('ineligible', 5), ('all', 6), ('eligible', 1)]:
            selector.value = mode
            await pilot.pause()
            assert table.row_count == expected
            assert app.plan is plan and app.plan.copies == 3
            assert not app.query_one('#execute', Button).disabled
        app.plan = Plan.create(plan.nation, plan.policy, ())
        app.render_cards()
        assert table.row_count == 0
        assert 'No cards match' in str(app.query_one('#filter-count', Static).render())
        app.invalidate()
        selector.value = 'all'
        await pilot.pause()
        assert table.row_count == 6 and app.plan is None
        assert app.query_one('#execute', Button).disabled


async def test_account_switch_invalidates_preview(tmp_path):
    settings = Settings(tmp_path)
    settings.add(Account('alpha'))
    settings.add(Account('beta', maximum='RARE', protect_collections=False))
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.query_one(DataTable).get_row_at(0)[0] == '#10 / S4'
        assert app.plan is None and app.query_one('#execute', Button).disabled
        app.plan = object()
        app.query_one('#accounts', Select).value = settings.accounts[1].id
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.account.nation == 'beta' and app.plan is None
        assert app.query_one('#rarity', Select).value == 'RARE'
        assert not app.query_one('#collections', Checkbox).value
        assert app.query_one(DataTable).get_row_at(0)[0] == '#20 / S4'
        assert app.query_one('#card-filter', Select).disabled


async def test_stale_deck_load_cannot_replace_selected_nation(tmp_path, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    original = __import__('deckhand.tui', fromlist=['NationStates']).NationStates

    class SlowAPI(original):
        async def deck(self, **kwargs):
            if self.nation == 'alpha':
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()  # Simulate a late result despite cancellation.
            return await super().deck()

    monkeypatch.setattr('deckhand.tui.NationStates', SlowAPI)
    settings = Settings(tmp_path)
    settings.add(Account('alpha'))
    settings.add(Account('beta'))
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 44)) as pilot:
        await asyncio.wait_for(started.wait(), 2)
        app.query_one('#accounts', Select).value = settings.accounts[1].id
        await pilot.pause()
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.account.nation == 'beta'
        assert app.query_one(DataTable).get_row_at(0)[0] == '#20 / S4'
        assert app.plan is None


async def test_add_account_and_session_credential_modal(tmp_path):
    app = Deckhand(settings=Settings(tmp_path))
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        await pilot.click('#manage-fleet')
        await pilot.pause()
        await pilot.click('#add-account')
        await pilot.pause()
        app.screen.query_one('#nation', Input).value = 'alpha'
        app.screen.query_one('#mode', Select).value = 'session'
        await pilot.click('#add')
        await pilot.pause()
        assert app.account.nation == 'alpha'
        from deckhand.tui import SecretPrompt
        assert isinstance(app.screen, SecretPrompt)
        app.screen.query_one('#secret', Input).value = 'test-only-password'
        await pilot.click('#continue')
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.vault.load(app.account) == 'test-only-password'
        assert not (tmp_path / 'credentials').exists()


async def test_execution_eta_countdown_progress_and_stop(tmp_path):
    from textual.widgets import ProgressBar
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        app.set_busy(True)
        await app.open_progress("Junk reviewed cards")
        app.execution_estimate(1, 5, 65)
        label = app.operation.query_one("#preview-eta", Static)
        assert "1 / 5 copies processed" in str(app.operation.query_one("#operation-count", Static).render())
        assert "1m" in str(label.render())
        assert app.operation.query_one("#progress", ProgressBar).progress == 1
        app.execution_estimate(5, 5, 0)
        assert "finishing cleanup" in str(label.render())
        app.action_stop()
        app.execution_estimate(2, 5, 20)
        assert app.eta_deadline is None and not str(label.render())
        app.set_busy(False)


async def test_fast_execution_toggle_preserves_preview_and_restores_per_account(tmp_path, monkeypatch):
    from deckhand.tui import demo_plan, execution_mode_notice
    settings = Settings(tmp_path)
    settings.contact = 'contact'
    settings.add(Account('alpha'))
    settings.add(Account('beta'))
    async def preview(cleaner, policy, **kwargs):
        return demo_plan(cleaner.api.nation, policy)
    monkeypatch.setattr('deckhand.tui.Cleaner.preview', preview)
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        await app.workers.wait_for_complete()
        app.action_scan()
        await app.workers.wait_for_complete()
        assert app.plan and not app.plan.policy.fast_execution
        reviewed = app.plan
        app.query_one('#card-filter', Select).value = 'eligible'
        app.query_one('#fast-execution', Checkbox).value = True
        await pilot.pause()
        assert app.plan is not None
        assert app.plan.decisions is reviewed.decisions
        assert app.plan.created == reviewed.created
        assert app.plan.copies == reviewed.copies
        assert app.plan.proceeds == reviewed.proceeds
        assert app.query_one('#card-filter', Select).value == 'eligible'
        assert not app.query_one('#execute', Button).disabled
        assert app.plan_cache[settings.accounts[0].id] is app.plan
        assert app.plan.policy.fast_execution
        assert Settings(tmp_path).accounts[0].fast_execution
        assert 'Only prepare and execute' in execution_mode_notice(app.plan.policy)
        app.query_one('#accounts', Select).value = settings.accounts[1].id
        await pilot.pause()
        assert not app.query_one('#fast-execution', Checkbox).value
        app.query_one('#accounts', Select).value = settings.accounts[0].id
        await pilot.pause()
        assert app.query_one('#fast-execution', Checkbox).value


def test_ui_source_has_no_corrupted_punctuation():
    import ast
    import inspect
    import deckhand.api as api
    import deckhand.tui as tui
    # Specific signatures of UTF-8 punctuation incorrectly decoded as Windows-1252.
    broken = ("\u00c2\u00b7", "\u00e2\u20ac", "\u00e2\u2014")
    for module in (api, tui):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not any(marker in node.value for marker in broken), node.value


async def test_clean_labels_placeholders_and_conditional_fast_note(tmp_path):
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        assert str(app.query_one('#hero', Static).render()).startswith('DECKHAND')
        assert 'API calls - session:' in app.api_count_text()
        note = app.query_one('#fast-note', Static)
        assert not note.display
        app.query_one('#fast-execution', Checkbox).value = True
        await pilot.pause()
        assert note.display
        assert 'No live rechecks' in str(note.render())
        app.action_scan()
        await app.workers.wait_for_complete()
        assert 'faster execution selected' in str(app.query_one('#status', Static).render())
        app.query_one('#fast-execution', Checkbox).value = False
        await pilot.pause()
        assert not note.display
        app.deck = (Card(CardKey(123, 1), Rarity.COMMON),)
        app.plan = None
        app.render_cards()
        row = app.query_one('#cards', DataTable).get_row_at(0)
        assert str(row[1]) == '(unknown)'
        assert row[5] == '-'


async def test_api_settings_and_enter_submission(tmp_path):
    from deckhand.tui import APISettings
    settings = Settings(tmp_path)
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.click('#api-settings')
        await pilot.pause()
        assert isinstance(app.screen, APISettings)
        contact = app.screen.query_one('#contact', Input)
        contact.value = 'contact_nation'
        contact.focus()
        await pilot.press('enter')
        await pilot.pause()
        assert not isinstance(app.screen, APISettings)
        assert settings.contact == Settings(tmp_path).contact == 'contact_nation'
        assert not app.query('#contact')
        await pilot.click('#manage-fleet')
        await pilot.pause()
        await pilot.click('#add-account')
        await pilot.pause()
        app.screen.query_one('#mode', Select).value = 'session'
        nation = app.screen.query_one('#nation', Input)
        nation.value = 'alpha'
        nation.focus()
        await pilot.press('enter')
        await pilot.pause()
        from deckhand.tui import SecretPrompt
        assert isinstance(app.screen, SecretPrompt)
        secret = app.screen.query_one('#secret', Input)
        secret.value = 'synthetic-test-only'
        secret.focus()
        await pilot.press('enter')
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.vault.load(app.account) == 'synthetic-test-only'


async def test_about_shows_both_versions_and_main_has_no_progress_bar(tmp_path):
    from deckhand.tui import About, package_version
    from textual.widgets import ProgressBar
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 46)) as pilot:
        await pilot.pause()
        assert not app.query(ProgressBar)
        assert app.query_one('#protection-panel').border_title == 'Protections'
        app.query_one('#sidebar-content').scroll_end(animate=False)
        await pilot.pause()
        await pilot.click('#about')
        await pilot.pause()
        assert isinstance(app.screen, About)
        texts = '\n'.join(str(w.render()) for w in app.screen.query(Static))
        assert f'Deckhand TUI: {package_version()}' in texts
        assert f'Deckhand backend package: {package_version()}' in texts
        await pilot.press('escape')
        await pilot.pause()
        assert not isinstance(app.screen, About)


async def test_selected_card_is_saved_as_exact_protection(tmp_path):
    settings = Settings(tmp_path)
    settings.add(Account('alpha'))
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        await app.workers.wait_for_complete()
        table = app.query_one('#cards', DataTable)
        table.focus()
        await pilot.press('enter')
        await pilot.pause()
        assert not app.query_one('#protect-selected', Button).disabled
        app.protect_selected()
        await app.workers.wait_for_complete()
        assert 'alpha' in Settings(tmp_path).accounts[0].protected_names
        assert app.plan is None
        app.selected_card = app.deck[0]
        app.protect_selected()
        await app.workers.wait_for_complete()
        assert Settings(tmp_path).accounts[0].protected_names == ['alpha']


async def test_preview_progress_dialog_stop_button(tmp_path, monkeypatch):
    from deckhand.tui import OperationProgress
    from deckhand.api import APIError
    started = asyncio.Event()
    settings = Settings(tmp_path)
    settings.contact = 'contact'
    settings.add(Account('alpha'))
    async def preview(cleaner, policy, **kwargs):
        started.set()
        kwargs['estimate'](0, 3, 20)
        await kwargs['stop'].wait()
        raise APIError('Preview canceled')
    monkeypatch.setattr('deckhand.tui.Cleaner.preview', preview)
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        await app.workers.wait_for_complete()
        app.action_scan()
        await asyncio.wait_for(started.wait(), 3)
        await pilot.pause()
        assert isinstance(app.screen, OperationProgress)
        assert 'remaining' in str(app.screen.query_one('#preview-eta', Static).render())
        await pilot.click('#operation-stop')
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.stop_event.is_set() and not app.busy and app.plan is None
        assert not isinstance(app.screen, OperationProgress)


async def test_cached_names_are_shared_across_nations_and_session_snapshots(tmp_path):
    from deckhand import CardKey
    settings = Settings(tmp_path)
    settings.add(Account('alpha'))
    settings.add(Account('beta'))
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        await app.workers.wait_for_complete()
        key = CardKey(77, 4)
        app.deck_cache[settings.accounts[1].id] = (Card(key, Rarity.RARE, 3),)
        app.cache_times[settings.accounts[1].id] = time.time()
        # Another nation has learned this same card's name.
        app.catalog.record([Card(key, Rarity.RARE, name='Shared Nation')])
        app.query_one('#accounts', Select).value = settings.accounts[1].id
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.deck[0].name == 'Shared Nation' and app.deck[0].copies == 3
        assert str(app.query_one('#cards', DataTable).get_row_at(0)[1]) == 'Shared Nation'


async def test_flag_theme_cached_by_account_and_falls_back(tmp_path, monkeypatch, public_deck_api):
    from io import BytesIO
    from PIL import Image
    settings = Settings(tmp_path)
    settings.add(Account('alpha', flag_theme=True))
    settings.add(Account('beta'))
    data = BytesIO()
    Image.new('RGB', (8, 8), 'red').save(data, format='PNG')
    calls = []
    async def flag_image(api):
        calls.append(api.nation)
        return data.getvalue()
    monkeypatch.setattr(public_deck_api, 'flag_image', flag_image, raising=False)
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 46)) as pilot:
        await app.workers.wait_for_complete()
        red = app.query_one('#hero').styles.color
        assert calls == ['alpha']
        app.query_one('#accounts', Select).value = settings.accounts[1].id
        await pilot.pause()
        assert app.query_one('#hero').styles.color != red
        app.query_one('#accounts', Select).value = settings.accounts[0].id
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.query_one('#hero').styles.color == red
        assert calls == ['alpha']


async def test_progress_dialog_presents_task_and_quiet_request_state(tmp_path):
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(100, 36)) as pilot:
        await pilot.pause()
        await app.open_progress('Preview cleanup')
        app.preview_status('Checking bids: 23/56 unique cards...')
        app.request_status('Checking market bids - rate-limit pacing: waiting 0.6s')
        app.preview_estimate(23, 56, 31)
        dialog = app.operation
        assert str(dialog.query_one('#operation-title', Label).render()) == 'Checking your cards'
        assert str(dialog.query_one('#operation-status', Static).render()) == 'Checking market bids'
        assert str(dialog.query_one('#operation-request', Static).render()) == 'Next check in 0.6s'
        assert '23 / 56 cards checked' in str(dialog.query_one('#operation-count', Static).render())
        assert 'remaining' in str(dialog.query_one('#preview-eta', Static).render())
        assert dialog.query_one('#operation-stop', Button).variant == 'default'
        app.close_progress()


async def test_header_sort_is_numeric_reversible_and_retains_plan(tmp_path):
    from deckhand import Policy, Decision
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(160, 50)) as pilot:
        await app.workers.wait_for_complete()
        cards = [Card(CardKey(10, 4), Rarity.COMMON, 10, 'Zulu', Decimal('10')),
            Card(CardKey(2, 3), Rarity.RARE, 2, 'Alpha', Decimal('2')),
            Card(CardKey(99, 1), Rarity.EPIC, 1, 'Unknown')]
        app.deck = tuple(cards)
        plan = Plan.create(app.account.nation, Policy(), [Decision(c, True, 'Eligible') for c in cards])
        app.plan = plan
        app.render_cards()
        table = app.query_one('#cards', DataTable)
        def header(label):
            index, key = next((i, k) for i, (k, c) in enumerate(table.columns.items()) if str(c.label) == label)
            table.sort_header(DataTable.HeaderSelected(table, key, index, table.columns[key].label))
        header('Market value')
        assert [table.get_row_at(i)[0] for i in range(3)] == ['#2 / S3', '#10 / S4', '#99 / S1']
        header('Market value')
        assert [table.get_row_at(i)[0] for i in range(3)] == ['#10 / S4', '#2 / S3', '#99 / S1']
        header('Copies')
        assert [table.get_row_at(i)[3] for i in range(3)] == ['1', '2', '10']
        app.render_cards()
        assert [table.get_row_at(i)[3] for i in range(3)] == ['1', '2', '10']
        assert app.plan is plan and app.plan.copies == 13
        table.move_cursor(row=1)
        table.focus()
        await pilot.press('enter')
        await pilot.pause()
        assert app.selected_card.key == CardKey(2, 3)


async def test_totals_refresh_and_about_runtime(tmp_path, monkeypatch, public_deck_api):
    from deckhand.tui import About, startup_command
    import platform, sys
    calls = []
    async def totals(api):
        calls.append(api.nation)
        return Decimal('12.34'), Decimal('1000.50')
    monkeypatch.setattr(public_deck_api, 'deck_totals', totals, raising=False)
    settings = Settings(tmp_path)
    settings.add(Account('alpha'))
    app = Deckhand(settings=settings)
    async with app.run_test(size=(130, 50)) as pilot:
        await app.workers.wait_for_complete()
        assert '12.34' in str(app.query_one('#bank-total', Static).render())
        assert '1,000.50' in str(app.query_one('#deck-value-total', Static).render())
        app.refresh_deck()
        await app.workers.wait_for_complete()
        assert calls == ['alpha', 'alpha']
        app.push_screen(About())
        await pilot.pause()
        runtime = str(app.screen.query_one('#about-runtime', Static).render())
        assert platform.python_version() in runtime and sys.executable in runtime
        assert app.screen.query_one('#about-command', TextArea).text == startup_command()


async def test_confirmation_accepts_human_nation_name_and_rejects_other(tmp_path):
    from deckhand.tui import Confirm
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    results = []
    async with app.run_test(size=(130, 50)) as pilot:
        app.push_screen(Confirm('greater_new_columbia', 'Synthetic confirmation'), results.append)
        await pilot.pause()
        field = app.screen.query_one('#confirm-nation', Input)
        field.value = 'Other Nation'
        field.focus()
        await pilot.press('enter')
        await pilot.pause()
        assert isinstance(app.screen, Confirm) and not results
        assert 'greater new columbia' in str(app.screen.query_one('#confirm-error', Static).render())
        field.value = 'Greater New Columbia'
        await pilot.press('enter')
        await pilot.pause()
        assert results == [True]


async def test_gift_confirmation_requires_both_human_readable_names(tmp_path):
    from deckhand import GiftPlan
    from deckhand.tui import GiftConfirm
    plan = GiftPlan('greater_new_columbia', 'free_separatists', Decimal('.10'), Decimal('1'), (), time.time())
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    results = []
    async with app.run_test(size=(130, 50)) as pilot:
        app.push_screen(GiftConfirm(plan), results.append)
        await pilot.pause()
        source = app.screen.query_one('#gift-source-confirm', Input)
        target = app.screen.query_one('#gift-target-confirm', Input)
        source.value = 'Greater New Columbia'
        source.focus()
        await pilot.press('enter')
        await pilot.pause()
        assert target.has_focus and results == []
        target.value = 'Another Nation'
        await pilot.press('enter')
        await pilot.pause()
        assert isinstance(app.screen, GiftConfirm) and not results
        target.value = 'Free Separatists'
        await pilot.press('enter')
        await pilot.pause()
        assert results == [True]
        app.push_screen(GiftConfirm(plan), results.append)
        await pilot.pause()
        await pilot.press('escape')
        await pilot.pause()
        assert results == [True, False]


async def test_table_column_separators_preserve_cell_data_and_width(tmp_path):
    from rich.style import Style
    from rich.segment import Segment
    app = Deckhand(settings=Settings(tmp_path), demo=True)
    async with app.run_test(size=(130, 50)) as pilot:
        await app.workers.wait_for_complete()
        table = app.query_one('#cards', DataTable)
        original = table.get_row_at(0)
        for row_index in (-1, 0):
            lines = table._render_cell(row_index, 0, Style(), 20)
            assert all(''.join(segment.text for segment in line).endswith('\u2502') for line in lines)
            assert all(Segment.get_line_length(line) == 20 for line in lines)
            assert lines[0][-1].style.meta['column'] == 0
        assert table.get_row_at(0) == original

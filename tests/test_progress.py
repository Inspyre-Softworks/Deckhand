import pytest
from textual.app import App
from textual.widgets import Button, ProgressBar, Static
from deckhand.progress import ProgressWindow
from deckhand.tui import OperationProgress, NameResolution


@pytest.mark.parametrize('size', [(100, 36), (70, 24)])
async def test_progress_window_is_standalone_and_preserves_inset_spec(size):
    app = App()
    stopped = []
    window = ProgressWindow('Shared progress', on_stop=lambda: stopped.append(True),
        status='Checking cards', total=10, action_label='Cancel', help_text='Completed work is kept.')
    async with app.run_test(size=size) as pilot:
        await app.push_screen(window)
        await pilot.pause()
        inset = window.query_one('#operation-inset')
        assert [w.id for w in inset.children] == ['operation-status', 'progress']
        assert window.query_one('#operation-title').parent is not inset
        assert window.query_one('#operation-title').styles.text_align == 'center'
        assert inset.styles.border_top[0] == 'inner'
        assert window.query_one('#dialog').region.height < size[1]
        window.update_progress(total=10, progress=3, unit='cards processed')
        window.set_estimate('About 12s remaining')
        window.set_detail('Waiting for server')
        assert window.query_one('#progress', ProgressBar).progress == 3
        assert '3 / 10' in str(window.query_one('#operation-count', Static).render())
        assert '12s' in str(window.query_one('#preview-eta', Static).render())
        await pilot.press('escape')
        assert stopped == [True]
        assert window.query_one('#operation-stop', Button).disabled
        await pilot.press('escape')
        assert stopped == [True]  # stop is idempotent while the caller finishes work
        window.set_action('Close', lambda: window.dismiss(None))
        await pilot.press('escape')
        await pilot.pause()
        assert app.screen is not window


def test_operation_windows_share_layout_class():
    assert issubclass(OperationProgress, ProgressWindow)
    assert issubclass(NameResolution, ProgressWindow)
    assert 'compose' not in OperationProgress.__dict__
    assert 'compose' not in NameResolution.__dict__

"""Reusable Textual progress modal with Deckhand's inset layout."""
from collections.abc import Callable
from textual import on
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, ProgressBar, Rule, Static


class ProgressWindow(ModalScreen):
    """Presentation and stop signaling; workers and job policy stay with callers.

    Titles sit above the inset. Only status and the bar live inside it.
    Counts, ETA, request detail, and a quiet action footer sit below.
    """
    BINDINGS = [("escape", "stop", "Stop / cancel")]
    DEFAULT_CSS = """
    ProgressWindow { align: center middle; background: #050911 80%; color: #dce7f7; }
    ProgressWindow #dialog.operation-dialog { width: 68; max-width: 95%; height: auto; max-height: 95%; overflow-y: auto; background: #15223a; padding: 1 3; border: round #36506b; }
    ProgressWindow #operation-inset { height: auto; padding: 1 2; margin-bottom: 1; background: #0e192a; border: inner #263b59; }
    ProgressWindow #operation-eyebrow, ProgressWindow #operation-title, ProgressWindow #operation-status { width: 100%; text-align: center; }
    ProgressWindow #operation-eyebrow { color: $accent; text-style: bold; margin-bottom: 1; }
    ProgressWindow #operation-title { color: #edf3fc; text-style: bold; margin-bottom: 1; }
    ProgressWindow #operation-status { color: #dce7f7; height: auto; min-height: 1; margin-bottom: 1; }
    ProgressWindow .operation-dialog #progress { width: 100%; height: 1; margin-bottom: 0; }
    ProgressWindow .operation-dialog #progress Bar { width: 1fr; }
    ProgressWindow #operation-metrics { height: auto; min-height: 2; }
    ProgressWindow #operation-count { width: 1fr; color: #a8bfd9; }
    ProgressWindow .operation-dialog #preview-eta { width: 1fr; height: auto; text-align: right; color: #dce7f7; }
    ProgressWindow #operation-request { height: 1; color: #8b9fb9; }
    ProgressWindow .operation-dialog Rule { margin: 1 0; color: #263b59; }
    ProgressWindow #operation-footer { height: 3; align-vertical: middle; }
    ProgressWindow #operation-help { width: 1fr; height: auto; color: #8b9fb9; padding-right: 2; }
    ProgressWindow #operation-stop { width: 12; min-width: 10; border: round #36506b; background: #1b2d44; color: #dce7f7; }
    ProgressWindow #operation-stop:hover { background: #29415e; }
    ProgressWindow #operation-shortcut { color: #8b9fb9; text-align: right; height: 1; }
    """

    def __init__(self, title, *, on_stop: Callable[[], None], eyebrow="DECKHAND",
                 status="Getting ready...", total=None, count="Preparing...",
                 estimate="Estimating time...", help_text="Stops safely after the current request.",
                 action_label="Stop"):
        super().__init__()
        self.heading = title
        self.eyebrow = eyebrow
        self.initial_status, self.initial_total = status, total
        self.initial_count, self.initial_estimate = count, estimate
        self.help_text, self.action_label = help_text, action_label
        self.stop_callback = on_stop
        self.stop_requested = False

    def compose(self):
        with Vertical(id="dialog", classes="operation-dialog"):
            yield Label(self.eyebrow, id="operation-eyebrow", markup=False)
            yield Label(self.heading, id="operation-title", markup=False)
            with Vertical(id="operation-inset"):
                yield Static(self.initial_status, id="operation-status", markup=False)
                yield ProgressBar(total=self.initial_total, show_eta=False, id="progress")
            with Horizontal(id="operation-metrics"):
                yield Static(self.initial_count, id="operation-count", markup=False)
                yield Static(self.initial_estimate, id="preview-eta", markup=False)
            yield Static("", id="operation-request", markup=False)
            yield Rule()
            with Horizontal(id="operation-footer"):
                yield Static(self.help_text, id="operation-help", markup=False)
                yield Button(self.action_label, id="operation-stop")
            yield Static(f"Esc to {self.action_label.lower()}", id="operation-shortcut")

    def set_status(self, text):
        self.query_one("#operation-status", Static).update(text)

    def set_detail(self, text):
        self.query_one("#operation-request", Static).update(text)

    def set_estimate(self, text):
        self.query_one("#preview-eta", Static).update(text)

    def update_progress(self, *, total=None, progress=0, unit="cards checked"):
        self.query_one("#progress", ProgressBar).update(total=total, progress=progress)
        if total is not None:
            self.query_one("#operation-count", Static).update(f"{progress} / {total} {unit}")

    def set_action(self, label, callback):
        """Replace the action, for example with Close after a worker error."""
        self.stop_callback = callback
        self.stop_requested = False
        button = self.query_one("#operation-stop", Button)
        button.label, button.disabled = label, False
        self.query_one("#operation-shortcut", Static).update(f"Esc to {label.lower()}")

    @on(Button.Pressed, "#operation-stop")
    def stop_pressed(self, event):
        event.stop()
        self.action_stop()

    def action_stop(self):
        if self.stop_requested:
            return
        self.stop_requested = True
        self.query_one("#operation-stop", Button).disabled = True
        self.set_status("Stopping safely...")
        self.set_detail("Finishing the current request")
        self.stop_callback()

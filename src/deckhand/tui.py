"""Textual frontend; all card logic lives in the library."""
import argparse
import asyncio
from decimal import Decimal
from pathlib import Path
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input,
    Label, ProgressBar, RichLog, Select, Static)
from rich.text import Text
from .api import NationStates, RateGate
from .credentials import Vault, default_backend
from .models import Card, CardKey, Decision, Plan, Policy, Rarity
from .service import Cleaner
from .storage import Account, Settings

MODES = [("Session only • never save", "session"), ("Password encrypted", "encrypted"),
    ("Windows Hello", "hello"), ("System keyring", "keyring"), ("Plaintext • unsafe", "plaintext")]


class AddAccount(ModalScreen):
    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Add a nation", classes="dialog-title")
            yield Input(placeholder="Nation name", id="nation")
            yield Input(placeholder="Display label (optional)", id="label")
            yield Label("Credential storage (you can leave credentials unset)")
            yield Select(MODES, value=default_backend(), allow_blank=False, id="mode")
            yield Static("Plaintext is readable by anyone with access to the file or its backups.", classes="warning")
            yield Checkbox("I accept plaintext storage risks", id="plain-ok")
            yield Static("", id="modal-error")
            with Horizontal(classes="buttons"):
                yield Button("Add account", variant="primary", id="add")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "add":
            mode = self.query_one("#mode", Select).value
            try:
                if mode == "plaintext" and not self.query_one("#plain-ok", Checkbox).value:
                    raise ValueError("Acknowledge the plaintext warning first.")
                account = Account(self.query_one("#nation", Input).value,
                    self.query_one("#label", Input).value, mode)
                self.dismiss(account)
            except ValueError as error:
                self.query_one("#modal-error", Static).update(str(error))


class SecretPrompt(ModalScreen):
    def __init__(self, account, *, saving=False):
        super().__init__()
        self.account, self.saving = account, saving

    def compose(self):
        with Vertical(id="dialog"):
            yield Label(f"{'Save credentials' if self.saving else 'Unlock'} · {self.account.nation}", classes="dialog-title")
            yield Static(f"Storage: {self.account.backend}", markup=False)
            if self.saving:
                yield Input(placeholder="Nation password", password=True, id="secret")
            if self.account.backend == "encrypted":
                yield Input(placeholder="Vault encryption password", password=True, id="master")
                if self.saving:
                    yield Input(placeholder="Repeat vault encryption password", password=True, id="repeat")
            if self.saving and self.account.backend == "plaintext":
                yield Static("WARNING: Your nation password will be saved in a readable file, including in backups.", classes="warning")
                yield Checkbox("I understand and want plaintext storage", id="plain-ok")
            yield Static("", id="modal-error")
            with Horizontal(classes="buttons"):
                yield Button("Continue", variant="primary", id="continue")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.clear_secrets()
            self.dismiss(None)
        elif event.button.id == "continue":
            master = self.query_one("#master", Input).value if self.account.backend == "encrypted" else None
            secret = self.query_one("#secret", Input).value if self.saving else None
            plain = bool(self.query("#plain-ok")) and self.query_one("#plain-ok", Checkbox).value
            error = ""
            if self.saving and not secret:
                error = "Enter the nation password."
            elif self.account.backend == "encrypted" and not master:
                error = "Enter the vault encryption password."
            elif self.saving and self.account.backend == "encrypted" and master != self.query_one("#repeat", Input).value:
                error = "Vault passwords do not match."
            elif self.saving and self.account.backend == "plaintext" and not plain:
                error = "Acknowledge the plaintext warning."
            if error:
                self.query_one("#modal-error", Static).update(error)
                return
            self.clear_secrets()
            self.dismiss({"secret": secret, "master": master, "allow_plaintext": plain})

    def clear_secrets(self):
        for widget in self.query(Input):
            widget.value = ""


class Confirm(ModalScreen):
    def __init__(self, nation, message):
        super().__init__()
        self.nation, self.message = nation, message

    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Confirm action", classes="dialog-title")
            yield Static(self.message, markup=False)
            yield Label(f"Type {self.nation} to continue")
            yield Input(id="confirm-nation")
            with Horizontal(classes="buttons"):
                yield Button("Confirm", variant="error", id="confirm")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "confirm":
            if self.query_one(Input).value.strip() == self.nation:
                self.dismiss(True)
            else:
                self.notify("Nation name must match exactly.", severity="warning")


class Deckhand(App):
    TITLE = "DECKHAND"
    SUB_TITLE = "NationStates · Card cleanup"
    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+s", "scan", "Preview"),
        ("escape", "stop", "Stop")]
    CSS = """
    Screen { background: #0b1220; color: #dce7f7; }
    Header { background: #15223a; }
    Footer { background: #15223a; }
    #body { height: 1fr; }
    #sidebar { width: 34; background: #111d30; padding: 1 2; border-right: solid #263b59; }
    .eyebrow { color: #67ded0; text-style: bold; margin-bottom: 1; }
    .muted { color: #8b9fb9; }
    #sidebar Label { margin-top: 1; }
    #sidebar Button { width: 100%; margin-top: 0; }
    #sidebar Select, #sidebar Input { width: 100%; }
    #main { width: 1fr; padding: 1 2; }
    #hero { height: 4; color: #67ded0; text-style: bold; }
    #stats { height: 4; background: #16263e; border-left: thick #67ded0; padding: 0 2; margin-bottom: 1; }
    DataTable { height: 1fr; min-height: 8; background: #0e192a; border: round #263b59; }
    #status { height: 2; color: #a8bfd9; margin-top: 1; }
    #progress { margin: 0 0 1 0; }
    #activity { height: 7; background: #0e192a; border: round #263b59; }
    .buttons { height: 3; margin-top: 1; }
    .buttons Button { margin-right: 1; }
    #execute { width: 24; }
    #stop { width: 14; }
    ModalScreen { align: center middle; background: #050911 80%; }
    #dialog { width: 70; height: auto; max-height: 95%; padding: 2 3; border: round #67ded0; background: #15223a; overflow-y: auto; }
    #dialog Input, #dialog Select { margin-top: 1; }
    .dialog-title { text-style: bold; color: #67ded0; margin-bottom: 1; }
    .warning { color: #ffd18a; margin-top: 1; }
    #modal-error { color: #ff9393; }
    """

    def __init__(self, *, settings=None, demo=False):
        super().__init__()
        self.settings = settings or Settings()
        self.vault = Vault(self.settings.directory)
        self.demo = demo
        if demo:
            self.settings.accounts = [Account("demo_nation", "Demo nation", "session")]
        self.account = self.settings.accounts[0] if self.settings.accounts else None
        self.plan = None
        self.busy = False
        self.stop_event = asyncio.Event()
        self.gate = RateGate()
        self.loading_account = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with VerticalScroll(id="sidebar"):
                yield Static("◆ YOUR FLEET", classes="eyebrow")
                yield Select(self.account_options(), prompt="Choose a nation", id="accounts",
                    value=self.account.id if self.account else Select.NULL)
                yield Button("+ Add account", id="add-account")
                yield Button("Credentials", id="credentials")
                yield Button("Forget credentials", id="forget")
                yield Button("Remove account", id="remove")
                yield Label("API contact nation / email")
                yield Input(value=self.settings.contact, placeholder="Your main nation", id="contact")
                yield Static("Used in the API User-Agent", classes="muted")
                yield Label("Junk this rarity and below")
                yield Select([(r.label, r.name) for r in Rarity], value="COMMON", allow_blank=False, id="rarity")
                yield Checkbox("Protect collections", value=True, id="collections")
                yield Checkbox("Protect sale listings", value=True, id="listings")
                yield Button("Preview cleanup", variant="primary", id="scan")
                yield Static("Bids above junk value are always protected.", classes="muted")
            with Vertical(id="main"):
                yield Static("◆ DECKHAND\nA cleaner deck. A clear decision.", id="hero")
                yield Static("Choose an account and preview your deck.\nNo cards have been changed.", id="stats")
                yield DataTable(id="cards", zebra_stripes=True)
                yield Static("Ready · preview is read-only", id="status")
                yield ProgressBar(total=100, show_eta=False, id="progress")
                with Horizontal(classes="buttons"):
                    yield Button("Junk reviewed cards", variant="error", id="execute", disabled=True)
                    yield Button("Stop", id="stop", disabled=True)
                yield RichLog(id="activity", markup=False, wrap=True)
        yield Footer()

    def account_options(self):
        return [(f"{a.label or a.nation} · {a.nation}" if a.label else a.nation, a.id) for a in self.settings.accounts]

    def on_mount(self):
        self.query_one(DataTable).add_columns("Card / Season", "Nation on card", "Rarity", "Copies", "Junk each", "Best bid", "Decision")
        self.show_account()
        self.log_line("Demo mode: all data is synthetic and execution is disabled." if self.demo else "Welcome. Add your nations; credentials are only needed when junking.")

    def log_line(self, message):
        self.query_one("#activity", RichLog).write(message)

    def invalidate(self):
        self.plan = None
        self.query_one("#execute", Button).disabled = True
        self.query_one(DataTable).clear()
        self.query_one("#stats", Static).update("Preview required\nAccount and filters determine what is eligible.")

    def show_account(self):
        self.loading_account = True
        policy = self.account.policy if self.account else Policy()
        self.query_one("#rarity", Select).value = policy.maximum.name
        self.query_one("#collections", Checkbox).value = policy.protect_collections
        self.query_one("#listings", Checkbox).value = policy.protect_listings
        self.loading_account = False
        self.invalidate()

    @on(Select.Changed, "#accounts")
    def selected_account(self, event):
        self.account = next((a for a in self.settings.accounts if a.id == event.value), None)
        self.show_account()

    @on(Select.Changed, "#rarity")
    @on(Checkbox.Changed, "#collections")
    @on(Checkbox.Changed, "#listings")
    def policy_changed(self):
        if not self.loading_account and self.is_mounted:
            self.invalidate()

    def policy(self):
        return Policy(Rarity[self.query_one("#rarity", Select).value],
            self.query_one("#collections", Checkbox).value,
            self.query_one("#listings", Checkbox).value)

    def set_busy(self, value):
        self.busy = value
        for widget in self.query("#sidebar Button, #sidebar Select, #sidebar Input, #sidebar Checkbox"):
            widget.disabled = value
        self.query_one("#stop", Button).disabled = not value
        self.query_one("#execute", Button).disabled = value or not self.plan or not self.plan.copies or self.demo

    @on(Button.Pressed)
    def button(self, event):
        actions = {"scan": self.action_scan, "execute": self.start_execution,
            "stop": self.action_stop, "add-account": self.add_account,
            "credentials": self.save_credentials, "forget": self.forget_credentials,
            "remove": self.remove_account}
        action = actions.get(event.button.id)
        if action:
            action()

    def action_scan(self):
        if self.busy:
            return
        if not self.account:
            self.notify("Add or select an account first.", severity="warning")
            return
        contact = self.query_one("#contact", Input).value.strip()
        if not self.demo and not contact:
            self.notify("Enter an API contact nation or email.", severity="warning")
            return
        policy = self.policy()
        self.account.maximum = policy.maximum.name
        self.account.protect_collections = policy.protect_collections
        self.account.protect_listings = policy.protect_listings
        self.settings.contact = contact
        try:
            if not self.demo:
                self.settings.save()
        except OSError:
            self.notify("Could not save settings.", severity="error")
            return
        self.invalidate()
        self.stop_event = asyncio.Event()
        self.set_busy(True)
        self.scan(self.account.nation, policy, contact)

    @work(exclusive=True, group="network", exit_on_error=False)
    async def scan(self, nation, policy, contact):
        try:
            if self.demo:
                self.plan = demo_plan(nation, policy)
            else:
                async with NationStates(nation, contact, gate=self.gate) as api:
                    self.plan = await Cleaner(api).preview(policy, progress=self.scan_progress, stop=self.stop_event)
            for d in self.plan.decisions:
                c = d.card
                color = "#67ded0" if d.eligible else "#8b9fb9"
                self.query_one(DataTable).add_row(f"#{c.key.card_id} / S{c.key.season}",
                    Text(c.name or "—"), c.rarity.label, str(c.copies), str(c.rarity.junk),
                    str(d.highest_bid) if d.highest_bid is not None else "—", Text(d.reason, style=color))
            self.query_one("#stats", Static).update(Text(
                f"{self.plan.copies} copies eligible  ·  {self.plan.proceeds:.2f} bank estimated\n"
                f"{nation}  /  {policy.maximum.label} and below  /  {len(self.plan.decisions)} unique cards"))
            self.query_one("#status", Static).update("Preview complete · execution rechecks every copy" + (" · DEMO" if self.demo else ""))
            self.query_one("#progress", ProgressBar).update(total=100, progress=100)
            self.log_line(f"Preview for {nation}: {self.plan.copies} copies eligible.")
        except Exception as error:
            self.invalidate()
            self.report_error(error)
        finally:
            self.set_busy(False)

    def scan_progress(self, current, total, decision):
        self.query_one("#progress", ProgressBar).update(total=total, progress=current)
        self.query_one("#status", Static).update(f"Scanning {current}/{total} unique cards…")

    def action_stop(self):
        if self.busy:
            self.stop_event.set()
            self.query_one("#status", Static).update("Stopping after the current request completes…")

    def start_execution(self):
        if self.busy or self.demo or not self.plan or not self.plan.copies:
            return
        self.set_busy(True)
        self.stop_event = asyncio.Event()
        self.execute_reviewed(self.account, self.plan)

    @work(group="network", exclusive=True, exit_on_error=False)
    async def execute_reviewed(self, account, plan):
        secret = None
        supplied = None
        master = None
        try:
            accepted = await self.push_screen_wait(Confirm(plan.nation,
                f"Permanently junk up to {plan.copies} reviewed copies for approximately {plan.proceeds:.2f} bank?\n"
                "This cannot be undone. New cards are never added to this run."))
            if not accepted or self.stop_event.is_set():
                return
            master = None
            if account.backend == "encrypted":
                supplied = await self.push_screen_wait(SecretPrompt(account))
                if supplied is None:
                    return
                master = supplied["master"]
            secret = await asyncio.to_thread(self.vault.load, account, master=master)
            master = None
            if supplied:
                supplied.clear()
            self.plan = None  # A plan is consumed even if execution fails partway.
            async with NationStates(plan.nation, self.settings.contact, gate=self.gate) as api:
                result = await Cleaner(api).execute(plan, secret, confirmed_nation=plan.nation,
                    stop=self.stop_event, progress=self.run_progress)
            self.log_line(f"{plan.nation}: {result.junked} junked, {result.skipped} skipped, {result.proceeds:.2f} bank."
                + (" Stopped." if result.stopped else " Finished."))
            self.query_one("#status", Static).update("Run ended · rescan for a fresh preview")
        except Exception as error:
            self.plan = None
            self.report_error(error)
        finally:
            secret = None
            master = None
            if supplied:
                supplied.clear()
            self.set_busy(False)

    def run_progress(self, done, skipped, message):
        self.log_line(f"{done} junked · {skipped} skipped · {message}")
        self.query_one("#status", Static).update(f"{done} junked · {skipped} skipped")

    def report_error(self, error):
        # Known application exceptions contain safe messages. Never print
        # arbitrary backend exceptions, reprs, request headers or tracebacks.
        from .api import APIError
        from .credentials import CredentialError
        from .hello import HelloError
        message = str(error) if isinstance(error, (APIError, CredentialError, HelloError)) else f"{type(error).__name__}: operation failed; no automatic retry."
        self.log_line(message)
        self.query_one("#status", Static).update(Text(message))
        self.notify(message, severity="error")

    def add_account(self):
        if not self.busy and not self.demo:
            self.push_screen(AddAccount(), self.account_added)

    def account_added(self, account):
        if account is None:
            return
        try:
            self.settings.add(account)
            self.account = account
            selector = self.query_one("#accounts", Select)
            selector.set_options(self.account_options())
            selector.value = account.id
            self.log_line(f"Added {account.nation}. Credentials are optional until execution.")
        except Exception as error:
            self.report_error(error)

    def save_credentials(self):
        if not self.busy and self.account and not self.demo:
            self.set_busy(True)
            self.credential_worker(self.account)

    @work(group="vault", exit_on_error=False)
    async def credential_worker(self, account):
        supplied = None
        try:
            supplied = await self.push_screen_wait(SecretPrompt(account, saving=True))
            if supplied:
                await asyncio.to_thread(self.vault.save, account, supplied["secret"],
                    master=supplied["master"], allow_plaintext=supplied["allow_plaintext"])
                self.log_line(f"Credentials stored for {account.nation} using {account.backend}.")
        except Exception as error:
            self.report_error(error)
        finally:
            if supplied:
                supplied.clear()
            self.set_busy(False)

    def forget_credentials(self):
        if not self.busy and self.account and not self.demo:
            self.set_busy(True)
            self.delete_worker(self.account, False)

    def remove_account(self):
        if not self.busy and self.account and not self.demo:
            self.set_busy(True)
            self.delete_worker(self.account, True)

    @work(group="vault", exit_on_error=False)
    async def delete_worker(self, account, remove):
        try:
            accepted = await self.push_screen_wait(Confirm(account.nation,
                "Remove this account and its saved credentials?" if remove else "Forget this account's saved credentials?"))
            if not accepted:
                return
            try:
                await asyncio.to_thread(self.vault.delete, account)
            except keyring_missing_errors():
                pass
            if remove:
                self.settings.accounts.remove(account)
                self.settings.save()
                selector = self.query_one("#accounts", Select)
                selector.set_options(self.account_options())
                selector.value = self.settings.accounts[0].id if self.settings.accounts else Select.NULL
            self.invalidate()
            self.log_line(f"Credentials forgotten for {account.nation}.")
        except Exception as error:
            self.report_error(error)
        finally:
            self.set_busy(False)

    async def action_quit(self):
        if self.busy:
            self.action_stop()
            self.notify("Stopping safely. Quit once the current operation finishes.")
        else:
            self.vault.session.clear()
            self.exit()


def keyring_missing_errors():
    from keyring.errors import PasswordDeleteError
    return (PasswordDeleteError,)


def demo_plan(nation, policy):
    from .models import decide
    deck = [Card(CardKey(101, 4), Rarity.COMMON, 3, "Silver Harbour"),
        Card(CardKey(102, 4), Rarity.COMMON, 2, "Moonlit Republic"),
        Card(CardKey(103, 3), Rarity.UNCOMMON, 1, "Cedar Isles"),
        Card(CardKey(104, 4), Rarity.COMMON, 1, "Amber Fields"),
        Card(CardKey(105, 2), Rarity.EPIC, 1, "Sunward"),
        Card(CardKey(106, 4), Rarity.COMMON, 2, "Starlight Coast")]
    return Plan.create(nation, policy, [decide(c, policy, {CardKey(104, 4)},
        {CardKey(106, 4)}, Decimal("0.08") if c.key.card_id == 102 else None) for c in deck])


def main():
    parser = argparse.ArgumentParser(description="Deckhand · NationStates card cleanup")
    parser.add_argument("--demo", action="store_true", help="Synthetic preview; never contacts NationStates")
    parser.add_argument("--config-dir", type=Path, help="Override the local account/vault directory")
    args = parser.parse_args()
    Deckhand(settings=Settings(args.config_dir), demo=args.demo).run()


if __name__ == "__main__":
    main()

"""Textual frontend; all card logic lives in the library."""
import argparse
import asyncio
import math
import re
import sys
import platform
import shlex
import subprocess
import time
import sqlite3
from importlib.metadata import version, PackageNotFoundError
from dataclasses import replace
from urllib.parse import urlencode
from decimal import Decimal, InvalidOperation
from pathlib import Path
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import (Button, Checkbox, DataTable, Footer, Header, Input,
    Label, ProgressBar, RichLog, Select, Static, TextArea, Link, Rule)
from rich.text import Text
from rich.segment import Segment
from rich.style import Style
from .appearance import flag_accent, DEFAULT_ACCENT
from .catalog import CardCatalog
from .api import NationStates, RateGate
from .credentials import Vault, default_backend
from .models import Card, CardKey, Decision, Plan, Policy, Rarity, nation_id
from .progress import ProgressWindow
from .gifting import Gifter
from .service import Cleaner
from .storage import Account, Settings, RequestCounter

MODES = [("Session only - never save", "session"), ("Password encrypted", "encrypted"),
    ("Windows Hello", "hello"), ("System keyring", "keyring"), ("Plaintext - unsafe", "plaintext")]


class CardTable(DataTable):
    """Column sorting changes presentation only, never the underlying plans."""
    def __init__(self, *args, **kwargs):
        tooltip = kwargs.pop("tooltip", "Click a column heading to sort; click again to reverse.")
        super().__init__(*args, **kwargs)
        self.tooltip = tooltip
        self.sort_column = None
        self.sort_reverse = False

    def _render_cell(self, row_index, column_index, base_style, width, cursor=False, hover=False):
        # Textual 8 has no column-grid option. Replace one padding cell with a
        # separator, preserving segment width and pointer metadata for sorting.
        lines = super()._render_cell(row_index, column_index, base_style, width, cursor, hover)
        if width < 1 or column_index < 0 or column_index >= len(self.columns) - 1:
            return lines
        return [Segment.adjust_line_length(line, width - 1, pad=False)
            + [Segment("\u2502", (line[-1].style or base_style) + Style(color="#36506b"))]
            for line in lines]

    @on(DataTable.HeaderSelected)
    def sort_header(self, event):
        event.stop()
        if event.column_key == self.sort_column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = event.column_key
            self.sort_reverse = False
        self.resort()

    def resort(self):
        if self.sort_column is None or self.row_count == 0:
            return
        label = str(self.columns[self.sort_column].label).lower()
        def sort_value(cell):
            text = cell.plain if isinstance(cell, Text) else str(cell)
            missing = text in ("-", "(unknown)", "")
            priority = int(not missing) if self.sort_reverse else int(missing)
            if missing:
                return priority, 0
            if label.startswith("card /"):
                return priority, tuple(int(v) for v in re.findall(r"\d+", text))
            if label == "rarity":
                return priority, int(Rarity.parse(text))
            if label in ("copies", "market value", "junk each", "best bid", "fee each"):
                return priority, Decimal(text)
            return priority, text.casefold()
        selected = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        self.sort(self.sort_column, key=sort_value, reverse=self.sort_reverse)
        self.move_cursor(row=self.get_row_index(selected))


class AddAccount(ModalScreen):
    @on(Input.Submitted)
    def submit_input(self, event):
        event.stop()
        self.query_one("#add", Button).press()

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

    @on(Input.Submitted)
    def submit_input(self, event):
        event.stop()
        self.query_one("#continue", Button).press()

    def compose(self):
        with Vertical(id="dialog"):
            yield Label(f"{'Save credentials' if self.saving else 'Unlock'} - {self.account.nation}", classes="dialog-title")
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


class ProtectedNames(ModalScreen):
    def __init__(self, account):
        super().__init__()
        self.account = account

    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Protect card nation names", classes="dialog-title")
            yield Static("One entry per line. Matches ignore case and treat spaces and underscores alike. Rules apply to this account.")
            yield Label("Exact nation names")
            yield TextArea("\n".join(self.account.protected_names), id="protected-names")
            yield Label("Nation name contains (literal text, not regular expressions)")
            yield TextArea("\n".join(self.account.protected_substrings), id="protected-substrings")
            with Horizontal(classes="buttons"):
                yield Button("Save rules", variant="primary", id="save-rules")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save-rules":
            self.dismiss(tuple([line.strip() for line in self.query_one(selector, TextArea).text.splitlines()
                if line.strip()] for selector in ("#protected-names", "#protected-substrings")))


class SaleReview(ModalScreen):
    def __init__(self, plan, *, above_junk=False):
        super().__init__()
        self.plan = plan
        self.above_junk = above_junk

    def compose(self):
        matches = self.plan.sale_candidates(above_junk=self.above_junk)
        group = "above" if self.above_junk else "equal to"
        stamp = time.strftime("%H:%M:%S", time.localtime(self.plan.created))
        with Vertical(id="dialog"):
            yield Label(f"Review sales - bids {group} junk value", classes="dialog-title")
            yield Static(f"Nation: {self.plan.nation} - preview at {stamp}\n"
                f"{len(matches)} unique cards - {sum(d.card.copies for d in matches)} owned copies",
                markup=False)
            yield Static("Manual sale review only. Open a card's market page, verify you are signed in as this nation, "
                "and match the bid on NationStates. These links do not place asks or sell cards.")
            yield Static("Bids can change or disappear. A bid may not cover every owned copy. "
                "Recheck price, protections, and available copies before selling; refresh the preview afterward.",
                classes="warning")
            with VerticalScroll(id="sale-list"):
                for decision in matches:
                    card = decision.card
                    query = urlencode({"generated_by": f"Deckhand (https://github.com/Inspyre-Softworks/Deckhand; usedBy:{self.plan.nation})"})
                    url = f"https://www.nationstates.net/page=deck/card={card.key.card_id}/season={card.key.season}?{query}"
                    yield Link(f"{card.name or 'Card'} - #{card.key.card_id} / S{card.key.season}", url=url)
                    yield Static(f"{card.copies} owned - best bid {decision.highest_bid} - junk each {card.rarity.junk}", markup=False)
            yield Button("Close review", id="close-sales")

    @on(Button.Pressed, "#close-sales")
    def close_review(self, event):
        event.stop()
        self.dismiss(None)


def package_version():
    try:
        return version("ns-deckhand")
    except PackageNotFoundError:
        return "unavailable (package not installed)"


def startup_command():
    argv = getattr(sys, "orig_argv", [sys.executable, *sys.argv])
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


class FleetAction(Message):
    def __init__(self, action):
        super().__init__()
        self.action = action


class FleetManagement(ModalScreen):
    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Your nations & credentials", classes="dialog-title")
            yield Select(self.app.account_options(), prompt="Choose a nation", id="manage-nations",
                value=self.app.account.id if self.app.account else Select.NULL)
            yield Static("Select a nation to manage its credentials. New nations prompt for credentials immediately.")
            yield Button("Add a nation", id="add-account", variant="primary")
            yield Button("Set credentials", id="credentials")
            yield Button("Forget credentials", id="forget")
            yield Rule()
            yield Button("Remove nation", id="remove", variant="error")
            yield Button("Close", id="close-fleet")

    @on(Select.Changed, "#manage-nations")
    def choose(self, event):
        event.stop()
        self.app.query_one("#accounts", Select).value = event.value

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        self.dismiss(None)
        if event.button.id != "close-fleet":
            self.app.post_message(FleetAction(event.button.id))


class APISettings(ModalScreen):
    def compose(self):
        with Vertical(id="dialog"):
            yield Label("API settings", classes="dialog-title")
            yield Label("Contact nation or email")
            yield Input(value=self.app.settings.contact, placeholder="Your main nation or email", id="contact")
            yield Static("Identifies Deckhand's operator in the NationStates API User-Agent. No password is sent with public reads.")
            yield Static("", id="api-settings-error", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Save", id="save-api", variant="primary")
                yield Button("Cancel", id="cancel-api")

    @on(Input.Submitted)
    def submitted(self, event):
        event.stop()
        self.query_one("#save-api", Button).press()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == "cancel-api":
            self.dismiss(None)
            return
        contact = self.query_one("#contact", Input).value.strip()
        if not contact or any(c in contact for c in "\r\n"):
            self.query_one("#api-settings-error", Static).update("Enter a contact nation or email.")
            return
        old = self.app.settings.contact
        self.app.settings.contact = contact
        try:
            if not self.app.demo:
                self.app.settings.save()
        except OSError:
            self.app.settings.contact = old
            self.query_one("#api-settings-error", Static).update("Could not save API settings.")
            return
        self.dismiss(None)


class About(ModalScreen):
    BINDINGS = [("escape", "close", "Close")]

    def compose(self):
        release = package_version()
        with Vertical(id="dialog"):
            yield Label("About Deckhand", classes="dialog-title")
            yield Static(f"Deckhand TUI: {release}\nDeckhand backend package: {release}", markup=False)
            yield Static("The TUI and reusable backend ship together in ns-deckhand.\nMIT licensed. NationStates card cleanup with explicit review and confirmation.")
            yield Rule()
            yield Static(f"Python: {platform.python_version()} ({platform.python_implementation()})\n"
                f"Interpreter: {sys.executable}\nSystem: {platform.platform()}", id="about-runtime", markup=False)
            yield Label("Startup command (Python process)")
            yield TextArea(startup_command(), read_only=True, id="about-command")
            yield Button("Close", id="close-about")

    @on(Button.Pressed, "#close-about")
    def action_close(self):
        self.dismiss(None)


class OperationProgress(ProgressWindow):
    def __init__(self, title):
        self.title_text = title
        preview = title == "Preview cleanup"
        heading = "Checking your cards" if preview else (
            "Cleaning your deck" if title == "Junk reviewed cards" else title)
        super().__init__(heading, on_stop=lambda: self.app.action_stop(),
            eyebrow="DECK REVIEW" if preview else "DECKHAND",
            status="Loading your deck..." if preview else "Getting ready...",
            count="Preparing review" if preview else "Preparing...",
            help_text="Preview only. Your cards stay untouched." if preview else
                "Stops safely after the current request.")

    def stage(self, message):
        if "Checking bids:" in message:
            message = "Checking market bids"
        elif "collection" in message.lower() or "protection" in message.lower():
            message = "Checking your protections"
        elif "deck" in message.lower():
            message = "Loading your deck"
        self.set_status(message.rstrip(". "))

    def request_state(self, message):
        # Keep transport-level details out of the main task description.
        if "rate-limit pacing" in message:
            match = re.search(r"waiting ([0-9.]+)s", message)
            detail = f"Next check in {match[1]}s" if match else "Pausing briefly between checks"
        elif "waiting for NationStates response" in message:
            detail = "Waiting for NationStates"
        elif "request slot" in message:
            detail = "Waiting to continue"
        else:
            detail = ""
        self.set_detail(detail)



class GiftSetup(ModalScreen):
    def __init__(self, source, recipients):
        super().__init__()
        self.source, self.recipients = source, recipients

    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Gift cards to another nation", classes="dialog-title")
            yield Static(f"Sending from {self.source.nation}", markup=False)
            yield Label("Saved recipient nation")
            yield Select([(a.label or a.nation, a.id) for a in self.recipients],
                value=self.recipients[0].id, allow_blank=False, id="gift-recipient")
            yield Label("Minimum bank to leave in the sending nation")
            yield Input(value="0.00", id="gift-minimum")
            yield Static("Highest estimated market value first, including all rarities and cleanup-protected cards. Listed cards are skipped. Each copy costs its junk value to gift.")
            yield Static("Uses the reviewed bank minus gift fees; no bank or deck rechecks. Other spending or changed fees can cross the floor.", classes="warning")
            yield Static("", id="gift-error", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Review gifts", id="preview-gifts", variant="primary")
                yield Button("Cancel", id="cancel-gifts")

    @on(Input.Submitted)
    def submitted(self, event):
        event.stop()
        self.query_one("#preview-gifts", Button).press()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == "cancel-gifts":
            self.dismiss(None)
            return
        try:
            minimum = Decimal(self.query_one("#gift-minimum", Input).value.strip())
            if not minimum.is_finite() or minimum < 0 or minimum != minimum.quantize(Decimal("0.01")):
                raise ValueError()
            recipient = self.query_one("#gift-recipient", Select).value
            if recipient not in {a.id for a in self.recipients}:
                raise ValueError()
            self.dismiss((recipient, minimum))
        except (InvalidOperation, ValueError):
            self.query_one("#gift-error", Static).update("Enter a nonnegative bank amount with at most two decimal places.")


class GiftReview(ModalScreen):
    def __init__(self, plan):
        super().__init__()
        self.plan = plan

    def compose(self):
        plan = self.plan
        copies, bank = plan.projected
        with Vertical(id="dialog", classes="gift-review"):
            yield Label("Review card gifts", classes="dialog-title")
            yield Static(f"{plan.source}  ->  {plan.recipient}\n"
                f"Bank: {plan.starting_bank:.2f} | Keep at least: {plan.minimum_bank:.2f}\n"
                f"{plan.copies} reviewed copies | About {copies} can be gifted, leaving {bank:.2f}\n"
                f"{plan.listed_copies} listed copies excluded", markup=False)
            yield CardTable(id="gift-cards", zebra_stripes=True)
            yield Static("Order uses this preview's estimated market values. Includes cleanup-protected cards. Gifts transfer ownership and spend bank; the queue makes no further checks. The floor uses reviewed bank and fees; changes can cross it.", classes="warning")
            with Horizontal(classes="buttons"):
                yield Button("Continue", id="accept-gifts", variant="primary", disabled=copies == 0)
                yield Button("Cancel", id="cancel-gift-review")

    def on_mount(self):
        table = self.query_one("#gift-cards", DataTable)
        table.add_columns("Card / season", "Nation", "Copies", "Market value", "Fee each")
        for item in self.plan.items:
            c = item.card
            table.add_row(f"#{c.key.card_id} / S{c.key.season}", Text(c.name or "(unknown)"),
                str(c.copies), str(item.market_value), str(item.fee))

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        self.dismiss(event.button.id == "accept-gifts")


def confirmation_matches(typed, expected):
    try:
        return nation_id(typed) == nation_id(expected)
    except ValueError:
        return False


class GiftConfirm(ModalScreen):
    BINDINGS = [("escape", "cancel_confirmation", "Cancel")]

    def action_cancel_confirmation(self):
        self.dismiss(False)

    def __init__(self, plan):
        super().__init__()
        self.plan = plan

    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Confirm card transfer", classes="dialog-title")
            yield Static(f"Gift up to {self.plan.copies} reviewed copies from {self.plan.source} "
                f"to {self.plan.recipient}, highest preview market value first. "
                f"Keep at least {self.plan.minimum_bank:.2f} bank in the sender. "
                "No additional bank, ownership, or listing checks will run. The bank floor is a local estimate. "
                "Transfers cannot be undone by Deckhand.", markup=False)
            yield Label("Type the sending nation name")
            yield Input(id="gift-source-confirm", placeholder=self.plan.source.replace("_", " "))
            yield Static(f"Sender: {self.plan.source.replace('_', ' ')}", id="gift-source-hint", markup=False)
            yield Label("Type the recipient nation name")
            yield Input(id="gift-target-confirm", placeholder=self.plan.recipient.replace("_", " "))
            yield Static(f"Recipient: {self.plan.recipient.replace('_', ' ')}", id="gift-target-hint", markup=False)
            yield Static("Capitalization and spaces/underscores are interchangeable.", classes="muted")
            yield Static("", id="gift-confirm-error")
            with Horizontal(classes="buttons"):
                yield Button("Confirm gifts", id="confirm-gifts", variant="error")
                yield Button("Cancel", id="cancel-gift-confirm")

    @on(Input.Changed)
    def name_changed(self, event):
        event.stop()
        if not self.is_mounted:
            return
        for selector, hint, expected, role in (
            ("#gift-source-confirm", "#gift-source-hint", self.plan.source, "Sender"),
            ("#gift-target-confirm", "#gift-target-hint", self.plan.recipient, "Recipient")):
            matches = confirmation_matches(self.query_one(selector, Input).value, expected)
            self.query_one(hint, Static).update(f"{role} matches" if matches
                else f"{role}: {expected.replace('_', ' ')}")
            self.query_one(hint).styles.color = "#67ded0" if matches else "#8b9fb9"
        if (confirmation_matches(self.query_one("#gift-source-confirm", Input).value, self.plan.source)
            and confirmation_matches(self.query_one("#gift-target-confirm", Input).value, self.plan.recipient)):
            self.query_one("#gift-confirm-error", Static).update("")

    @on(Input.Submitted)
    def submitted(self, event):
        event.stop()
        if (event.input.id == "gift-source-confirm"
            and confirmation_matches(event.value, self.plan.source)
            and not self.query_one("#gift-target-confirm", Input).value.strip()):
            self.query_one("#gift-target-confirm", Input).focus()
            return
        self.query_one("#confirm-gifts", Button).press()

    @on(Button.Pressed)
    def pressed(self, event):
        event.stop()
        if event.button.id == "cancel-gift-confirm":
            self.dismiss(False)
        elif (confirmation_matches(self.query_one("#gift-source-confirm", Input).value, self.plan.source)
              and confirmation_matches(self.query_one("#gift-target-confirm", Input).value, self.plan.recipient)):
            self.dismiss(True)
        else:
            self.query_one("#gift-confirm-error", Static).update(
                "Both nation names must match the selected sender and recipient. Case and spaces are allowed.")



class NameResolution(ProgressWindow):
    def __init__(self, cards, nation, contact, gate, catalog):
        self.cards = list(cards)
        super().__init__("Resolve card names", on_stop=self.action_cancel_resolution,
            status="Finding missing names...", total=len(self.cards),
            count=f"0 / {len(self.cards)} cards processed", estimate="",
            help_text="Completed names are kept when you cancel.", action_label="Cancel")
        self.nation, self.contact = nation, contact
        self.gate, self.catalog = gate, catalog
        self.stop = asyncio.Event()
        self.worker = None
        self.finished = False

    def on_mount(self):
        self.worker = self.resolve()

    def progress(self, completed, total, card):
        self.cards[completed - 1] = card
        self.update_progress(total=total, progress=completed, unit="cards processed")

    @work(exit_on_error=False)
    async def resolve(self):
        try:
            async with NationStates(self.nation, self.contact, gate=self.gate,
                catalog=self.catalog, status=self.resolution_status) as api:
                self.cards = await api.resolve_card_names(self.cards, stop=self.stop, progress=self.progress)
            self.finished = True
            self.dismiss(tuple(self.cards))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep completed results visible; never echo arbitrary HTTP/backend content.
            self.finished = True
            self.set_status("Name lookup failed. Completed names are kept.")
            self.set_detail("Close and try again to continue.")
            self.set_action("Close", self.action_cancel_resolution)

    def resolution_status(self, message):
        if not self.stop.is_set():
            self.set_detail(message)

    def action_cancel_resolution(self):
        self.stop.set()
        if self.worker is not None and not self.finished:
            # Only public reads: cancellation can interrupt rate pacing or HTTP immediately.
            self.worker.cancel()
        self.dismiss(tuple(self.cards))


class CardLookup(ModalScreen):
    def __init__(self, catalog):
        super().__init__()
        self.catalog = catalog

    @on(Input.Submitted)
    def submit_input(self, event):
        event.stop()
        self.query_one("#lookup-search", Button).press()

    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Local card lookup", classes="dialog-title")
            yield Static("Previously fetched metadata only; quantities and market state are not saved.")
            yield Select([("Nation name", "name"), ("Card number", "number")],
                value="name", allow_blank=False, id="lookup-kind")
            yield Input(placeholder="Exact name or card number", id="lookup-query")
            yield Static("", id="lookup-results", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Search", id="lookup-search", variant="primary")
                yield Button("Close", id="lookup-close")

    @on(Button.Pressed, "#lookup-close")
    def close_lookup(self, event):
        event.stop()
        self.dismiss(None)

    @on(Button.Pressed, "#lookup-search")
    async def search(self, event):
        event.stop()
        query = self.query_one("#lookup-query", Input).value.strip()
        try:
            args = {"name": query} if self.query_one("#lookup-kind", Select).value == "name" else {"card_id": int(query)}
            cards = await asyncio.to_thread(self.catalog.lookup, **args)
            result = "\n".join(f"{c.name or '(name unknown)'} · #{c.key.card_id} / S{c.key.season} · {c.rarity.label}" for c in cards)
            self.query_one("#lookup-results", Static).update(result or "No locally known cards match. Load a deck or preview to populate the catalog.")
        except ValueError:
            self.query_one("#lookup-results", Static).update("Enter a name or a positive card number.")
        except (OSError, sqlite3.Error):
            self.query_one("#lookup-results", Static).update("The local card catalog is unavailable.")


def execution_mode_notice(policy):
    if policy.fast_execution:
        return ("FASTER EXECUTION: trusts the reviewed queue. Only prepare and execute commands "
            "are sent; ownership, protections, names, and bids are not rechecked. "
            "Changes since review can be missed.")
    return "Standard execution: ownership, protections, and markets are rechecked for each copy."


class Confirm(ModalScreen):
    BINDINGS = [("escape", "cancel_confirmation", "Cancel")]

    def action_cancel_confirmation(self):
        self.dismiss(False)

    def __init__(self, nation, message):
        super().__init__()
        self.nation, self.message = nation, message

    @on(Input.Submitted)
    def submit_input(self, event):
        event.stop()
        self.query_one("#confirm", Button).press()

    def compose(self):
        with Vertical(id="dialog"):
            yield Label("Confirm action", classes="dialog-title")
            yield Static(self.message, markup=False)
            yield Label(f"Type {self.nation} to continue")
            yield Input(id="confirm-nation", placeholder=self.nation.replace("_", " "))
            yield Static("Capitalization and spaces/underscores are interchangeable.", classes="muted")
            yield Static("", id="confirm-error", markup=False)
            with Horizontal(classes="buttons"):
                yield Button("Confirm", variant="error", id="confirm")
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def pressed(self, event):
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "confirm":
            if confirmation_matches(self.query_one(Input).value, self.nation):
                self.dismiss(True)
            else:
                self.query_one("#confirm-error", Static).update(f"Enter the selected nation: {self.nation.replace('_', ' ')}")


class Deckhand(App):
    TITLE = "DECKHAND"
    SUB_TITLE = "NationStates - Card cleanup"
    BINDINGS = [("ctrl+q", "quit", "Quit"), ("ctrl+s", "scan", "Preview"),
        ("escape", "stop", "Stop")]
    CSS = """
    Screen { background: #0b1220; color: #dce7f7; }
    Header { background: #15223a; }
    Footer { background: #15223a; }
    #body { height: 1fr; }
    #sidebar { width: 38; background: #111d30; padding: 1 2; border-right: solid #263b59; }
    .eyebrow { color: #67ded0; text-style: bold; margin-bottom: 1; }
    .muted { color: #8b9fb9; }
    #sidebar Label { margin-top: 1; }
    #sidebar Button { width: 100%; margin-top: 0; }
    #sidebar Select, #sidebar Input { width: 100%; }
    #sidebar-content { height: 1fr; }
    .control-group { height: auto; border: round #263b59; padding: 0 1; margin-bottom: 1; }
    .control-group > Checkbox { width: 100%; }
    #fast-note { display: none; margin-bottom: 1; }
    #api-counts { height: 3; color: #8b9fb9; }
    #sale-actions { height: 3; display: none; }
    #sale-actions Button { width: 1fr; }
    #dialog.gift-review { width: 96; max-width: 95%; }
    #gift-cards { height: 14; min-height: 8; }
    #sale-list { height: auto; max-height: 15; }
    #sale-list Link { height: auto; margin-top: 1; }
    #dialog TextArea { height: 6; }
    #main { width: 1fr; padding: 1 2; }
    #hero { height: 4; color: #67ded0; text-style: bold; }
    #deck-totals { height: 4; margin-bottom: 1; }
    #deck-totals Static { width: 1fr; background: #111d30; border: round #263b59; padding: 0 1; margin-right: 1; }
    #stats { height: 4; background: #16263e; border-left: thick #67ded0; padding: 0 2; margin-bottom: 1; }
    DataTable { height: 1fr; min-height: 8; background: #0e192a; border: round #263b59; }
    #status { height: 2; color: #a8bfd9; margin-top: 1; }
    #request-status { height: 2; color: #8b9fb9; }
    #preview-eta { height: 1; color: #67ded0; }
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
    #gift-confirm-error, #confirm-error { color: #ff9393; height: auto; }
    #gift-source-hint, #gift-target-hint { height: auto; }
    #modal-error { color: #ff9393; }
    """

    @on(Button.Pressed, "#resolve-names")
    def resolve_names(self):
        if self.busy or self.demo or not self.account or not self.deck:
            return
        self.cancel_deck_load()
        account_id = self.account.id
        self.set_busy(True)
        contact = self.settings.contact.strip() or self.account.nation

        def resolved(cards):
            if self.account and self.account.id == account_id:
                self.deck = tuple(cards)
                self.display_names.update({c.key: c.name for c in cards if c.name})
                self.deck_cache[account_id] = self.deck
                self.invalidate()
                known = sum(bool(c.name) for c in cards)
                self.query_one("#status", Static).update(
                    f"Names available: {known}/{len(cards)} - preview required")
            self.set_busy(False)

        self.push_screen(NameResolution(self.deck, self.account.nation, contact,
            self.gate, self.catalog), resolved)

    @on(Button.Pressed, "#lookup-card")
    def lookup_card(self):
        if not self.demo:
            self.push_screen(CardLookup(self.catalog))

    def __init__(self, *, settings=None, demo=False):
        super().__init__()
        self.settings = settings or Settings()
        self.vault = Vault(self.settings.directory)
        self.catalog = CardCatalog(self.settings.directory / "cards.sqlite3")
        self.demo = demo
        if demo:
            self.settings.accounts = [Account("demo_nation", "Demo nation", "session")]
        self.account = self.settings.accounts[0] if self.settings.accounts else None
        self.plan = None
        self.deck = ()
        self.deck_cache = {}
        self.plan_cache = {}
        self.filter_cache = {}
        self.cache_times = {}
        self.deck_worker = None
        self.deck_generation = 0
        self.shown_account_id = None
        self.busy = False
        self.operation = None
        self.selected_card = None
        self.display_names = {}
        self.flag_accents = {}
        self.totals_cache = {}
        self.stop_event = asyncio.Event()
        self.gate = RateGate()
        self.session_api_calls = 0
        self.request_counter = RequestCounter(self.settings.directory)
        try:
            self.total_api_calls = self.request_counter.total()
        except (OSError, sqlite3.Error):
            self.total_api_calls = None
        self.gate.on_request = self.record_api_call
        self.loading_account = False
        self.eta_deadline = None
        self.eta_remaining = 0
        self.eta_unit = "bid checks"
        self.eta_requests_per_unit = 1

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            with Vertical(id="sidebar"):
                with VerticalScroll(id="sidebar-content"):
                    with Vertical(id="accounts-panel", classes="control-group"):
                        yield Select(self.account_options(), prompt="Choose a nation", id="accounts",
                            value=self.account.id if self.account else Select.NULL)
                        yield Button("Manage nations...", id="manage-fleet")
                        yield Button("API settings...", id="api-settings")
                    with Vertical(id="policy-panel", classes="control-group"):
                        yield Label("Junk this rarity and below")
                        yield Select([(r.label, r.name) for r in Rarity], value="COMMON", allow_blank=False, id="rarity")
                    with Vertical(id="protection-panel", classes="control-group"):
                        yield Checkbox("Protect collections", value=True, id="collections")
                        yield Checkbox("Protect sale listings", value=True, id="listings")
                        yield Checkbox("Protect my nations", value=True, id="own-nations")
                        yield Checkbox("Faster execution", value=False, id="fast-execution",
                            tooltip=execution_mode_notice(Policy(fast_execution=True)))
                        yield Static("Uses reviewed results only. No live rechecks.",
                            id="fast-note", classes="warning")
                        yield Button("Protected name rules...", id="name-rules")
                        yield Button("Protect selected card", id="protect-selected", disabled=True)
                    with Vertical(id="deck-panel", classes="control-group"):
                        yield Button("Preview cleanup", variant="primary", id="scan")
                        yield Button("Refresh deck", id="refresh-deck")
                        yield Button("Resolve card names", id="resolve-names", disabled=self.demo)
                        yield Button("Find card locally", id="lookup-card", disabled=self.demo)
                        yield Button("Gift cards...", id="gift-cards-open", disabled=self.demo)
                        yield Static("Preview protects bids above junk value. Faster execution trusts that review.", classes="muted")
                    with Vertical(id="appearance-panel", classes="control-group"):
                        yield Checkbox("Use flag colors", value=False, id="flag-theme")
                        yield Button("About Deckhand", id="about")
                yield Static(self.api_count_text(), id="api-counts")
            with Vertical(id="main"):
                yield Static("DECKHAND\nA cleaner deck. A clear decision.", id="hero")
                yield Static("Choose an account and preview your deck.\nNo cards have been changed.", id="stats")
                with Horizontal(id="deck-totals"):
                    yield Static("BANK\nUnavailable", id="bank-total", markup=False)
                    yield Static("DECK VALUE\nUnavailable", id="deck-value-total", markup=False)
                yield Select([("All cards", "all"), ("Eligible cards", "eligible"),
                    ("Ineligible cards", "ineligible")], value="all", allow_blank=False,
                    id="card-filter", disabled=True)
                yield Static("No preview to filter", id="filter-count", classes="muted")
                yield CardTable(id="cards", zebra_stripes=True, cursor_type="row",
                    tooltip="Click a column heading to sort; click again to reverse.")
                yield Static("Ready - preview is read-only", id="status")
                yield Static("", id="request-status")
                yield Rule()
                with Horizontal(classes="buttons"):
                    yield Button("Junk reviewed cards", variant="error", id="execute", disabled=True)
                with Horizontal(id="sale-actions"):
                    yield Button("Review sales at junk value", id="sell-equal")
                    yield Button("Review sales above junk value", id="sell-above")
                yield RichLog(id="activity", markup=False, wrap=True)
        yield Footer()

    async def open_progress(self, title):
        self.operation = OperationProgress(title)
        await self.push_screen(self.operation)

    def close_progress(self):
        if self.operation is not None:
            dialog, self.operation = self.operation, None
            if dialog.is_mounted:
                return dialog.dismiss(None)

    def progress_update(self, **kwargs):
        if self.operation is not None and self.operation.is_mounted:
            unit = "copies processed" if self.eta_unit == "copies" else "cards checked"
            self.operation.update_progress(**kwargs, unit=unit)

    def eta_text(self, text):
        if self.operation is not None and self.operation.is_mounted:
            display = re.sub(r" remaining - .*", " remaining", text)
            if display.startswith("Taking longer"):
                display = "Taking longer than expected"
            self.operation.set_estimate(display)

    @on(Checkbox.Changed, "#flag-theme")
    def flag_theme_changed(self):
        if self.loading_account or not self.account:
            return
        old = self.account.flag_theme
        self.account.flag_theme = self.query_one("#flag-theme", Checkbox).value
        try:
            if not self.demo:
                self.settings.save()
        except OSError:
            self.account.flag_theme = old
            with self.prevent(Checkbox.Changed):
                self.query_one("#flag-theme", Checkbox).value = old
            self.notify("Could not save appearance setting.", severity="error")
        self.update_flag_theme()

    def apply_accent(self, accent):
        self.register_theme(Theme(name="deckhand-nation", primary=accent, accent=accent,
            background="#0b1220", foreground="#dce7f7", surface="#15223a", panel="#111d30",
            warning="#ffd18a", error="#e45c78", success="#67ded0", dark=True))
        self.theme = "deckhand-nation"
        for widget in self.query("#hero, .eyebrow, .dialog-title"):
            widget.styles.color = accent
        for widget in self.query(".control-group"):
            widget.styles.border = ("round", accent)
        self.query_one("#stats").styles.border_left = ("thick", accent)

    def update_flag_theme(self):
        self.apply_accent(DEFAULT_ACCENT)
        if self.account and self.account.flag_theme:
            if self.account.id in self.flag_accents:
                self.apply_accent(self.flag_accents[self.account.id])
            elif not self.demo:
                self.load_flag_theme(self.account.id, self.account.nation)

    @work(group="flag-theme", exclusive=True, exit_on_error=False)
    async def load_flag_theme(self, account_id, nation):
        try:
            contact = self.settings.contact.strip() or nation
            async with NationStates(nation, contact, gate=self.gate) as api:
                data = await api.flag_image()
            accent = await asyncio.to_thread(flag_accent, data)
            self.flag_accents[account_id] = accent
            if self.account and self.account.id == account_id and self.account.flag_theme:
                self.apply_accent(accent)
        except Exception:
            if self.account and self.account.id == account_id and self.account.flag_theme:
                self.notify("Flag colors unavailable; using the default theme.", severity="warning")

    def show_totals(self, totals=None, *, loading=False, cached=False):
        suffix = " (cached)" if cached else ""
        bank = f"{totals[0]:,.2f}{suffix}" if totals else ("Loading..." if loading else "Unavailable")
        deck = f"{totals[1]:,.2f}{suffix}" if totals else ("Loading..." if loading else "Unavailable")
        self.query_one("#bank-total", Static).update(f"BANK\n{bank}")
        self.query_one("#deck-value-total", Static).update(f"DECK VALUE (estimated)\n{deck}")

    @work(group="deck-totals", exclusive=True, exit_on_error=False)
    async def load_totals(self, account_id, nation):
        try:
            if self.demo:
                totals = Decimal("12.34"), sum((c.market_value or Decimal(0)) * c.copies for c in demo_deck())
            else:
                async with NationStates(nation, self.settings.contact.strip() or nation, gate=self.gate) as api:
                    totals = await api.deck_totals()
            self.totals_cache[account_id] = totals
            if self.account and self.account.id == account_id:
                self.show_totals(totals)
        except Exception:
            self.totals_cache.pop(account_id, None)
            if self.account and self.account.id == account_id:
                self.show_totals()

    def account_options(self):
        return [(f"{a.label or a.nation} - {a.nation}" if a.label else a.nation, a.id) for a in self.settings.accounts]

    def on_mount(self):
        for ident, title in [("accounts-panel", "Nations & credentials"),
            ("policy-panel", "Cleanup limits"),
            ("protection-panel", "Protections"), ("deck-panel", "Deck tools"),
            ("appearance-panel", "Appearance & help")]:
            self.query_one(f"#{ident}").border_title = title
        self.set_interval(1, self.update_preview_eta)
        self.query_one(DataTable).add_columns("Card / Season", "Nation on card", "Rarity", "Copies", "Junk each", "Best bid", "Market value", "Decision")
        self.show_account()
        self.log_line("Demo mode: all data is synthetic and execution is disabled." if self.demo else "Welcome. Add your nations; credentials are only needed when junking.")

    def log_line(self, message):
        self.query_one("#activity", RichLog).write(message)

    def api_count_text(self):
        total = f"{self.total_api_calls:,}" if self.total_api_calls is not None else "unavailable"
        return f"API calls - session: {self.session_api_calls:,}\nLifetime: {total}"

    def record_api_call(self):
        self.session_api_calls += 1
        try:
            self.total_api_calls = self.request_counter.increment()
        except (OSError, sqlite3.Error):
            self.total_api_calls = None
        self.query_one("#api-counts", Static).update(self.api_count_text())

    def request_status(self, message):
        if not (self.busy and self.stop_event.is_set()):
            self.query_one("#request-status", Static).update(message)
            if self.operation is not None and self.operation.is_mounted:
                self.operation.request_state(message)
            if self.eta_deadline is not None and self.eta_remaining:
                # A newly advertised backoff must not leave an optimistic countdown.
                minimum = max(time.monotonic(), self.gate.next_request)
                minimum += self.eta_remaining * self.eta_requests_per_unit * (self.gate.interval + self.gate.response_seconds)
                self.eta_deadline = max(self.eta_deadline, minimum)
                self.update_preview_eta()

    def execution_estimate(self, completed, total, seconds):
        if self.stop_event.is_set():
            return
        self.eta_unit = "copies"
        self.preview_estimate(completed, total, seconds)
        self.progress_update(total=total, progress=completed)

    def preview_estimate(self, completed, total, seconds):
        self.progress_update(total=total, progress=completed)
        self.eta_remaining = total - completed
        self.eta_deadline = time.monotonic() + seconds
        self.update_preview_eta()

    def update_preview_eta(self):
        if self.eta_deadline is None:
            return
        seconds = max(0, math.ceil(self.eta_deadline - time.monotonic()))
        if not self.eta_remaining:
            message = ("Copy checks complete - finishing cleanup..." if self.eta_unit == "copies"
                else "Bid checks complete - finishing preview...")
        elif not seconds:
            message = "Taking longer than estimated - waiting for the current request..."
        else:
            minutes, seconds = divmod(seconds, 60)
            duration = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
            message = f"About {duration} remaining - {self.eta_remaining} {self.eta_unit} left (estimate)"
        self.eta_text(message)

    def clear_preview_eta(self):
        self.eta_deadline = None
        self.eta_remaining = 0
        self.eta_unit = "bid checks"
        self.eta_requests_per_unit = 1
        self.eta_text("")

    def preview_status(self, message):
        self.query_one("#status", Static).update(message)
        if self.operation is not None and self.operation.is_mounted:
            self.operation.stage(message)

    def invalidate(self, *, discard_cache=True):
        self.clear_preview_eta()
        if discard_cache and self.account:
            self.plan_cache.pop(self.account.id, None)
        self.plan = None
        self.update_sale_actions()
        self.query_one("#execute", Button).disabled = True
        self.query_one("#card-filter", Select).disabled = True
        self.render_cards()
        self.query_one("#stats", Static).update("Preview required\nClick Preview cleanup to check eligibility.")

    def show_account(self):
        self.cancel_deck_load()
        account_id = self.account.id if self.account else None
        self.deck = self.deck_cache.get(account_id, ())
        self.shown_account_id = self.account.id if self.account else None
        self.loading_account = True
        policy = self.settings.policy_for(self.account) if self.account else Policy()
        with self.prevent(Select.Changed, Checkbox.Changed):
            self.query_one("#rarity", Select).value = policy.maximum.name
            self.query_one("#collections", Checkbox).value = policy.protect_collections
            self.query_one("#listings", Checkbox).value = policy.protect_listings
            self.query_one("#own-nations", Checkbox).value = policy.protect_own_nations
            self.query_one("#fast-execution", Checkbox).value = policy.fast_execution
            self.query_one("#fast-note").display = policy.fast_execution
            self.query_one("#flag-theme", Checkbox).value = bool(self.account and self.account.flag_theme)
            self.query_one("#card-filter", Select).value = self.filter_cache.get(account_id, "all")
        self.loading_account = False
        self.update_flag_theme()
        self.invalidate(discard_cache=False)
        if account_id in self.totals_cache:
            self.show_totals(self.totals_cache[account_id], cached=True)
        elif self.account:
            self.show_totals(loading=True)
            self.load_totals(account_id, self.account.nation)
        else:
            self.show_totals()
        cached_plan = self.plan_cache.get(account_id)
        if cached_plan is not None and cached_plan.policy == policy:
            self.plan = cached_plan
        elif cached_plan is not None:
            self.plan_cache.pop(account_id, None)
        self.render_cards()
        self.set_busy(False)
        if account_id in self.deck_cache:
            if not self.demo:
                self.refresh_cached_names(account_id, self.deck_generation)
            stamp = time.strftime("%H:%M:%S", time.localtime(self.cache_times[account_id]))
            if self.plan:
                self.show_plan_summary()
            else:
                self.query_one("#stats", Static).update(Text(
                    f"{self.account.nation} - {len(self.deck)} unique cards\n"
                    "Eligibility not checked - click Preview cleanup"))
            self.query_one("#status", Static).update(
                f"Session cache - fetched at {stamp} - Refresh deck or Preview cleanup for live data")
            return
        if self.account:
            contact = self.settings.contact.strip() or self.account.nation
            self.query_one("#status", Static).update("Loading deck - read-only...")
            self.deck_worker = self.load_deck(self.account.id, self.account.nation,
                contact, self.deck_generation)

    @work(group="catalog-names", exclusive=True, exit_on_error=False)
    async def refresh_cached_names(self, account_id, generation):
        try:
            names = await asyncio.to_thread(self.catalog.names_for, [c.key for c in self.deck])
            self.display_names.update(names)
            if self.account and self.account.id == account_id and generation == self.deck_generation:
                self.deck = tuple(replace(c, name=c.name or names.get(c.key, "")) for c in self.deck)
                self.deck_cache[account_id] = self.deck
                self.render_cards()
        except (OSError, sqlite3.Error):
            self.notify("Local card names are unavailable.", severity="warning")

    def cancel_deck_load(self):
        self.deck_generation += 1
        self.query_one("#request-status", Static).update("")
        if self.deck_worker is not None:
            self.deck_worker.cancel()
            self.deck_worker = None

    @work(exclusive=True, group="deck-load", exit_on_error=False)
    async def load_deck(self, account_id, nation, contact, generation):
        try:
            if self.demo:
                cards = demo_deck()
            else:
                async with NationStates(nation, contact, gate=self.gate, status=self.request_status, catalog=self.catalog) as api:
                    cards = await api.deck()
            if generation != self.deck_generation or not self.account or self.account.id != account_id:
                return
            self.deck = tuple(cards)
            self.deck_cache[account_id] = self.deck
            self.cache_times[account_id] = time.time()
            self.render_cards()
            self.query_one("#resolve-names", Button).disabled = self.busy or self.demo
            self.query_one("#stats", Static).update(Text(
                f"{nation} - {len(self.deck)} unique cards - {sum(c.copies for c in self.deck)} copies\n"
                "Eligibility not checked - click Preview cleanup"))
            self.query_one("#status", Static).update("Deck loaded - no cards have been changed")
        except Exception as error:
            if generation == self.deck_generation:
                self.report_error(error)

    @on(Select.Changed, "#accounts")
    def selected_account(self, event):
        if event.value == self.shown_account_id:
            return
        self.account = next((a for a in self.settings.accounts if a.id == event.value), None)
        self.show_account()

    @on(Checkbox.Changed, "#fast-execution")
    def execution_mode_changed(self):
        enabled = self.query_one("#fast-execution", Checkbox).value
        self.query_one("#fast-note").display = enabled
        if self.loading_account or not self.account:
            return
        old = self.account.fast_execution
        self.account.fast_execution = enabled
        try:
            if not self.demo:
                self.settings.save()
        except OSError:
            self.account.fast_execution = old
            with self.prevent(Checkbox.Changed):
                self.query_one("#fast-execution", Checkbox).value = old
            self.query_one("#fast-note").display = old
            self.notify("Could not save execution mode.", severity="error")
            return
        if self.plan is not None:
            # Execution frequency changes no reviewed eligibility, identity, or count.
            self.plan = replace(self.plan, policy=replace(self.plan.policy, fast_execution=enabled))
            self.plan_cache[self.account.id] = self.plan
            mode = "Faster" if enabled else "Standard"
            self.query_one("#status", Static).update(f"{mode} execution selected - review retained")

    @on(Select.Changed, "#rarity")
    @on(Checkbox.Changed, "#collections")
    @on(Checkbox.Changed, "#listings")
    @on(Checkbox.Changed, "#own-nations")
    def policy_changed(self):
        self.query_one("#fast-note").display = self.query_one("#fast-execution", Checkbox).value
        if not self.loading_account and self.is_mounted:
            if self.account:
                policy = self.policy()
                self.account.maximum = policy.maximum.name
                self.account.protect_collections = policy.protect_collections
                self.account.protect_listings = policy.protect_listings
                self.account.protect_own_nations = policy.protect_own_nations
                self.account.fast_execution = policy.fast_execution
            self.invalidate()

    def policy(self):
        return Policy(Rarity[self.query_one("#rarity", Select).value],
            self.query_one("#collections", Checkbox).value,
            self.query_one("#listings", Checkbox).value,
            self.query_one("#own-nations", Checkbox).value,
            own_nations=tuple(a.nation for a in self.settings.accounts),
            protected_names=tuple(self.account.protected_names) if self.account else (),
            protected_substrings=tuple(self.account.protected_substrings) if self.account else (),
            fast_execution=self.query_one("#fast-execution", Checkbox).value)

    @on(Select.Changed, "#card-filter")
    def card_filter_changed(self):
        if self.is_mounted:
            if self.account:
                self.filter_cache[self.account.id] = self.query_one("#card-filter", Select).value
            self.render_cards()

    def render_cards(self):
        """Filter the view only; the reviewed cleanup plan stays intact."""
        table = self.query_one(DataTable)
        table.clear()
        self.selected_card = None
        self.query_one("#protect-selected", Button).disabled = True
        if self.plan is None:
            for card in self.deck:
                table.add_row(f"#{card.key.card_id} / S{card.key.season}",
                    Text(card.name or self.display_names.get(card.key) or "(unknown)"), card.rarity.label, str(card.copies),
                    str(card.rarity.junk), "-", str(card.market_value) if card.market_value is not None else "-", "Not checked",
                    key=f"{card.key.card_id}:{card.key.season}")
            table.resort()
            self.query_one("#filter-count", Static).update(
                f"Showing {len(self.deck)} unique cards - preview required for eligibility filters")
            return
        card_filter = self.query_one("#card-filter", Select).value
        for decision in self.plan.decisions:
            if card_filter == "eligible" and not decision.eligible:
                continue
            if card_filter == "ineligible" and decision.eligible:
                continue
            card = decision.card
            color = "#67ded0" if decision.eligible else "#8b9fb9"
            table.add_row(f"#{card.key.card_id} / S{card.key.season}",
                Text(card.name or self.display_names.get(card.key) or "(unknown)"), card.rarity.label, str(card.copies), str(card.rarity.junk),
                str(decision.highest_bid) if decision.highest_bid is not None else "-",
                str(card.market_value) if card.market_value is not None else "-",
                Text(decision.reason, style=color), key=f"{card.key.card_id}:{card.key.season}")
        table.resort()
        message = f"Showing {table.row_count} of {len(self.plan.decisions)} unique cards"
        if not table.row_count:
            message += " - No cards match this view"
        self.query_one("#filter-count", Static).update(message)

    def set_busy(self, value):
        self.busy = value
        if not value:
            self.query_one("#request-status", Static).update("")
        for widget in self.query("#sidebar Button, #sidebar Select, #sidebar Input, #sidebar Checkbox"):
            widget.disabled = value
        self.query_one("#execute", Button).disabled = value or not self.plan or not self.plan.copies or self.demo
        self.query_one("#card-filter", Select).disabled = value or self.plan is None
        self.query_one("#resolve-names", Button).disabled = value or self.demo or not self.deck
        self.query_one("#gift-cards-open", Button).disabled = value or self.demo or self.account is None
        self.query_one("#protect-selected", Button).disabled = value or self.selected_card is None
        self.update_sale_actions()

    def update_sale_actions(self):
        equal = bool(self.plan and self.plan.sale_candidates())
        above = bool(self.plan and self.plan.sale_candidates(above_junk=True))
        self.query_one("#sale-actions").display = not self.busy and (equal or above)
        self.query_one("#sell-equal", Button).display = equal
        self.query_one("#sell-above", Button).display = above

    def review_sales(self, *, above_junk=False):
        if not self.busy and self.plan and self.plan.sale_candidates(above_junk=above_junk):
            self.push_screen(SaleReview(self.plan, above_junk=above_junk))

    @on(Button.Pressed)
    def button(self, event):
        actions = {"scan": self.action_scan, "execute": self.start_execution,
            "add-account": self.add_account, "about": lambda: self.push_screen(About()),
            "protect-selected": self.protect_selected, "gift-cards-open": self.open_gifts,
            "manage-fleet": lambda: self.push_screen(FleetManagement()),
            "api-settings": lambda: self.push_screen(APISettings()),
            "credentials": self.save_credentials, "forget": self.forget_credentials,
            "remove": self.remove_account, "refresh-deck": self.refresh_deck,
            "name-rules": self.edit_name_rules, "sell-equal": self.review_sales,
            "sell-above": lambda: self.review_sales(above_junk=True)}
        action = actions.get(event.button.id)
        if action:
            action()

    @on(DataTable.RowSelected, "#cards")
    def card_selected(self, event):
        self.selected_card = next((c for c in self.deck
            if f"{c.key.card_id}:{c.key.season}" == event.row_key.value), None)
        self.query_one("#protect-selected", Button).disabled = self.busy or self.selected_card is None

    @work(group="protect", exit_on_error=False)
    async def protect_selected(self):
        if self.busy or not self.account or self.selected_card is None:
            return
        card, account = self.selected_card, self.account
        self.stop_event = asyncio.Event()
        self.set_busy(True)
        try:
            name = card.name
            if not name:
                contact = self.settings.contact.strip() or account.nation
                await self.open_progress("Resolve selected card name")
                async with NationStates(account.nation, contact, gate=self.gate,
                    catalog=self.catalog, status=self.request_status) as api:
                    info = await api.card_info(card.key)
                    if info.rarity != card.rarity:
                        raise ValueError("Card information changed; refresh the deck.")
                    name = info.name
            if self.stop_event.is_set():
                return
            old = list(account.protected_names)
            if name.casefold() not in {n.casefold() for n in old}:
                account.protected_names.append(name)
                try:
                    if not self.demo:
                        self.settings.save()
                except Exception:
                    account.protected_names = old
                    raise
            self.invalidate()
            self.notify(f"Protected {name} for {account.nation}, across all seasons.")
        except Exception as error:
            self.report_error(error)
        finally:
            self.close_progress()
            self.set_busy(False)

    def open_gifts(self):
        if self.busy or self.demo or not self.account:
            return
        recipients = [a for a in self.settings.accounts if a.nation != self.account.nation]
        if not recipients:
            self.notify("Save another nation first to use as the recipient.", severity="warning")
            return
        self.push_screen(GiftSetup(self.account, recipients), self.gifts_requested)

    def gifts_requested(self, options):
        if options is None or not self.account or self.busy:
            return
        recipient_id, minimum = options
        recipient = next((a for a in self.settings.accounts if a.id == recipient_id), None)
        if recipient is None or recipient.nation == self.account.nation:
            return
        self.cancel_deck_load()
        self.stop_event = asyncio.Event()
        self.set_busy(True)
        self.gift_worker(self.account, recipient, minimum)

    @work(group="network", exclusive=True, exit_on_error=False)
    async def gift_worker(self, source, recipient, minimum):
        supplied = None
        password = None
        attempted = False
        estimated_bank = None
        try:
            contact = self.settings.contact.strip() or source.nation
            await self.open_progress("Preparing card gifts")
            async with NationStates(source.nation, contact, gate=self.gate,
                status=self.request_status, catalog=self.catalog) as api:
                gifter = Gifter(api)
                plan = await gifter.preview(recipient.nation, minimum, stop=self.stop_event,
                    progress=self.scan_progress)
                await self.close_progress()
                if self.stop_event.is_set() or not await self.push_screen_wait(GiftReview(plan)):
                    return
                if not await self.push_screen_wait(GiftConfirm(plan)) or self.stop_event.is_set():
                    return
                if not any(a.id == recipient.id and a.nation == plan.recipient for a in self.settings.accounts):
                    raise ValueError("Recipient is no longer a saved nation")
                if not any(a.id == source.id and a.nation == plan.source for a in self.settings.accounts):
                    raise ValueError("Sender is no longer a saved nation")
                if source.backend == "encrypted":
                    supplied = await self.push_screen_wait(SecretPrompt(source))
                    if supplied is None:
                        return
                password = await asyncio.to_thread(self.vault.load, source,
                    master=supplied["master"] if supplied else None)
                if self.stop_event.is_set():
                    return
                # Consume source/recipient snapshots even if a write has uncertain outcome.
                attempted = True
                self.plan = None
                for account in (source, recipient):
                    self.totals_cache.pop(account.id, None)
                    self.deck_cache.pop(account.id, None)
                    self.plan_cache.pop(account.id, None)
                await self.open_progress("Gifting your cards")
                self.eta_unit = "copies"
                self.eta_requests_per_unit = 2
                def progress(done, total, card):
                    self.progress_update(total=total, progress=done)
                    self.preview_status(f"{done} gifts sent to {recipient.nation}")
                    self.log_line(f"Gifted #{card.key.card_id} / S{card.key.season} to {recipient.nation}.")
                result = await gifter.execute(plan, password, confirmed_source=source.nation,
                    confirmed_recipient=recipient.nation, stop=self.stop_event, progress=progress, estimate=self.execution_estimate)
                estimated_bank = result.bank
                self.log_line(f"{result.gifted} gifted, {result.skipped} skipped; "
                    f"estimated bank {result.bank:.2f}. {result.reason}.")
                self.query_one("#status", Static).update(
                    f"{result.reason}: {result.gifted} gifted to {recipient.nation}; estimated bank {result.bank:.2f}. Refresh deck.")
        except Exception as error:
            self.report_error(error)
        finally:
            password = None
            if supplied:
                supplied.clear()
            self.close_progress()
            self.clear_preview_eta()
            if attempted:
                self.show_totals()
                if estimated_bank is not None:
                    self.query_one("#bank-total", Static).update(f"BANK (estimated)\n{estimated_bank:,.2f}")
                self.deck = ()
                self.invalidate()
            self.set_busy(False)

    def edit_name_rules(self):
        if not self.busy and self.account:
            self.push_screen(ProtectedNames(self.account), self.name_rules_saved)

    def name_rules_saved(self, rules):
        if rules is None or not self.account:
            return
        old = self.account.protected_names, self.account.protected_substrings
        self.account.protected_names, self.account.protected_substrings = rules
        self.invalidate()
        try:
            if not self.demo:
                self.settings.save()
        except OSError as error:
            self.account.protected_names, self.account.protected_substrings = old
            self.report_error(error)

    def refresh_deck(self):
        if self.busy or not self.account:
            return
        self.cancel_deck_load()
        self.invalidate()
        self.deck_cache.pop(self.account.id, None)
        self.totals_cache.pop(self.account.id, None)
        self.show_totals(loading=True)
        self.load_totals(self.account.id, self.account.nation)
        self.query_one("#status", Static).update("Refreshing live deck - read-only...")
        contact = self.settings.contact.strip() or self.account.nation
        self.deck_worker = self.load_deck(self.account.id, self.account.nation,
            contact, self.deck_generation)

    def show_plan_summary(self):
        self.query_one("#stats", Static).update(Text(
            f"{self.plan.copies} copies eligible  -  {self.plan.proceeds:.2f} bank estimated\n"
            f"{self.plan.nation}  /  {self.plan.policy.maximum.label} and below  /  {len(self.plan.decisions)} unique cards"))

    def action_scan(self):
        if self.busy:
            return
        if not self.account:
            self.notify("Add or select an account first.", severity="warning")
            return
        contact = self.settings.contact.strip()
        if not self.demo and not contact:
            self.notify("Set a contact nation or email in API settings.", severity="warning")
            self.push_screen(APISettings())
            return
        policy = self.policy()
        self.account.maximum = policy.maximum.name
        self.account.protect_collections = policy.protect_collections
        self.account.protect_listings = policy.protect_listings
        self.account.protect_own_nations = policy.protect_own_nations
        self.account.fast_execution = policy.fast_execution
        self.settings.contact = contact
        try:
            if not self.demo:
                self.settings.save()
        except OSError:
            self.notify("Could not save settings.", severity="error")
            return
        self.cancel_deck_load()
        self.invalidate()
        self.stop_event = asyncio.Event()
        self.set_busy(True)
        self.progress_update(total=100, progress=0)
        self.eta_text("Estimating after deck and protections load...")
        self.scan(self.account.nation, policy, contact)

    @work(exclusive=True, group="network", exit_on_error=False)
    async def scan(self, nation, policy, contact):
        try:
            await self.open_progress("Preview cleanup")
            if self.demo:
                self.plan = demo_plan(nation, policy)
            else:
                async with NationStates(nation, contact, gate=self.gate, status=self.request_status, catalog=self.catalog) as api:
                    self.plan = await Cleaner(api).preview(policy, progress=self.scan_progress,
                        stop=self.stop_event, status=self.preview_status, estimate=self.preview_estimate)
            self.deck = tuple(d.card for d in self.plan.decisions)
            self.deck_cache[self.account.id] = self.deck
            self.plan_cache[self.account.id] = self.plan
            self.cache_times[self.account.id] = time.time()
            self.render_cards()
            self.show_plan_summary()
            self.load_totals(self.account.id, self.account.nation)
            self.query_one("#status", Static).update(
                "Preview complete - " + ("faster execution selected" if self.plan.policy.fast_execution
                    else "standard execution checks") + (" - DEMO" if self.demo else ""))
            self.log_line(f"Preview for {nation}: {self.plan.copies} copies eligible.")
        except Exception as error:
            self.invalidate()
            self.report_error(error)
        finally:
            self.clear_preview_eta()
            self.close_progress()
            self.set_busy(False)

    def scan_progress(self, current, total, decision):
        if self.eta_deadline is None:
            self.progress_update(total=total, progress=current)

    def action_stop(self):
        if isinstance(self.screen, NameResolution):
            self.screen.action_cancel_resolution()
            return
        if self.busy:
            self.clear_preview_eta()
            self.stop_event.set()
            self.query_one("#status", Static).update("Stopping after the current request completes...")

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
                "This cannot be undone. New cards are never added to this run.\n"
                + execution_mode_notice(plan.policy)))
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
            self.plan_cache.pop(account.id, None)
            self.deck_cache.pop(account.id, None)
            await self.open_progress("Junk reviewed cards")
            self.eta_requests_per_unit = (2 if plan.policy.fast_execution else
                5 + int(plan.policy.protect_collections) + int(plan.policy.protect_listings))
            async with NationStates(plan.nation, self.settings.contact, gate=self.gate, status=self.request_status, catalog=self.catalog) as api:
                result = await Cleaner(api).execute(plan, secret, confirmed_nation=plan.nation,
                    stop=self.stop_event, progress=self.run_progress, estimate=self.execution_estimate)
            self.log_line(f"{plan.nation}: {result.junked} junked, {result.skipped} skipped, {result.proceeds:.2f} bank."
                + (" Stopped." if result.stopped else " Finished."))
            self.query_one("#status", Static).update("Run ended - rescan for a fresh preview")
        except Exception as error:
            self.plan = None
            self.plan_cache.pop(account.id, None)
            self.report_error(error)
        finally:
            self.clear_preview_eta()
            self.close_progress()
            self.totals_cache.pop(account.id, None)
            self.show_totals(loading=True)
            self.load_totals(account.id, account.nation)
            secret = None
            master = None
            if supplied:
                supplied.clear()
            self.set_busy(False)

    def run_progress(self, done, skipped, message):
        self.log_line(f"{done} junked - {skipped} skipped - {message}")
        self.query_one("#status", Static).update(f"{done} junked - {skipped} skipped")

    def report_error(self, error):
        # Known application exceptions contain safe messages. Never print
        # arbitrary backend exceptions, reprs, request headers or tracebacks.
        self.query_one("#request-status", Static).update("")
        from .api import APIError
        from .credentials import CredentialError
        from .hello import HelloError
        message = str(error) if isinstance(error, (APIError, CredentialError, HelloError)) else f"{type(error).__name__}: operation failed; no automatic retry."
        self.log_line(message)
        self.query_one("#status", Static).update(Text(message))
        self.notify(message, severity="error")

    @on(FleetAction)
    def manage_action(self, event):
        actions = {"add-account": self.add_account, "credentials": self.save_credentials,
            "forget": self.forget_credentials, "remove": self.remove_account}
        action = actions.get(event.action)
        if action:
            action()

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
            self.log_line(f"Added {account.nation}.")
            self.call_after_refresh(self.save_credentials)
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
                self.deck_cache.pop(account.id, None)
                self.plan_cache.pop(account.id, None)
                self.filter_cache.pop(account.id, None)
                self.cache_times.pop(account.id, None)
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
    return Plan.create(nation, policy, [decide(c, policy, {CardKey(104, 4)},
        {CardKey(106, 4)}, Decimal("0.08") if c.key.card_id == 102 else None) for c in demo_deck()])


def demo_deck():
    cards = [Card(CardKey(101, 4), Rarity.COMMON, 3, "Silver Harbour"),
        Card(CardKey(102, 4), Rarity.COMMON, 2, "Moonlit Republic"),
        Card(CardKey(103, 3), Rarity.UNCOMMON, 1, "Cedar Isles"),
        Card(CardKey(104, 4), Rarity.COMMON, 1, "Amber Fields"),
        Card(CardKey(105, 2), Rarity.EPIC, 1, "Sunward"),
        Card(CardKey(106, 4), Rarity.COMMON, 2, "Starlight Coast")]
    values = ("2.50", "10.00", "0.20", "0.01", "100.00", "1.00")
    return [replace(c, market_value=Decimal(v)) for c, v in zip(cards, values)]


def main():
    parser = argparse.ArgumentParser(description="Deckhand - NationStates card cleanup")
    parser.add_argument("--demo", action="store_true", help="Synthetic preview; never contacts NationStates")
    parser.add_argument("--config-dir", type=Path, help="Override the local account/vault directory")
    args = parser.parse_args()
    Deckhand(settings=Settings(args.config_dir), demo=args.demo).run()


if __name__ == "__main__":
    main()

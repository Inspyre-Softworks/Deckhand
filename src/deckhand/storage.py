"""Account metadata and atomic, owner-only file writes (POSIX permissions)."""
from dataclasses import dataclass, asdict, field, replace
import json
import os
from pathlib import Path
import tempfile
import sqlite3
from uuid import uuid4
from platformdirs import user_config_path
from .models import Policy, Rarity, nation_id


class RequestCounter:
    """Persist aggregate counts only; SQLite serializes concurrent increments."""
    def __init__(self, directory):
        self.path = Path(directory) / "api_usage.sqlite3"

    def total(self):
        if not self.path.exists():
            return 0
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT total FROM api_usage WHERE id=1").fetchone()
            return row[0] if row else 0

    def increment(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS api_usage (id INTEGER PRIMARY KEY, total INTEGER NOT NULL)")
            db.execute("INSERT INTO api_usage VALUES (1, 1) ON CONFLICT(id) DO UPDATE SET total=total+1")
            return db.execute("SELECT total FROM api_usage WHERE id=1").fetchone()[0]


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".deckhand-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@dataclass
class Account:
    nation: str
    label: str = ""
    backend: str = "session"
    id: str = field(default_factory=lambda: uuid4().hex)
    maximum: str = "COMMON"
    protect_collections: bool = True
    protect_listings: bool = True
    protect_own_nations: bool = True
    protected_names: list[str] = field(default_factory=list)
    protected_substrings: list[str] = field(default_factory=list)
    fast_execution: bool = False
    flag_theme: bool = False

    def __post_init__(self):
        self.nation = nation_id(self.nation)
        if len(self.id) != 32 or any(c not in "0123456789abcdef" for c in self.id):
            raise ValueError("Invalid account identifier")
        if self.backend not in ("session", "encrypted", "hello", "keyring", "plaintext"):
            raise ValueError("Unknown credential backend")
        if type(self.flag_theme) is not bool:
            raise ValueError("flag_theme must be a boolean")
        if type(self.fast_execution) is not bool:
            raise ValueError("fast_execution must be a boolean")
        Rarity[self.maximum]
        for values in (self.protected_names, self.protected_substrings):
            if not isinstance(values, (list, tuple)) or not all(isinstance(value, str) for value in values):
                raise ValueError("Protected name rules must be lists of text entries")

    @property
    def policy(self):
        return Policy(Rarity[self.maximum], self.protect_collections, self.protect_listings,
            self.protect_own_nations, protected_names=tuple(self.protected_names),
            protected_substrings=tuple(self.protected_substrings), fast_execution=self.fast_execution)


class Settings:
    def policy_for(self, account):
        return replace(account.policy, own_nations=tuple(a.nation for a in self.accounts))

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else user_config_path("ns-deckhand", appauthor=False)
        self.accounts = []
        self.contact = ""
        path = self.directory / "accounts.json"
        if path.exists():
            data = json.loads(path.read_text("utf-8"))
            self.accounts = [Account(**item) for item in data["accounts"]]
            self.contact = data.get("contact", "")

    def save(self):
        atomic_write(self.directory / "accounts.json", json.dumps({
            "version": 1, "contact": self.contact,
            "accounts": [asdict(a) for a in self.accounts],
        }, indent=2).encode())

    def add(self, account):
        if any(a.nation == account.nation for a in self.accounts):
            raise ValueError("That nation already has an account")
        self.accounts.append(account)
        try:
            self.save()
        except Exception:
            self.accounts.remove(account)
            raise

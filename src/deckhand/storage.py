"""Account metadata and atomic, owner-only file writes (POSIX permissions)."""
from dataclasses import dataclass, asdict, field
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4
from platformdirs import user_config_path
from .models import Policy, Rarity, nation_id


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

    def __post_init__(self):
        self.nation = nation_id(self.nation)
        if len(self.id) != 32 or any(c not in "0123456789abcdef" for c in self.id):
            raise ValueError("Invalid account identifier")
        if self.backend not in ("session", "encrypted", "hello", "keyring", "plaintext"):
            raise ValueError("Unknown credential backend")
        Rarity[self.maximum]

    @property
    def policy(self):
        return Policy(Rarity[self.maximum], self.protect_collections, self.protect_listings)


class Settings:
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

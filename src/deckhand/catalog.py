"""Persistent public card metadata, never ownership or cleanup authority."""
from contextlib import closing
from pathlib import Path
import sqlite3

from .models import Card, CardKey, Rarity, name_match


class CardCatalog:
    """A local catalog keyed by card number AND season.

    Operations open their own connection and may be offloaded to a worker thread.
    Lookup returns metadata Cards with copies=1, not owned quantities.
    """

    def __init__(self, path):
        self.path = Path(path)

    def record(self, cards):
        # Validate/materialize before opening a transaction; unnamed observations
        # must never erase a previously resolved name.
        rows = [(c.key.card_id, c.key.season, c.name.strip(),
                 name_match(c.name), int(c.rarity)) for c in cards]
        if not rows:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS cards (
                card_id INTEGER NOT NULL, season INTEGER NOT NULL,
                name TEXT NOT NULL, normalized_name TEXT NOT NULL,
                rarity INTEGER NOT NULL, PRIMARY KEY(card_id, season))""")
            db.execute("CREATE INDEX IF NOT EXISTS cards_name ON cards(normalized_name)")
            db.executemany("""INSERT INTO cards VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(card_id, season) DO UPDATE SET
                name=CASE WHEN excluded.name='' THEN cards.name ELSE excluded.name END,
                normalized_name=CASE WHEN excluded.name='' THEN cards.normalized_name
                    ELSE excluded.normalized_name END, rarity=excluded.rarity""", rows)

    def names_for(self, keys):
        """Return known display names for exact identities using one connection."""
        if not self.path.exists():
            return {}
        result = {}
        with closing(sqlite3.connect(self.path)) as db:
            for key in keys:
                row = db.execute("SELECT name FROM cards WHERE card_id=? AND season=?",
                    (key.card_id, key.season)).fetchone()
                if row and row[0].strip():
                    result[key] = row[0].strip()
        return result

    def lookup(self, *, name=None, card_id=None, season=None):
        """Exact normalized name OR positive card number; all seasons by default.

        Unknown cards return an empty list. No network request is made.
        """
        if (name is None) == (card_id is None):
            raise ValueError("Provide either a name or a card number.")
        if card_id is not None and (type(card_id) is not int or card_id < 1):
            raise ValueError("Card number must be a positive integer.")
        if season is not None and (type(season) is not int or season < 1):
            raise ValueError("Season must be a positive integer.")
        if name is not None and not name_match(name):
            raise ValueError("Enter a card name.")
        if not self.path.exists():
            return []
        column, value = ('normalized_name', name_match(name)) if name is not None else ('card_id', card_id)
        query = f"SELECT card_id, season, name, rarity FROM cards WHERE {column}=?"
        params = [value]
        if season is not None:
            query += " AND season=?"
            params.append(season)
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute(query + " ORDER BY card_id, season", params).fetchall()
        return [Card(CardKey(number, s), Rarity(rarity), name=n) for number, s, n, rarity in rows]

"""Search history manager for KDP Scout GUI.

Logs every search/action across all tools into a dedicated SQLite table
so users can browse, review, and export past results.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from kdp_scout.config import Config

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS search_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    tool        TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    query       TEXT,
    result_count INTEGER DEFAULT 0,
    results     TEXT,
    notes       TEXT
);
"""


class SearchHistory:
    """Singleton-ish history manager that writes to the app DB."""

    _instance: Optional["SearchHistory"] = None

    @classmethod
    def instance(cls) -> "SearchHistory":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        db_path = Config.get_db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------
    def log(
        self,
        tool: str,
        action: str,
        query: str = "",
        results: list | dict | None = None,
        result_count: int | None = None,
        notes: str = "",
    ):
        """Record a search / action in the history table."""
        try:
            results_json = None
            if results is not None:
                # Convert sqlite3.Row objects to dicts
                if isinstance(results, list):
                    clean = []
                    for r in results:
                        if isinstance(r, dict):
                            clean.append(r)
                        elif isinstance(r, (tuple, list)):
                            clean.append(list(r))
                        else:
                            try:
                                clean.append(dict(r))
                            except Exception:
                                clean.append(str(r))
                    results_json = json.dumps(clean, default=str, ensure_ascii=False)
                else:
                    results_json = json.dumps(results, default=str, ensure_ascii=False)

            if result_count is None and isinstance(results, list):
                result_count = len(results)
            elif result_count is None:
                result_count = 0

            self._conn.execute(
                "INSERT INTO search_history (timestamp, tool, action, query, result_count, results, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    tool,
                    action,
                    query or "",
                    result_count,
                    results_json,
                    notes,
                ),
            )
            self._conn.commit()
            logger.debug("History logged: %s / %s (%d results)", tool, action, result_count)
        except Exception:
            logger.exception("Failed to log search history")

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------
    def get_all(self, limit: int = 500) -> list[dict]:
        """Return recent history entries (newest first), without results blob."""
        rows = self._conn.execute(
            "SELECT id, timestamp, tool, action, query, result_count, notes "
            "FROM search_history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_results(self, history_id: int) -> list | dict | None:
        """Return the full results JSON for a given history entry."""
        row = self._conn.execute(
            "SELECT results FROM search_history WHERE id = ?", (history_id,)
        ).fetchone()
        if row and row["results"]:
            try:
                return json.loads(row["results"])
            except Exception:
                return None
        return None

    def get_entry(self, history_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM search_history WHERE id = ?", (history_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_entry(self, history_id: int):
        self._conn.execute("DELETE FROM search_history WHERE id = ?", (history_id,))
        self._conn.commit()

    def clear_all(self):
        self._conn.execute("DELETE FROM search_history")
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

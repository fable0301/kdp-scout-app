"""SQLite database management for KDP Scout.

Handles schema creation, migrations, and provides repository classes
for each entity type.

New in this version:
- book_snapshots: added ku_eligible, price_hardcover, series_name,
  also_bought_asins, formats_available, language, publisher, review_histogram
- keyword_metrics: added top10_avg_bsr, top10_asins, competition_score,
  ku_ratio, median_reviews, marketplace
- bsr_category_history: new table for per-category BSR tracking over time
- competition_snapshots: new table for search-probe results per keyword
"""

import os
import sqlite3
import logging
from datetime import datetime, date
from pathlib import Path

from kdp_scout.config import Config

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    category TEXT,
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS keyword_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    snapshot_date TEXT NOT NULL,
    estimated_volume INTEGER,
    volume_source TEXT,
    competition_count INTEGER,
    autocomplete_position INTEGER,
    avg_bsr_top_results REAL,
    suggested_bid REAL,
    impressions INTEGER,
    clicks INTEGER,
    orders INTEGER,
    top10_avg_bsr REAL,
    top10_asins TEXT,
    competition_score REAL,
    ku_ratio REAL,
    median_reviews INTEGER,
    marketplace TEXT DEFAULT 'us',
    UNIQUE(keyword_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asin TEXT NOT NULL UNIQUE,
    title TEXT,
    author TEXT,
    is_own INTEGER DEFAULT 0,
    added_date TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS book_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id),
    snapshot_date TEXT NOT NULL,
    bsr_overall INTEGER,
    bsr_category TEXT,
    price_kindle REAL,
    price_paperback REAL,
    price_hardcover REAL,
    review_count INTEGER,
    avg_rating REAL,
    page_count INTEGER,
    estimated_daily_sales REAL,
    estimated_monthly_revenue REAL,
    ku_eligible INTEGER DEFAULT 0,
    series_name TEXT,
    also_bought_asins TEXT,
    formats_available TEXT,
    language TEXT,
    publisher TEXT,
    review_histogram TEXT,
    UNIQUE(book_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS keyword_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    book_id INTEGER NOT NULL REFERENCES books(id),
    snapshot_date TEXT NOT NULL,
    rank_position INTEGER,
    source TEXT,
    UNIQUE(keyword_id, book_id, snapshot_date)
);

CREATE TABLE IF NOT EXISTS ads_search_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_name TEXT,
    ad_group TEXT,
    search_term TEXT NOT NULL,
    keyword_match_type TEXT,
    impressions INTEGER,
    clicks INTEGER,
    ctr REAL,
    spend REAL,
    sales REAL,
    acos REAL,
    orders INTEGER,
    report_date TEXT NOT NULL,
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    browse_node_id TEXT UNIQUE,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id),
    path TEXT,
    books_count INTEGER,
    bsr_for_top_1 INTEGER,
    bsr_for_top_20 INTEGER,
    last_scanned TEXT
);

CREATE TABLE IF NOT EXISTS bsr_category_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id),
    snapshot_date TEXT NOT NULL,
    category_name TEXT NOT NULL,
    rank INTEGER NOT NULL,
    UNIQUE(book_id, snapshot_date, category_name)
);

CREATE TABLE IF NOT EXISTS competition_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id),
    snapshot_date TEXT NOT NULL,
    marketplace TEXT DEFAULT 'us',
    competition_count INTEGER,
    avg_bsr_top10 REAL,
    median_reviews INTEGER,
    ku_ratio REAL,
    top_asins TEXT,
    raw_results TEXT,
    UNIQUE(keyword_id, snapshot_date, marketplace)
);
"""

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_keywords_keyword ON keywords(keyword);
CREATE INDEX IF NOT EXISTS idx_keywords_source ON keywords(source);
CREATE INDEX IF NOT EXISTS idx_keywords_category ON keywords(category);
CREATE INDEX IF NOT EXISTS idx_keywords_active ON keywords(is_active);

CREATE INDEX IF NOT EXISTS idx_keyword_metrics_keyword_id ON keyword_metrics(keyword_id);
CREATE INDEX IF NOT EXISTS idx_keyword_metrics_date ON keyword_metrics(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_keyword_metrics_marketplace ON keyword_metrics(marketplace);

CREATE INDEX IF NOT EXISTS idx_books_asin ON books(asin);
CREATE INDEX IF NOT EXISTS idx_books_is_own ON books(is_own);

CREATE INDEX IF NOT EXISTS idx_book_snapshots_book_id ON book_snapshots(book_id);
CREATE INDEX IF NOT EXISTS idx_book_snapshots_date ON book_snapshots(snapshot_date);

CREATE INDEX IF NOT EXISTS idx_keyword_rankings_keyword ON keyword_rankings(keyword_id);
CREATE INDEX IF NOT EXISTS idx_keyword_rankings_book ON keyword_rankings(book_id);
CREATE INDEX IF NOT EXISTS idx_keyword_rankings_date ON keyword_rankings(snapshot_date);

CREATE INDEX IF NOT EXISTS idx_ads_search_terms_term ON ads_search_terms(search_term);
CREATE INDEX IF NOT EXISTS idx_ads_search_terms_campaign ON ads_search_terms(campaign_name);
CREATE INDEX IF NOT EXISTS idx_ads_search_terms_date ON ads_search_terms(report_date);

CREATE INDEX IF NOT EXISTS idx_categories_browse_node ON categories(browse_node_id);
CREATE INDEX IF NOT EXISTS idx_categories_parent ON categories(parent_id);

CREATE INDEX IF NOT EXISTS idx_bsr_category_history_book ON bsr_category_history(book_id);
CREATE INDEX IF NOT EXISTS idx_bsr_category_history_date ON bsr_category_history(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_bsr_category_history_category ON bsr_category_history(category_name);

CREATE INDEX IF NOT EXISTS idx_competition_snapshots_keyword ON competition_snapshots(keyword_id);
CREATE INDEX IF NOT EXISTS idx_competition_snapshots_date ON competition_snapshots(snapshot_date);
"""


def get_connection():
    """Get a database connection, creating the database if needed.

    Returns:
        sqlite3.Connection with row factory set to sqlite3.Row.
    """
    db_path = Config.get_db_path()

    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')

    return conn


def init_db():
    """Initialize the database schema, indexes, and run migrations."""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(INDEX_SQL)

        _run_migrations(conn)

        conn.commit()
        logger.info(f'Database initialized at {Config.get_db_path()}')
    finally:
        conn.close()


def _run_migrations(conn):
    """Run all pending schema migrations in order."""
    _migrate_add_score_column(conn)
    _migrate_book_snapshots_v2(conn)
    _migrate_keyword_metrics_v2(conn)


def _migrate_add_score_column(conn):
    """Add score column to keywords table if it doesn't exist."""
    cursor = conn.execute("PRAGMA table_info(keywords)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'score' not in columns:
        conn.execute('ALTER TABLE keywords ADD COLUMN score REAL DEFAULT 0')
        logger.info('Migration: added score column to keywords table')


def _migrate_book_snapshots_v2(conn):
    """Add new columns to book_snapshots if they don't exist."""
    cursor = conn.execute("PRAGMA table_info(book_snapshots)")
    columns = [row[1] for row in cursor.fetchall()]

    new_columns = [
        ('price_hardcover', 'REAL'),
        ('ku_eligible', 'INTEGER DEFAULT 0'),
        ('series_name', 'TEXT'),
        ('also_bought_asins', 'TEXT'),
        ('formats_available', 'TEXT'),
        ('language', 'TEXT'),
        ('publisher', 'TEXT'),
        ('review_histogram', 'TEXT'),
    ]

    for col_name, col_def in new_columns:
        if col_name not in columns:
            conn.execute(f'ALTER TABLE book_snapshots ADD COLUMN {col_name} {col_def}')
            logger.info(f'Migration: added {col_name} to book_snapshots')


def _migrate_keyword_metrics_v2(conn):
    """Add new columns to keyword_metrics if they don't exist."""
    cursor = conn.execute("PRAGMA table_info(keyword_metrics)")
    columns = [row[1] for row in cursor.fetchall()]

    new_columns = [
        ('top10_avg_bsr', 'REAL'),
        ('top10_asins', 'TEXT'),
        ('competition_score', 'REAL'),
        ('ku_ratio', 'REAL'),
        ('median_reviews', 'INTEGER'),
        ('marketplace', "TEXT DEFAULT 'us'"),
    ]

    for col_name, col_def in new_columns:
        if col_name not in columns:
            conn.execute(f'ALTER TABLE keyword_metrics ADD COLUMN {col_name} {col_def}')
            logger.info(f'Migration: added {col_name} to keyword_metrics')


class KeywordRepository:
    """Data access for keywords and keyword_metrics tables."""

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()

    def find_by_keyword(self, keyword):
        cursor = self._conn.execute(
            'SELECT * FROM keywords WHERE keyword = ?',
            (keyword.lower().strip(),),
        )
        return cursor.fetchone()

    def upsert_keyword(self, keyword, source='autocomplete', category=None):
        keyword = keyword.lower().strip()
        now = datetime.now().isoformat()

        existing = self.find_by_keyword(keyword)
        if existing:
            self._conn.execute(
                'UPDATE keywords SET last_updated = ? WHERE id = ?',
                (now, existing['id']),
            )
            self._conn.commit()
            return existing['id'], False

        cursor = self._conn.execute(
            'INSERT INTO keywords (keyword, source, category, first_seen, last_updated) '
            'VALUES (?, ?, ?, ?, ?)',
            (keyword, source, category, now, now),
        )
        self._conn.commit()
        return cursor.lastrowid, True

    def add_metric(self, keyword_id, autocomplete_position=None, **kwargs):
        """Add a keyword_metrics snapshot for today.

        Accepts original fields plus new v2 fields:
        top10_avg_bsr, top10_asins, competition_score, ku_ratio,
        median_reviews, marketplace.
        """
        today = date.today().isoformat()

        existing = self._conn.execute(
            'SELECT * FROM keyword_metrics WHERE keyword_id = ? AND snapshot_date = ?',
            (keyword_id, today),
        ).fetchone()

        all_metric_fields = [
            'estimated_volume', 'volume_source', 'competition_count',
            'avg_bsr_top_results', 'suggested_bid', 'impressions',
            'clicks', 'orders',
            # v2 new fields
            'top10_avg_bsr', 'top10_asins', 'competition_score',
            'ku_ratio', 'median_reviews', 'marketplace',
        ]

        if existing:
            updates = []
            params = []
            if autocomplete_position is not None:
                updates.append('autocomplete_position = ?')
                params.append(autocomplete_position)
            for field in all_metric_fields:
                val = kwargs.get(field)
                if val is not None:
                    updates.append(f'{field} = ?')
                    params.append(val)
            if updates:
                params.append(existing['id'])
                self._conn.execute(
                    f'UPDATE keyword_metrics SET {", ".join(updates)} WHERE id = ?',
                    params,
                )
        else:
            self._conn.execute(
                'INSERT INTO keyword_metrics '
                '(keyword_id, snapshot_date, autocomplete_position, '
                'estimated_volume, volume_source, competition_count, '
                'avg_bsr_top_results, suggested_bid, impressions, clicks, orders, '
                'top10_avg_bsr, top10_asins, competition_score, '
                'ku_ratio, median_reviews, marketplace) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    keyword_id,
                    today,
                    autocomplete_position,
                    kwargs.get('estimated_volume'),
                    kwargs.get('volume_source'),
                    kwargs.get('competition_count'),
                    kwargs.get('avg_bsr_top_results'),
                    kwargs.get('suggested_bid'),
                    kwargs.get('impressions'),
                    kwargs.get('clicks'),
                    kwargs.get('orders'),
                    kwargs.get('top10_avg_bsr'),
                    kwargs.get('top10_asins'),
                    kwargs.get('competition_score'),
                    kwargs.get('ku_ratio'),
                    kwargs.get('median_reviews'),
                    kwargs.get('marketplace', 'us'),
                ),
            )
        self._conn.commit()

    def get_all_keywords(self, active_only=True):
        query = 'SELECT * FROM keywords'
        if active_only:
            query += ' WHERE is_active = 1'
        query += ' ORDER BY last_updated DESC'
        return self._conn.execute(query).fetchall()

    def get_keyword_count(self):
        row = self._conn.execute('SELECT COUNT(*) as cnt FROM keywords').fetchone()
        return row['cnt']

    def get_keywords_with_latest_metrics(self, limit=20, min_score=0, order_by='score'):
        if order_by == 'score':
            order_clause = """
                ORDER BY k.score DESC,
                    CASE WHEN km.autocomplete_position IS NOT NULL THEN 0 ELSE 1 END,
                    km.autocomplete_position ASC
            """
        elif order_by == 'impressions':
            order_clause = """
                ORDER BY km.impressions DESC NULLS LAST,
                    k.score DESC
            """
        else:
            order_clause = """
                ORDER BY
                    CASE WHEN km.autocomplete_position IS NOT NULL THEN 0 ELSE 1 END,
                    km.autocomplete_position ASC,
                    k.last_updated DESC
            """

        query = f"""
            SELECT k.id, k.keyword, k.source, k.first_seen, k.category, k.score,
                   km.autocomplete_position, km.snapshot_date,
                   km.estimated_volume, km.competition_count,
                   km.avg_bsr_top_results, km.impressions, km.clicks, km.orders,
                   km.top10_avg_bsr, km.competition_score, km.ku_ratio,
                   km.median_reviews, km.marketplace
            FROM keywords k
            LEFT JOIN keyword_metrics km ON k.id = km.keyword_id
                AND km.snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM keyword_metrics
                    WHERE keyword_id = k.id
                )
            WHERE k.is_active = 1 AND k.score >= ?
            {order_clause}
            LIMIT ?
        """
        return self._conn.execute(query, (min_score, limit)).fetchall()

    def get_keyword_with_metrics(self, keyword_id):
        query = """
            SELECT k.id, k.keyword, k.source, k.first_seen, k.category, k.score,
                   km.autocomplete_position, km.snapshot_date,
                   km.estimated_volume, km.competition_count,
                   km.avg_bsr_top_results, km.suggested_bid,
                   km.impressions, km.clicks, km.orders,
                   km.top10_avg_bsr, km.top10_asins, km.competition_score,
                   km.ku_ratio, km.median_reviews, km.marketplace
            FROM keywords k
            LEFT JOIN keyword_metrics km ON k.id = km.keyword_id
                AND km.snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM keyword_metrics
                    WHERE keyword_id = k.id
                )
            WHERE k.id = ?
        """
        return self._conn.execute(query, (keyword_id,)).fetchone()

    def get_ads_data_for_keyword(self, keyword_text):
        row = self._conn.execute(
            """
            SELECT SUM(impressions) as impressions,
                   SUM(clicks) as clicks,
                   SUM(orders) as orders,
                   SUM(spend) as spend,
                   SUM(sales) as sales
            FROM ads_search_terms
            WHERE LOWER(search_term) = LOWER(?)
            """,
            (keyword_text,),
        ).fetchone()
        if row and row['impressions'] is not None:
            return {
                'impressions': row['impressions'],
                'clicks': row['clicks'],
                'orders': row['orders'],
                'spend': row['spend'],
                'sales': row['sales'],
            }
        return None

    def get_ads_acos_for_keyword(self, keyword_text):
        row = self._conn.execute(
            """
            SELECT CASE WHEN SUM(sales) > 0
                THEN SUM(spend) / SUM(sales)
                ELSE NULL END as acos
            FROM ads_search_terms
            WHERE LOWER(search_term) = LOWER(?)
            """,
            (keyword_text,),
        ).fetchone()
        if row and row['acos'] is not None:
            return row['acos']
        return None

    def get_own_ranking_for_keyword(self, keyword_id):
        row = self._conn.execute(
            """
            SELECT MIN(kr.rank_position) as best_rank
            FROM keyword_rankings kr
            JOIN books b ON kr.book_id = b.id
            WHERE kr.keyword_id = ? AND b.is_own = 1
            """,
            (keyword_id,),
        ).fetchone()
        if row and row['best_rank'] is not None:
            return row['best_rank']
        return None

    def update_score(self, keyword_id, score):
        self._conn.execute(
            'UPDATE keywords SET score = ? WHERE id = ?',
            (score, keyword_id),
        )
        self._conn.commit()

    def get_all_keyword_ids(self, active_only=True):
        query = 'SELECT id FROM keywords'
        if active_only:
            query += ' WHERE is_active = 1'
        rows = self._conn.execute(query).fetchall()
        return [row['id'] for row in rows]

    def get_unscored_keyword_ids(self):
        query = 'SELECT id FROM keywords WHERE is_active = 1 AND score IS NULL'
        rows = self._conn.execute(query).fetchall()
        return [row['id'] for row in rows]

    def get_keyword_metrics_history(self, keyword_id, days=30):
        query = """
            SELECT * FROM keyword_metrics
            WHERE keyword_id = ?
              AND snapshot_date >= date('now', ?)
            ORDER BY snapshot_date ASC
        """
        return self._conn.execute(
            query, (keyword_id, f'-{days} days')
        ).fetchall()

    def add_competition_snapshot(self, keyword_id, marketplace='us',
                                 competition_count=None, avg_bsr_top10=None,
                                 median_reviews=None, ku_ratio=None,
                                 top_asins=None, raw_results=None):
        """Store competition probe results for a keyword.

        Args:
            keyword_id: ID of the keyword.
            marketplace: Marketplace code.
            competition_count: Total search results count.
            avg_bsr_top10: Average BSR of top 10 organic results.
            median_reviews: Median reviews of top 10 results.
            ku_ratio: Fraction of KU-eligible results.
            top_asins: JSON string of top ASIN list.
            raw_results: JSON string of full results.
        """
        today = date.today().isoformat()

        existing = self._conn.execute(
            'SELECT id FROM competition_snapshots '
            'WHERE keyword_id = ? AND snapshot_date = ? AND marketplace = ?',
            (keyword_id, today, marketplace),
        ).fetchone()

        if existing:
            self._conn.execute(
                'UPDATE competition_snapshots SET '
                'competition_count=?, avg_bsr_top10=?, median_reviews=?, '
                'ku_ratio=?, top_asins=?, raw_results=? WHERE id=?',
                (competition_count, avg_bsr_top10, median_reviews,
                 ku_ratio, top_asins, raw_results, existing['id']),
            )
        else:
            self._conn.execute(
                'INSERT INTO competition_snapshots '
                '(keyword_id, snapshot_date, marketplace, competition_count, '
                'avg_bsr_top10, median_reviews, ku_ratio, top_asins, raw_results) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (keyword_id, today, marketplace, competition_count,
                 avg_bsr_top10, median_reviews, ku_ratio, top_asins, raw_results),
            )
        self._conn.commit()

    def get_competition_history(self, keyword_id, marketplace='us', days=90):
        """Get competition snapshot history for a keyword.

        Args:
            keyword_id: ID of the keyword.
            marketplace: Marketplace code.
            days: Lookback window.

        Returns:
            List of sqlite3.Row objects ordered by date.
        """
        return self._conn.execute(
            'SELECT * FROM competition_snapshots '
            'WHERE keyword_id = ? AND marketplace = ? '
            "AND snapshot_date >= date('now', ?) "
            'ORDER BY snapshot_date ASC',
            (keyword_id, marketplace, f'-{days} days'),
        ).fetchall()


class BookRepository:
    """Data access for books and book_snapshots tables."""

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()

    def find_by_asin(self, asin):
        cursor = self._conn.execute(
            'SELECT * FROM books WHERE asin = ?',
            (asin.upper().strip(),),
        )
        return cursor.fetchone()

    def upsert_book(self, asin, title=None, author=None, is_own=False, notes=None):
        asin = asin.upper().strip()
        now = datetime.now().isoformat()

        existing = self.find_by_asin(asin)
        if existing:
            updates = []
            params = []
            if title is not None:
                updates.append('title = ?')
                params.append(title)
            if author is not None:
                updates.append('author = ?')
                params.append(author)
            if is_own:
                updates.append('is_own = ?')
                params.append(1)
            if notes is not None:
                updates.append('notes = ?')
                params.append(notes)
            if updates:
                params.append(existing['id'])
                self._conn.execute(
                    f'UPDATE books SET {", ".join(updates)} WHERE id = ?',
                    params,
                )
                self._conn.commit()
            return existing['id'], False

        cursor = self._conn.execute(
            'INSERT INTO books (asin, title, author, is_own, added_date, notes) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (asin, title, author, 1 if is_own else 0, now, notes),
        )
        self._conn.commit()
        return cursor.lastrowid, True

    def remove_book(self, asin):
        asin = asin.upper().strip()
        existing = self.find_by_asin(asin)
        if not existing:
            return False
        book_id = existing['id']
        self._conn.execute('DELETE FROM book_snapshots WHERE book_id = ?', (book_id,))
        self._conn.execute('DELETE FROM bsr_category_history WHERE book_id = ?', (book_id,))
        self._conn.execute('DELETE FROM books WHERE id = ?', (book_id,))
        self._conn.commit()
        return True

    def get_all_books(self):
        return self._conn.execute(
            'SELECT * FROM books ORDER BY is_own DESC, title ASC'
        ).fetchall()

    def get_book_count(self):
        row = self._conn.execute('SELECT COUNT(*) as cnt FROM books').fetchone()
        return row['cnt']

    def add_snapshot(self, book_id, bsr_overall=None, bsr_category=None,
                     price_kindle=None, price_paperback=None, price_hardcover=None,
                     review_count=None, avg_rating=None, page_count=None,
                     estimated_daily_sales=None, estimated_monthly_revenue=None,
                     ku_eligible=None, series_name=None, also_bought_asins=None,
                     formats_available=None, language=None, publisher=None,
                     review_histogram=None):
        """Add a snapshot for a tracked book.

        Accepts all original fields plus new v2 fields.
        If a snapshot already exists for today, it is updated.
        """
        today = date.today().isoformat()

        existing = self._conn.execute(
            'SELECT id FROM book_snapshots WHERE book_id = ? AND snapshot_date = ?',
            (book_id, today),
        ).fetchone()

        if existing:
            self._conn.execute(
                'UPDATE book_snapshots SET '
                'bsr_overall=?, bsr_category=?, '
                'price_kindle=?, price_paperback=?, price_hardcover=?, '
                'review_count=?, avg_rating=?, page_count=?, '
                'estimated_daily_sales=?, estimated_monthly_revenue=?, '
                'ku_eligible=?, series_name=?, also_bought_asins=?, '
                'formats_available=?, language=?, publisher=?, review_histogram=? '
                'WHERE id=?',
                (
                    bsr_overall, bsr_category,
                    price_kindle, price_paperback, price_hardcover,
                    review_count, avg_rating, page_count,
                    estimated_daily_sales, estimated_monthly_revenue,
                    1 if ku_eligible else 0, series_name, also_bought_asins,
                    formats_available, language, publisher, review_histogram,
                    existing['id'],
                ),
            )
            self._conn.commit()
            return existing['id']

        cursor = self._conn.execute(
            'INSERT INTO book_snapshots '
            '(book_id, snapshot_date, bsr_overall, bsr_category, '
            'price_kindle, price_paperback, price_hardcover, '
            'review_count, avg_rating, page_count, '
            'estimated_daily_sales, estimated_monthly_revenue, '
            'ku_eligible, series_name, also_bought_asins, '
            'formats_available, language, publisher, review_histogram) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                book_id, today, bsr_overall, bsr_category,
                price_kindle, price_paperback, price_hardcover,
                review_count, avg_rating, page_count,
                estimated_daily_sales, estimated_monthly_revenue,
                1 if ku_eligible else 0, series_name, also_bought_asins,
                formats_available, language, publisher, review_histogram,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def add_bsr_category_history(self, book_id, category_name, rank, snapshot_date=None):
        """Store per-category BSR snapshot for multi-category BSR tracking.

        Args:
            book_id: ID of the book.
            category_name: The Amazon category name.
            rank: The category BSR rank.
            snapshot_date: Date string. Defaults to today.
        """
        if snapshot_date is None:
            snapshot_date = date.today().isoformat()

        existing = self._conn.execute(
            'SELECT id FROM bsr_category_history '
            'WHERE book_id=? AND snapshot_date=? AND category_name=?',
            (book_id, snapshot_date, category_name),
        ).fetchone()

        if existing:
            self._conn.execute(
                'UPDATE bsr_category_history SET rank=? WHERE id=?',
                (rank, existing['id']),
            )
        else:
            self._conn.execute(
                'INSERT INTO bsr_category_history '
                '(book_id, snapshot_date, category_name, rank) VALUES (?, ?, ?, ?)',
                (book_id, snapshot_date, category_name, rank),
            )
        self._conn.commit()

    def get_bsr_category_history(self, book_id, category_name=None, days=90):
        """Get BSR history for a book across all or a specific category.

        Args:
            book_id: ID of the book.
            category_name: Optional category filter.
            days: Lookback window in days.

        Returns:
            List of sqlite3.Row objects ordered by date.
        """
        if category_name:
            return self._conn.execute(
                'SELECT * FROM bsr_category_history '
                'WHERE book_id=? AND category_name=? '
                "AND snapshot_date >= date('now', ?) "
                'ORDER BY snapshot_date ASC',
                (book_id, category_name, f'-{days} days'),
            ).fetchall()
        return self._conn.execute(
            'SELECT * FROM bsr_category_history '
            'WHERE book_id=? '
            "AND snapshot_date >= date('now', ?) "
            'ORDER BY snapshot_date ASC, category_name ASC',
            (book_id, f'-{days} days'),
        ).fetchall()

    def get_latest_snapshot(self, book_id):
        return self._conn.execute(
            'SELECT * FROM book_snapshots WHERE book_id = ? '
            'ORDER BY snapshot_date DESC LIMIT 1',
            (book_id,),
        ).fetchone()

    def get_previous_snapshot(self, book_id):
        return self._conn.execute(
            'SELECT * FROM book_snapshots WHERE book_id = ? '
            'ORDER BY snapshot_date DESC LIMIT 1 OFFSET 1',
            (book_id,),
        ).fetchone()

    def get_all_snapshots(self, book_id, days=90):
        """Get all snapshots for a book within a date window.

        Args:
            book_id: ID of the book.
            days: Lookback window.

        Returns:
            List of sqlite3.Row objects ordered by date.
        """
        return self._conn.execute(
            'SELECT * FROM book_snapshots '
            'WHERE book_id=? '
            "AND snapshot_date >= date('now', ?) "
            'ORDER BY snapshot_date ASC',
            (book_id, f'-{days} days'),
        ).fetchall()

    def get_books_with_latest_snapshot(self):
        query = """
            SELECT b.*, bs.bsr_overall, bs.bsr_category,
                   bs.price_kindle, bs.price_paperback, bs.price_hardcover,
                   bs.review_count, bs.avg_rating, bs.page_count,
                   bs.estimated_daily_sales, bs.estimated_monthly_revenue,
                   bs.ku_eligible, bs.series_name, bs.formats_available,
                   bs.language, bs.publisher,
                   bs.snapshot_date as last_snapshot_date
            FROM books b
            LEFT JOIN book_snapshots bs ON b.id = bs.book_id
                AND bs.snapshot_date = (
                    SELECT MAX(snapshot_date)
                    FROM book_snapshots
                    WHERE book_id = b.id
                )
            ORDER BY b.is_own DESC, bs.bsr_overall ASC
        """
        return self._conn.execute(query).fetchall()


class AdsRepository:
    """Data access for ads_search_terms table."""

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()

    def add_search_term(self, campaign_name=None, ad_group=None,
                        search_term=None, keyword_match_type=None,
                        impressions=None, clicks=None, ctr=None,
                        spend=None, sales=None, acos=None, orders=None,
                        report_date=None, imported_at=None):
        cursor = self._conn.execute(
            'INSERT INTO ads_search_terms '
            '(campaign_name, ad_group, search_term, keyword_match_type, '
            'impressions, clicks, ctr, spend, sales, acos, orders, '
            'report_date, imported_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (
                campaign_name, ad_group, search_term, keyword_match_type,
                impressions, clicks, ctr, spend, sales, acos, orders,
                report_date, imported_at,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_all_search_terms(self, campaign_filter=None):
        if campaign_filter:
            return self._conn.execute(
                'SELECT * FROM ads_search_terms '
                'WHERE campaign_name LIKE ? '
                'ORDER BY orders DESC, impressions DESC',
                (f'%{campaign_filter}%',),
            ).fetchall()
        return self._conn.execute(
            'SELECT * FROM ads_search_terms '
            'ORDER BY orders DESC, impressions DESC'
        ).fetchall()

    def get_aggregated_search_terms(self):
        return self._conn.execute(
            'SELECT search_term, '
            '  SUM(impressions) as total_impressions, '
            '  SUM(clicks) as total_clicks, '
            '  SUM(spend) as total_spend, '
            '  SUM(sales) as total_sales, '
            '  SUM(orders) as total_orders, '
            '  CASE WHEN SUM(sales) > 0 '
            '    THEN SUM(spend) / SUM(sales) '
            '    ELSE NULL END as avg_acos, '
            '  CASE WHEN SUM(impressions) > 0 '
            '    THEN CAST(SUM(clicks) AS REAL) / SUM(impressions) '
            '    ELSE NULL END as avg_ctr '
            'FROM ads_search_terms '
            'GROUP BY search_term '
            'ORDER BY total_orders DESC, total_impressions DESC'
        ).fetchall()

    def get_search_term_count(self):
        row = self._conn.execute(
            'SELECT COUNT(*) as cnt FROM ads_search_terms'
        ).fetchone()
        return row['cnt']

    def get_opportunity_keywords(self):
        return self._conn.execute(
            'SELECT search_term, '
            '  SUM(impressions) as total_impressions, '
            '  SUM(clicks) as total_clicks, '
            '  SUM(spend) as total_spend, '
            '  SUM(orders) as total_orders '
            'FROM ads_search_terms '
            'GROUP BY search_term '
            'HAVING SUM(impressions) > 0 AND (SUM(orders) IS NULL OR SUM(orders) = 0) '
            'ORDER BY total_impressions DESC'
        ).fetchall()


class KeywordRankingRepository:
    """Data access for keyword_rankings table."""

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()

    def add_ranking(self, keyword_id, book_id, position, source, snapshot_date=None):
        if snapshot_date is None:
            snapshot_date = date.today().isoformat()

        existing = self._conn.execute(
            'SELECT id FROM keyword_rankings '
            'WHERE keyword_id = ? AND book_id = ? AND snapshot_date = ?',
            (keyword_id, book_id, snapshot_date),
        ).fetchone()

        if existing:
            self._conn.execute(
                'UPDATE keyword_rankings SET rank_position = ?, source = ? WHERE id = ?',
                (position, source, existing['id']),
            )
            self._conn.commit()
            return existing['id']

        cursor = self._conn.execute(
            'INSERT INTO keyword_rankings '
            '(keyword_id, book_id, snapshot_date, rank_position, source) '
            'VALUES (?, ?, ?, ?, ?)',
            (keyword_id, book_id, snapshot_date, position, source),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_rankings_for_book(self, book_id, snapshot_date=None):
        if snapshot_date:
            query = """
                SELECT kr.*, k.keyword
                FROM keyword_rankings kr
                JOIN keywords k ON kr.keyword_id = k.id
                WHERE kr.book_id = ? AND kr.snapshot_date = ?
                ORDER BY kr.rank_position ASC
            """
            return self._conn.execute(query, (book_id, snapshot_date)).fetchall()

        query = """
            SELECT kr.*, k.keyword
            FROM keyword_rankings kr
            JOIN keywords k ON kr.keyword_id = k.id
            WHERE kr.book_id = ?
              AND kr.snapshot_date = (
                  SELECT MAX(snapshot_date) FROM keyword_rankings
                  WHERE book_id = ?
              )
            ORDER BY kr.rank_position ASC
        """
        return self._conn.execute(query, (book_id, book_id)).fetchall()

    def get_rankings_for_keyword(self, keyword_id):
        query = """
            SELECT kr.*, b.asin, b.title, b.is_own
            FROM keyword_rankings kr
            JOIN books b ON kr.book_id = b.id
            WHERE kr.keyword_id = ?
            ORDER BY kr.rank_position ASC
        """
        return self._conn.execute(query, (keyword_id,)).fetchall()

    def get_gaps(self, own_book_ids, competitor_book_ids):
        if not own_book_ids or not competitor_book_ids:
            return []

        own_placeholders = ','.join('?' * len(own_book_ids))
        comp_placeholders = ','.join('?' * len(competitor_book_ids))

        query = f"""
            SELECT k.id as keyword_id, k.keyword, k.score,
                   cr.rank_position as competitor_position,
                   b.title as competitor_title, b.asin as competitor_asin,
                   cr.snapshot_date
            FROM keyword_rankings cr
            JOIN keywords k ON cr.keyword_id = k.id
            JOIN books b ON cr.book_id = b.id
            WHERE cr.book_id IN ({comp_placeholders})
              AND cr.keyword_id NOT IN (
                  SELECT keyword_id FROM keyword_rankings
                  WHERE book_id IN ({own_placeholders})
              )
            ORDER BY cr.rank_position ASC
        """
        params = list(competitor_book_ids) + list(own_book_ids)
        return self._conn.execute(query, params).fetchall()

    def get_ranking_count_for_book(self, book_id):
        row = self._conn.execute(
            'SELECT COUNT(*) as cnt FROM keyword_rankings WHERE book_id = ?',
            (book_id,),
        ).fetchone()
        return row['cnt']


class CategoryRepository:
    """Data access for categories table."""

    def __init__(self, conn=None):
        self._conn = conn or get_connection()
        self._owns_conn = conn is None

    def close(self):
        if self._owns_conn:
            self._conn.close()

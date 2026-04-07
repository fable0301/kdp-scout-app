"""Competitor analysis engine.

Coordinates book tracking, BSR snapshots, and competitor comparisons.
Serves as the main entry point for the `track` CLI command group.

New in this version:
- get_snapshots(): exposes BSR snapshot history for the GUI
- _store_snapshot(): stores all new v2 fields (KU, hardcover, also_bought,
  series, formats, language, publisher, review_histogram)
- per-category BSR stored in bsr_category_history table
- multi-marketplace revenue estimate (compare_marketplaces)
- total_monthly_revenue: direct sales + KU earnings
- also_bought graph: surface "also bought" clusters
"""

import json
import logging

from kdp_scout.db import BookRepository, init_db
from kdp_scout.collectors.product_scraper import ProductScraper, CaptchaDetected
from kdp_scout.collectors.bsr_model import (
    estimate_daily_sales,
    estimate_monthly_revenue,
    estimate_total_monthly_revenue,
    compare_marketplaces,
    sales_velocity_label,
)

logger = logging.getLogger(__name__)


class CompetitorEngine:
    """Manages book tracking, snapshots, and competitor comparisons."""

    def __init__(self):
        init_db()
        self._repo = BookRepository()
        self._scraper = ProductScraper()

    def close(self):
        self._repo.close()

    # ── Public API ────────────────────────────────────────────────────

    def add_book(self, asin, name=None, is_own=False):
        """Add a book to tracking. Scrapes initial data and stores in DB.

        Args:
            asin: Amazon ASIN.
            name: Optional display name override.
            is_own: Whether this is the user's own book.

        Returns:
            Dict with book data and snapshot info, or None on scrape failure.

        Raises:
            CaptchaDetected: If Amazon serves a CAPTCHA page.
        """
        asin = asin.upper().strip()
        logger.info(f'Adding book to tracking: {asin}')

        try:
            scraped = self._scraper.scrape_product(asin)
        except CaptchaDetected:
            raise
        except Exception as e:
            logger.error(f'Failed to scrape ASIN {asin}: {e}')
            scraped = None

        title = name
        author = None
        if scraped:
            title = name or scraped.get('title')
            author = scraped.get('author')

        book_id, is_new = self._repo.upsert_book(
            asin=asin, title=title, author=author, is_own=is_own,
        )

        result = {
            'book_id': book_id,
            'asin': asin,
            'title': title,
            'author': author,
            'is_own': is_own,
            'is_new': is_new,
            'scraped': scraped,
            'snapshot': None,
        }

        if scraped:
            snapshot = self._store_snapshot(book_id, scraped)
            result['snapshot'] = snapshot

        return result

    def remove_book(self, asin):
        """Remove a book from tracking."""
        asin = asin.upper().strip()
        removed = self._repo.remove_book(asin)
        if removed:
            logger.info(f'Removed book from tracking: {asin}')
        else:
            logger.warning(f'Book not found for removal: {asin}')
        return removed

    def list_books(self):
        """List all tracked books with latest snapshot data."""
        return self._repo.get_books_with_latest_snapshot()

    def take_snapshot(self, asin=None):
        """Take BSR/price/review snapshot of tracked books.

        If asin is None, snapshots ALL tracked books.

        Args:
            asin: Optional ASIN to snapshot. None = all tracked books.

        Returns:
            List of dicts with snapshot results for each book.
        """
        if asin:
            books = [self._repo.find_by_asin(asin.upper().strip())]
            if books[0] is None:
                logger.warning(f'Book not found: {asin}')
                return []
        else:
            books = self._repo.get_all_books()

        results = []
        for book in books:
            book_asin = book['asin']
            book_id = book['id']
            prev_snapshot = self._repo.get_latest_snapshot(book_id)

            try:
                scraped = self._scraper.scrape_product(book_asin)
                if scraped is None:
                    results.append({
                        'asin': book_asin,
                        'title': book['title'],
                        'success': False,
                        'error': 'Scrape returned no data',
                    })
                    continue

                if scraped.get('title') and not book['title']:
                    self._repo.upsert_book(
                        asin=book_asin,
                        title=scraped['title'],
                        author=scraped.get('author'),
                    )

                snapshot = self._store_snapshot(book_id, scraped)
                changes = {}
                if prev_snapshot:
                    changes = self._calculate_changes(prev_snapshot, snapshot)

                results.append({
                    'asin': book_asin,
                    'title': book['title'] or scraped.get('title', 'Unknown'),
                    'success': True,
                    'snapshot': snapshot,
                    'changes': changes,
                })

            except CaptchaDetected as e:
                logger.warning(f'CAPTCHA detected while snapshotting {book_asin}')
                results.append({
                    'asin': book_asin,
                    'title': book['title'],
                    'success': False,
                    'error': str(e),
                })
            except Exception as e:
                logger.error(f'Error snapshotting {book_asin}: {e}')
                results.append({
                    'asin': book_asin,
                    'title': book['title'],
                    'success': False,
                    'error': str(e),
                })

        return results

    def compare_books(self, asins=None):
        """Compare metrics across tracked books.

        Args:
            asins: Optional list of ASINs. None = all tracked books.

        Returns:
            List of sqlite3.Row objects with book and snapshot data.
        """
        all_books = self._repo.get_books_with_latest_snapshot()
        if asins:
            asin_set = {a.upper().strip() for a in asins}
            return [b for b in all_books if b['asin'] in asin_set]
        return all_books

    def get_snapshots(self, asin, days=90):
        """Get BSR snapshot history for a book.

        Used by the GUI competitors page to draw the BSR trend chart.

        Args:
            asin: Amazon ASIN.
            days: How many days of history to return.

        Returns:
            List of sqlite3.Row objects ordered by date ascending.
            Each row has: snapshot_date, bsr_overall, price_kindle,
            price_paperback, price_hardcover, review_count, avg_rating,
            estimated_daily_sales, estimated_monthly_revenue, ku_eligible.
            Returns empty list if the book is not tracked.
        """
        book = self._repo.find_by_asin(asin.upper().strip())
        if not book:
            return []
        return self._repo.get_all_snapshots(book['id'], days=days)

    def get_category_bsr_history(self, asin, category_name=None, days=90):
        """Get per-category BSR history for a book.

        Args:
            asin: Amazon ASIN.
            category_name: Optional specific category. None = all categories.
            days: Lookback window.

        Returns:
            List of sqlite3.Row objects ordered by date / category.
        """
        book = self._repo.find_by_asin(asin.upper().strip())
        if not book:
            return []
        return self._repo.get_bsr_category_history(
            book['id'], category_name=category_name, days=days
        )

    def get_also_bought(self, asin):
        """Get the most recent also-bought ASIN list for a book.

        Returns the also_bought_asins field from the latest snapshot,
        parsed from JSON into a Python list.

        Args:
            asin: Amazon ASIN.

        Returns:
            List of ASIN strings, or empty list.
        """
        book = self._repo.find_by_asin(asin.upper().strip())
        if not book:
            return []
        snap = self._repo.get_latest_snapshot(book['id'])
        if not snap or not snap['also_bought_asins']:
            return []
        try:
            return json.loads(snap['also_bought_asins'])
        except (json.JSONDecodeError, TypeError):
            return []

    def estimate_revenue_all_marketplaces(self, asin):
        """Estimate revenue across all available marketplaces for a book.

        Uses the latest snapshot BSR and price. Requires the book to have
        been scraped at least once.

        Args:
            asin: Amazon ASIN.

        Returns:
            List of marketplace revenue dicts (sorted by revenue), or [].
        """
        book = self._repo.find_by_asin(asin.upper().strip())
        if not book:
            return []
        snap = self._repo.get_latest_snapshot(book['id'])
        if not snap:
            return []

        # US BSR is the baseline — we can't know other marketplace BSRs without
        # scraping them, but we can estimate relative potential from US rank.
        us_bsr = snap['bsr_overall']
        if not us_bsr:
            return []

        price = snap['price_kindle'] or snap['price_paperback'] or 4.99

        # Build hypothetical bsr_map: scale US BSR by market size ratios
        MARKET_SIZE_RATIOS = {
            'us': 1.00, 'uk': 0.25, 'de': 0.20, 'fr': 0.12,
            'ca': 0.10, 'au': 0.08, 'jp': 0.08, 'es': 0.05, 'it': 0.05,
        }
        bsr_map = {mp: int(us_bsr / ratio)
                   for mp, ratio in MARKET_SIZE_RATIOS.items()}

        return compare_marketplaces(bsr_map, price=price, ku_eligible=bool(snap['ku_eligible']))

    def full_revenue_breakdown(self, asin, genre='default'):
        """Full revenue breakdown: sales + KU for US marketplace.

        Args:
            asin: Amazon ASIN.
            genre: Genre key for KU borrow fraction.

        Returns:
            Dict with keys: sales_revenue, ku_revenue, total, daily_sales,
            monthly_borrows, kenp_reads, velocity. Or None.
        """
        book = self._repo.find_by_asin(asin.upper().strip())
        if not book:
            return None
        snap = self._repo.get_latest_snapshot(book['id'])
        if not snap:
            return None

        bsr = snap['bsr_overall']
        price = snap['price_kindle'] or snap['price_paperback'] or 4.99
        ku = bool(snap['ku_eligible'])

        result = estimate_total_monthly_revenue(
            bsr, price, ku_eligible=ku, genre=genre
        )
        result['velocity'] = sales_velocity_label(result.get('daily_sales', 0))
        return result

    # ── Internal helpers ─────────────────────────────────────────────

    def _store_snapshot(self, book_id, scraped):
        """Store a snapshot from scraped data (all v2 fields).

        Args:
            book_id: Database ID of the book.
            scraped: Dict from ProductScraper.scrape_product().

        Returns:
            Dict with the stored snapshot data.
        """
        bsr = scraped.get('bsr_overall')
        price_kindle = scraped.get('price_kindle')
        price_paperback = scraped.get('price_paperback')
        price_hardcover = scraped.get('price_hardcover')
        ku_eligible = scraped.get('ku_eligible', False)

        # Estimate daily sales and revenue
        daily_sales = None
        monthly_revenue = None
        if bsr:
            daily_sales = estimate_daily_sales(bsr, 'us_kindle')
            price_for_revenue = price_kindle or price_paperback or price_hardcover
            if price_for_revenue:
                rev = estimate_total_monthly_revenue(
                    bsr, price_for_revenue,
                    ku_eligible=ku_eligible,
                )
                monthly_revenue = rev['total']

        # Serialize categories to JSON
        bsr_category_json = None
        bsr_categories = scraped.get('bsr_categories', {})
        if bsr_categories:
            bsr_category_json = json.dumps(bsr_categories)

        # Serialize lists to JSON for storage
        also_bought_json = None
        if scraped.get('also_bought'):
            also_bought_json = json.dumps(scraped['also_bought'][:20])

        formats_json = None
        if scraped.get('formats'):
            formats_json = json.dumps(scraped['formats'])

        review_histogram_json = None
        if scraped.get('review_histogram'):
            review_histogram_json = json.dumps(scraped['review_histogram'])

        snapshot_id = self._repo.add_snapshot(
            book_id=book_id,
            bsr_overall=bsr,
            bsr_category=bsr_category_json,
            price_kindle=price_kindle,
            price_paperback=price_paperback,
            price_hardcover=price_hardcover,
            review_count=scraped.get('review_count'),
            avg_rating=scraped.get('avg_rating'),
            page_count=scraped.get('page_count'),
            estimated_daily_sales=daily_sales,
            estimated_monthly_revenue=monthly_revenue,
            ku_eligible=ku_eligible,
            series_name=scraped.get('series_name'),
            also_bought_asins=also_bought_json,
            formats_available=formats_json,
            language=scraped.get('language'),
            publisher=scraped.get('publisher'),
            review_histogram=review_histogram_json,
        )

        # Store per-category BSR in bsr_category_history
        if bsr_categories:
            for cat_name, rank in bsr_categories.items():
                if isinstance(rank, int) and rank > 0:
                    try:
                        self._repo.add_bsr_category_history(
                            book_id=book_id,
                            category_name=cat_name,
                            rank=rank,
                        )
                    except Exception:
                        pass  # non-fatal

        return {
            'snapshot_id': snapshot_id,
            'bsr_overall': bsr,
            'bsr_categories': bsr_categories,
            'price_kindle': price_kindle,
            'price_paperback': price_paperback,
            'price_hardcover': price_hardcover,
            'review_count': scraped.get('review_count'),
            'avg_rating': scraped.get('avg_rating'),
            'page_count': scraped.get('page_count'),
            'estimated_daily_sales': daily_sales,
            'estimated_monthly_revenue': monthly_revenue,
            'ku_eligible': ku_eligible,
            'series_name': scraped.get('series_name'),
            'also_bought': scraped.get('also_bought', [])[:5],
            'formats': scraped.get('formats', {}),
            'language': scraped.get('language'),
            'publisher': scraped.get('publisher'),
        }

    def _calculate_changes(self, prev, current):
        """Calculate changes between two snapshots.

        Args:
            prev: Previous snapshot (sqlite3.Row).
            current: Current snapshot (dict).

        Returns:
            Dict of label -> {'old', 'new', 'direction'}.
        """
        changes = {}

        comparisons = [
            ('bsr_overall', 'BSR', True),
            ('review_count', 'Reviews', False),
            ('avg_rating', 'Rating', False),
            ('price_kindle', 'Kindle Price', None),
            ('price_paperback', 'Paperback Price', None),
        ]

        for field, label, lower_is_better in comparisons:
            old_val = prev[field] if prev[field] is not None else None
            new_val = current.get(field)

            if old_val is not None and new_val is not None and old_val != new_val:
                if lower_is_better is None:
                    direction = 'changed'
                elif new_val < old_val:
                    direction = 'improved' if lower_is_better else 'declined'
                elif new_val > old_val:
                    direction = 'declined' if lower_is_better else 'improved'
                else:
                    direction = 'unchanged'

                changes[label] = {
                    'old': old_val,
                    'new': new_val,
                    'direction': direction,
                }

        return changes

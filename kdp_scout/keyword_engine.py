"""Keyword mining, scoring, reverse ASIN, and competition analysis engine.

Coordinates autocomplete mining, deduplication, database storage,
keyword scoring based on multiple signals, and reverse ASIN lookups
via search result probing or DataForSEO API.

New in this version:
- mine_keywords_multi_marketplace(): mine same seed on several marketplaces
- CompetitionProber: probe Amazon search results for real competition data
  per keyword (top10 avg BSR, KU ratio, median reviews, competition count)
- KeywordScorer: new signals (ku_ratio, median_reviews, competition_score)
  weight added; updated DEFAULT_WEIGHTS
"""

import logging
import math
import re

import time
from datetime import datetime, date

from bs4 import BeautifulSoup

from kdp_scout.db import (
    KeywordRepository, BookRepository, KeywordRankingRepository, init_db,
)
from kdp_scout.collectors.autocomplete import mine_autocomplete
try:
    from kdp_scout.collectors.autocomplete import mine_autocomplete_async, mine_autocomplete_multi_marketplace_async
    _HAS_ASYNC = True
except ImportError:
    _HAS_ASYNC = False
from kdp_scout.http_client import fetch, get_browser_headers
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config

logger = logging.getLogger(__name__)

# ── Scoring weights ───────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    'autocomplete':       0.18,
    'competition':        0.12,
    'bsr_demand':         0.10,
    'ads_impressions':    0.08,
    'ads_orders':         0.12,
    'ads_profitability':  0.08,
    'search_volume':      0.05,
    'commercial_value':   0.05,
    'click_through_rate': 0.05,
    'own_ranking':        0.05,
    # New signals
    'ku_ratio':           0.06,   # KU saturation (lower = better opportunity)
    'median_reviews':     0.06,   # Competition barrier (lower = easier entry)
}


# ── Normalizers ───────────────────────────────────────────────────────────────

def normalize_autocomplete(position):
    if position is None or position <= 0:
        return 0.0
    return max(0.0, (11 - position) / 10)


def normalize_competition(count):
    if count is None or count < 0:
        return 0.0
    return 1.0 / (1.0 + count / 50000.0)


def normalize_bsr(bsr):
    if bsr is None or bsr <= 0:
        return 0.0
    return max(0.0, 1.0 - math.log10(bsr) / 6.0)


def normalize_impressions(impressions):
    if impressions is None or impressions <= 0:
        return 0.0
    return min(1.0, math.log10(max(1, impressions)) / 5.0)


def normalize_orders(orders):
    if orders is None or orders <= 0:
        return 0.0
    return min(1.0, math.log10(max(1, orders)) / 3.0)


def normalize_ctr(clicks, impressions):
    if (clicks is None or impressions is None
            or clicks < 0 or impressions <= 0):
        return 0.0
    ctr = clicks / impressions
    return min(1.0, ctr / 0.05)


def normalize_acos(acos):
    if acos is None:
        return 0.0
    acos_pct = acos * 100.0
    return max(0.0, 1.0 - acos_pct / 100.0)


def normalize_search_volume(volume):
    if volume is None or volume <= 0:
        return 0.0
    return min(1.0, math.log10(max(1, volume)) / 5.0)


def normalize_suggested_bid(bid):
    if bid is None or bid <= 0:
        return 0.0
    return min(1.0, bid / 3.0)


def normalize_own_ranking(rank):
    if rank is None or rank <= 0:
        return 0.0
    return max(0.0, (50.0 - rank) / 49.0)


def normalize_ku_ratio(ku_ratio):
    """Normalize KU ratio to opportunity score.

    A moderate KU ratio (0.40-0.60) is ideal: proven KU reader base
    but not completely saturated. Very high ratio = commodity trap.
    Very low ratio = buyers market (harder to monetize via KU).

    Args:
        ku_ratio: Fraction 0.0-1.0 of top results that are KU-eligible.
                  None = unknown.

    Returns:
        Float 0-1 (higher = more opportunity).
    """
    if ku_ratio is None:
        return 0.5  # Neutral if unknown
    # Sweet spot around 0.40-0.60
    # Below 0.20 or above 0.80 = less opportunity
    return 1.0 - abs(ku_ratio - 0.5) * 2.0


def normalize_median_reviews(median_reviews):
    """Normalize median reviews to opportunity score.

    Fewer reviews in top results = lower barrier to entry.
    0-50 reviews = excellent, 50-200 = good, 200-500 = ok, 500+ = hard.

    Args:
        median_reviews: Median review count of top 10 results.

    Returns:
        Float 0-1 (higher = lower barrier = better opportunity).
    """
    if median_reviews is None or median_reviews <= 0:
        return 0.5  # Neutral if unknown
    # Exponential decay: 0 reviews -> 1.0, 500 reviews -> ~0.1
    return max(0.0, 1.0 / (1.0 + median_reviews / 100.0))


# ── Core mining ───────────────────────────────────────────────────────────────

def mine_keywords(seed, depth=1, department='kindle', progress_callback=None,
                  marketplace='us'):
    """Mine keywords from autocomplete and store results.

    Args:
        seed: Seed keyword.
        depth: Mining depth (1 = seed + a-z, 2 = recursive).
        department: Amazon department ('kindle', 'books', 'all').
        progress_callback: Optional callable(completed, total).
        marketplace: 2-letter marketplace code (default 'us').

    Returns:
        Dict with new_count, existing_count, total_mined, keywords, seed,
        depth, department, marketplace.
    """
    init_db()
    logger.info(
        f'Mining keywords: seed="{seed}", depth={depth}, '
        f'department={department}, marketplace={marketplace}'
    )

    raw_results = mine_autocomplete(
        seed,
        department=department,
        depth=depth,
        progress_callback=progress_callback,
        marketplace=marketplace,
    )

    repo = KeywordRepository()
    try:
        new_count = 0
        existing_count = 0
        keywords = []

        for keyword, position in raw_results:
            keyword_id, is_new = repo.upsert_keyword(
                keyword, source='autocomplete', category=seed,
            )
            repo.add_metric(
                keyword_id,
                autocomplete_position=position,
                marketplace=marketplace,
            )

            if is_new:
                new_count += 1
            else:
                existing_count += 1

            keywords.append((keyword, position, is_new))

        logger.info(
            f'Mining complete: {new_count} new, {existing_count} existing, '
            f'{len(keywords)} total'
        )

        return {
            'new_count': new_count,
            'existing_count': existing_count,
            'total_mined': len(keywords),
            'keywords': keywords,
            'seed': seed,
            'depth': depth,
            'department': department,
            'marketplace': marketplace,
        }

    finally:
        repo.close()


def mine_keywords_multi_marketplace(seed, depth=1, department='kindle',
                                    marketplaces=None, progress_callback=None):
    """Mine same seed across multiple marketplaces.

    Mines autocomplete on each marketplace, deduplicates globally,
    and returns a merged result with per-marketplace position data.

    Args:
        seed: Seed keyword.
        depth: Mining depth.
        department: Amazon department.
        marketplaces: List of 2-letter codes. Default: ['us','uk','de','ca'].
        progress_callback: Optional callable(completed, total, marketplace).

    Returns:
        Dict with combined_keywords (dict keyword -> {marketplace: position}),
        new_count, existing_count, per_marketplace results.
    """
    if marketplaces is None:
        marketplaces = ['us', 'uk', 'de', 'ca']

    init_db()
    combined = {}   # keyword -> {marketplace: position}
    per_mp = {}

    total_steps = len(marketplaces)
    for i, mp in enumerate(marketplaces):
        if progress_callback:
            progress_callback(i, total_steps, mp)

        # Build a sub-progress callback so cancellation checks propagate
        # into individual mine_autocomplete calls (which can be slow).
        def _sub_progress(current, total, message="", _mp=mp, _i=i):
            if progress_callback:
                # Report marketplace-level progress (fraction within current mp)
                frac = current / max(total, 1)
                overall = _i + frac
                progress_callback(overall, total_steps, _mp)

        try:
            raw = mine_autocomplete(
                seed, department=department, depth=depth,
                marketplace=mp,
                progress_callback=_sub_progress,
            )
            per_mp[mp] = raw
            for kw, pos in raw:
                if kw not in combined:
                    combined[kw] = {}
                combined[kw][mp] = pos
        except InterruptedError:
            logger.info(f'Mining cancelled during {mp}')
            raise
        except Exception as e:
            logger.warning(f'Failed to mine {mp} for "{seed}": {e}')
            per_mp[mp] = []

    if progress_callback:
        progress_callback(total_steps, total_steps, 'done')

    # Store all in DB
    repo = KeywordRepository()
    new_count = 0
    existing_count = 0
    try:
        for kw, mp_positions in combined.items():
            keyword_id, is_new = repo.upsert_keyword(kw, source='autocomplete', category=seed)
            # Use US position if available, otherwise first available
            pos = mp_positions.get('us') or next(iter(mp_positions.values()), None)
            repo.add_metric(keyword_id, autocomplete_position=pos, marketplace='multi')
            if is_new:
                new_count += 1
            else:
                existing_count += 1
    finally:
        repo.close()

    return {
        'combined_keywords': combined,
        'new_count': new_count,
        'existing_count': existing_count,
        'total_unique': len(combined),
        'per_marketplace': per_mp,
        'marketplaces': marketplaces,
        'seed': seed,
    }


# ── Fast (async) mining ───────────────────────────────────────────────────────


def mine_keywords_fast(seed, depth=1, department='kindle', progress_callback=None,
                       marketplace='us'):
    """Fast async version of mine_keywords. Must be called from a non-async context.

    Falls back to sync mine_keywords if aiohttp is not available.

    Args:
        seed: Seed keyword.
        depth: Mining depth (1 = seed + a-z, 2 = recursive).
        department: Amazon department ('kindle', 'books', 'all').
        progress_callback: Optional callable(completed, total).
        marketplace: 2-letter marketplace code (default 'us').

    Returns:
        Dict with new_count, existing_count, total_mined, keywords, seed,
        depth, department, marketplace.
    """
    import asyncio

    if not _HAS_ASYNC:
        return mine_keywords(seed, depth, department, progress_callback, marketplace)

    init_db()
    logger.info(
        f'Fast mining: seed="{seed}", depth={depth}, '
        f'department={department}, marketplace={marketplace}'
    )

    raw_results = asyncio.run(
        mine_autocomplete_async(
            seed, department=department, depth=depth,
            progress_callback=progress_callback, marketplace=marketplace,
        )
    )

    repo = KeywordRepository()
    try:
        new_count = 0
        existing_count = 0
        keywords = []
        for keyword, position in raw_results:
            keyword_id, is_new = repo.upsert_keyword(
                keyword, source='autocomplete', category=seed,
            )
            repo.add_metric(
                keyword_id,
                autocomplete_position=position,
                marketplace=marketplace,
            )
            if is_new:
                new_count += 1
            else:
                existing_count += 1
            keywords.append((keyword, position, is_new))

        logger.info(
            f'Fast mining complete: {new_count} new, {existing_count} existing, '
            f'{len(keywords)} total'
        )

        return {
            'new_count': new_count,
            'existing_count': existing_count,
            'total_mined': len(keywords),
            'keywords': keywords,
            'seed': seed,
            'depth': depth,
            'department': department,
            'marketplace': marketplace,
        }
    finally:
        repo.close()


def mine_keywords_multi_marketplace_fast(seed, depth=1, department='kindle',
                                         marketplaces=None, progress_callback=None):
    """Fast async version of mine_keywords_multi_marketplace.

    Falls back to sync version if aiohttp is not available.

    Args:
        seed: Seed keyword.
        depth: Mining depth.
        department: Amazon department.
        marketplaces: List of 2-letter codes. Default: ['us','uk','de','ca'].
        progress_callback: Optional callable(completed, total, marketplace).

    Returns:
        Dict with combined_keywords, new_count, existing_count, per_marketplace results.
    """
    import asyncio

    if not _HAS_ASYNC:
        return mine_keywords_multi_marketplace(
            seed, depth, department, marketplaces, progress_callback,
        )

    if marketplaces is None:
        marketplaces = ['us', 'uk', 'de', 'ca']

    init_db()

    # Use async multi-marketplace mining
    # Wrap the async progress callback to match expected signature
    combined = {}
    per_mp = {}

    total_steps = len(marketplaces)
    for i, mp in enumerate(marketplaces):
        if progress_callback:
            progress_callback(i, total_steps, mp)

        def _sub_progress(current, total, message="", _mp=mp, _i=i):
            if progress_callback:
                frac = current / max(total, 1)
                overall = _i + frac
                progress_callback(overall, total_steps, _mp)

        try:
            raw = asyncio.run(
                mine_autocomplete_async(
                    seed, department=department, depth=depth,
                    marketplace=mp, progress_callback=_sub_progress,
                )
            )
            per_mp[mp] = raw
            for kw, pos in raw:
                if kw not in combined:
                    combined[kw] = {}
                combined[kw][mp] = pos
        except InterruptedError:
            logger.info(f'Mining cancelled during {mp}')
            raise
        except Exception as e:
            logger.warning(f'Failed to mine {mp} for "{seed}": {e}')
            per_mp[mp] = []

    if progress_callback:
        progress_callback(total_steps, total_steps, 'done')

    # Store all in DB
    repo = KeywordRepository()
    new_count = 0
    existing_count = 0
    try:
        for kw, mp_positions in combined.items():
            keyword_id, is_new = repo.upsert_keyword(kw, source='autocomplete', category=seed)
            pos = mp_positions.get('us') or next(iter(mp_positions.values()), None)
            repo.add_metric(keyword_id, autocomplete_position=pos, marketplace='multi')
            if is_new:
                new_count += 1
            else:
                existing_count += 1
    finally:
        repo.close()

    return {
        'combined_keywords': combined,
        'new_count': new_count,
        'existing_count': existing_count,
        'total_unique': len(combined),
        'per_marketplace': per_mp,
        'marketplaces': marketplaces,
        'seed': seed,
    }


# ── Competition probing ───────────────────────────────────────────────────────

class CompetitionProber:
    """Probe Amazon search results for competition data per keyword.

    Uses amazon_search.py (the new search collector) to get real
    top-10 organic results for each keyword, then computes:
    - competition_count (total results)
    - avg_bsr_top10
    - ku_ratio (fraction of top 10 that are KU-eligible)
    - median_reviews
    - top_asins (list of top organic ASINs)

    Results are stored in competition_snapshots and keyword_metrics tables.
    """

    def __init__(self):
        init_db()
        self._repo = KeywordRepository()
        self._interrupted = False

    def close(self):
        self._repo.close()

    def probe_keywords(self, keyword_ids=None, limit=50, marketplace='us',
                       progress_callback=None, cancel_check=None):
        """Probe competition data for a list of keywords.

        Args:
            keyword_ids: List of keyword IDs. If None, probes top `limit` by score.
            limit: Max keywords to probe if keyword_ids is None.
            marketplace: 2-letter marketplace code.
            progress_callback: Optional callable(completed, total, keyword).

        Returns:
            List of probe result dicts, one per keyword.
        """
        from kdp_scout.collectors.amazon_search import AmazonSearchCollector

        if keyword_ids is None:
            rows = self._repo.get_keywords_with_latest_metrics(
                limit=limit, min_score=0, order_by='score',
            )
            keyword_ids = [r['id'] for r in rows]

        if not keyword_ids:
            return []

        collector = AmazonSearchCollector(marketplace=marketplace)
        total = len(keyword_ids)
        results = []

        try:
            for i, kw_id in enumerate(keyword_ids):
                if cancel_check and cancel_check():
                    logger.info(f'CompetitionProber cancelled after {i}/{total}')
                    break

                kw = self._repo.get_keyword_with_metrics(kw_id)
                if kw is None:
                    continue

                keyword_text = kw['keyword']

                try:
                    probe = collector.probe_competition(keyword_text)
                    if probe:
                        self._store_probe(kw_id, probe, marketplace)
                        results.append({'keyword_id': kw_id, 'keyword': keyword_text,
                                        'success': True, **probe})
                    else:
                        results.append({'keyword_id': kw_id, 'keyword': keyword_text,
                                        'success': False})
                except Exception as e:
                    logger.error(f'Probe error for "{keyword_text}": {e}')
                    results.append({'keyword_id': kw_id, 'keyword': keyword_text,
                                    'success': False, 'error': str(e)})

                if progress_callback:
                    progress_callback(i + 1, total, keyword_text)

        finally:
            pass

        return results

    def _store_probe(self, keyword_id, probe, marketplace):
        """Persist probe results to both tables."""
        import json

        top_asins_json = json.dumps(probe.get('top_asins', []))
        raw_json = json.dumps(probe.get('raw_results', []))

        self._repo.add_competition_snapshot(
            keyword_id=keyword_id,
            marketplace=marketplace,
            competition_count=probe.get('competition_count'),
            avg_bsr_top10=probe.get('avg_bsr_top10'),
            median_reviews=probe.get('median_reviews'),
            ku_ratio=probe.get('ku_ratio'),
            top_asins=top_asins_json,
            raw_results=raw_json,
        )

        # Also update keyword_metrics with the new fields
        self._repo.add_metric(
            keyword_id,
            competition_count=probe.get('competition_count'),
            avg_bsr_top_results=probe.get('avg_bsr_top10'),
            top10_avg_bsr=probe.get('avg_bsr_top10'),
            top10_asins=top_asins_json,
            ku_ratio=probe.get('ku_ratio'),
            median_reviews=probe.get('median_reviews'),
            marketplace=marketplace,
        )


# ── Scoring ───────────────────────────────────────────────────────────────────

class KeywordScorer:
    """Scores keywords based on multiple signals.

    Uses weighted normalized scoring across 12 signal dimensions.
    Score is on a 0-100 scale.
    """

    def __init__(self, weights=None):
        init_db()
        self._repo = KeywordRepository()
        self._weights = weights or DEFAULT_WEIGHTS

    def close(self):
        self._repo.close()

    def score_keyword(self, keyword_id: int) -> float:
        return self.score_keyword_detailed(keyword_id)['total']

    def score_keyword_detailed(self, keyword_id: int) -> dict:
        """Compute detailed score breakdown for a keyword.

        Returns dict with 'total' and 'components' (per-signal breakdown).
        """
        kw = self._repo.get_keyword_with_metrics(keyword_id)
        if kw is None:
            return self._empty_result()
        if not isinstance(kw, dict):
            kw = dict(kw)

        autocomplete_pos = kw['autocomplete_position']
        competition_count = kw['competition_count']
        avg_bsr = kw['avg_bsr_top_results'] or kw.get('top10_avg_bsr')
        impressions = kw['impressions']
        clicks = kw['clicks']
        orders = kw['orders']
        estimated_volume = kw['estimated_volume']
        suggested_bid = kw['suggested_bid']
        ku_ratio = kw.get('ku_ratio')
        median_reviews = kw.get('median_reviews')

        # Fall back to ads_search_terms if keyword_metrics lacks ads data
        if not impressions and not clicks and not orders:
            ads_data = self._repo.get_ads_data_for_keyword(kw['keyword'])
            if ads_data:
                impressions = ads_data['impressions']
                clicks = ads_data['clicks']
                orders = ads_data['orders']

        acos = self._repo.get_ads_acos_for_keyword(kw['keyword'])
        own_rank = self._repo.get_own_ranking_for_keyword(keyword_id)

        components = {}

        def _add(name, norm_val, raw, description):
            w = self._weights.get(name, 0.0)
            components[name] = {
                'score': norm_val,
                'weight': w,
                'weighted': norm_val * w * 100,
                'raw': raw,
                'description': description,
            }

        _add('autocomplete', normalize_autocomplete(autocomplete_pos),
             autocomplete_pos,
             f'Position {autocomplete_pos}' if autocomplete_pos else 'Not in autocomplete')

        _add('competition', normalize_competition(competition_count),
             competition_count,
             f'{competition_count:,} results' if competition_count is not None else 'No data')

        _add('bsr_demand', normalize_bsr(avg_bsr),
             avg_bsr,
             f'Avg BSR {avg_bsr:,.0f}' if avg_bsr is not None else 'No data')

        _add('ads_impressions', normalize_impressions(impressions),
             impressions,
             f'{impressions:,} impressions' if impressions is not None else 'No data')

        _add('ads_orders', normalize_orders(orders),
             orders,
             f'{orders:,} orders' if orders is not None else 'No data')

        _add('ads_profitability', normalize_acos(acos),
             acos,
             f'{acos * 100:.1f}% ACOS' if acos is not None else 'No data')

        _add('search_volume', normalize_search_volume(estimated_volume),
             estimated_volume,
             f'{estimated_volume:,} est. volume' if estimated_volume is not None else 'No data')

        _add('commercial_value', normalize_suggested_bid(suggested_bid),
             suggested_bid,
             f'${suggested_bid:.2f} suggested bid' if suggested_bid is not None else 'No data')

        ctr_raw = (clicks / impressions
                   if clicks and impressions and impressions > 0 else None)
        _add('click_through_rate', normalize_ctr(clicks, impressions),
             ctr_raw,
             f'{ctr_raw * 100:.2f}% CTR' if ctr_raw is not None else 'No data')

        _add('own_ranking', normalize_own_ranking(own_rank),
             own_rank,
             f'Rank #{own_rank}' if own_rank is not None else 'Not ranked')

        _add('ku_ratio', normalize_ku_ratio(ku_ratio),
             ku_ratio,
             f'{ku_ratio * 100:.0f}% KU' if ku_ratio is not None else 'No data')

        _add('median_reviews', normalize_median_reviews(median_reviews),
             median_reviews,
             f'{median_reviews} median reviews' if median_reviews is not None else 'No data')

        total = sum(c['weighted'] for c in components.values())
        return {'total': round(total, 1), 'components': components}

    def _empty_result(self):
        components = {}
        for name, weight in self._weights.items():
            components[name] = {
                'score': 0.0, 'weight': weight, 'weighted': 0.0,
                'raw': None, 'description': 'No data',
            }
        return {'total': 0.0, 'components': components}

    def score_all_keywords(self, recalculate=False) -> int:
        if recalculate:
            keyword_ids = self._repo.get_all_keyword_ids(active_only=True)
        else:
            keyword_ids = self._repo.get_unscored_keyword_ids()

        count = 0
        for keyword_id in keyword_ids:
            score = self.score_keyword(keyword_id)
            self._repo.update_score(keyword_id, score)
            count += 1

        logger.info(f'Scored {count} keywords (recalculate={recalculate})')
        return count

    def get_top_keywords(self, limit=50, min_score=0) -> list:
        return self._repo.get_keywords_with_latest_metrics(
            limit=limit, min_score=min_score, order_by='score',
        )


# ── Reverse ASIN ─────────────────────────────────────────────────────────────

class ReverseASIN:
    """Reverse ASIN lookup via search probing or DataForSEO API."""

    SPONSORED_MARKERS = [
        'AdHolder', 'sp-sponsored-result', 'puis-sponsored-label',
        's-sponsored-label', 'a-spacing-micro s-sponsored-label',
    ]
    SEARCH_URL = 'https://www.amazon.com/s'

    def __init__(self):
        init_db()
        self._kw_repo = KeywordRepository()
        self._book_repo = BookRepository()
        self._ranking_repo = KeywordRankingRepository()
        rate_registry.get_limiter(
            'search_probe', rate=Config.SEARCH_PROBE_RATE_LIMIT
        )
        self._interrupted = False

    def close(self):
        self._kw_repo.close()
        self._book_repo.close()
        self._ranking_repo.close()

    def reverse_asin_probe(self, asin, top_n=None, method='auto',
                           progress_callback=None):
        """Find keywords that a given ASIN ranks for.

        Args:
            asin: Amazon ASIN.
            top_n: Only check top N keywords by score.
            method: 'probe', 'dataforseo', or 'auto'.
            progress_callback: Optional callable(completed, total, found, keyword).

        Returns:
            List of dicts with keyword, position, snapshot_date, source.
        """
        asin = asin.upper().strip()

        book = self._book_repo.find_by_asin(asin)
        if not book:
            book_id, _ = self._book_repo.upsert_book(asin=asin)
        else:
            book_id = book['id']

        if method == 'auto':
            from kdp_scout.collectors.dataforseo import DataForSEOCollector
            dfs = DataForSEOCollector()
            method = 'dataforseo' if dfs.is_available() else 'probe'

        if method == 'dataforseo':
            return self._reverse_via_dataforseo(asin, book_id)
        else:
            return self._reverse_via_probe(
                asin, book_id, top_n=top_n, progress_callback=progress_callback,
            )

    def _reverse_via_dataforseo(self, asin, book_id):
        from kdp_scout.collectors.dataforseo import DataForSEOCollector
        dfs = DataForSEOCollector()
        raw_results = dfs.reverse_asin(asin)
        today = date.today().isoformat()
        results = []

        for item in raw_results:
            keyword = item['keyword']
            position = item['position']
            keyword_id, _ = self._kw_repo.upsert_keyword(keyword, source='dataforseo')
            self._ranking_repo.add_ranking(
                keyword_id=keyword_id, book_id=book_id,
                position=position, source='dataforseo', snapshot_date=today,
            )
            results.append({
                'keyword': keyword, 'position': position,
                'snapshot_date': today, 'source': 'dataforseo',
                'search_volume': item.get('search_volume', 0),
            })

        logger.info(
            f'DataForSEO reverse ASIN for {asin}: {len(results)} rankings found '
            f'(spend: ${dfs.get_estimated_spend():.4f})'
        )
        return results

    def _reverse_via_probe(self, asin, book_id, top_n=None, progress_callback=None, cancel_check=None):
        if top_n:
            keywords = self._kw_repo.get_keywords_with_latest_metrics(
                limit=top_n, min_score=0, order_by='score',
            )
        else:
            keywords = self._kw_repo.get_all_keywords(active_only=True)

        if not keywords:
            logger.warning('No keywords in database to probe.')
            return []

        total = len(keywords)
        today = date.today().isoformat()
        results = []
        completed = 0

        try:
            for kw_row in keywords:
                if cancel_check and cancel_check():
                    logger.info('Reverse probe cancelled by user')
                    break

                keyword = kw_row['keyword']
                keyword_id = kw_row['id']

                position = self._probe_search(keyword, asin)

                if position is not None:
                    self._ranking_repo.add_ranking(
                        keyword_id=keyword_id, book_id=book_id,
                        position=position, source='probe', snapshot_date=today,
                    )
                    results.append({
                        'keyword': keyword, 'position': position,
                        'snapshot_date': today, 'source': 'probe',
                    })

                completed += 1
                if progress_callback:
                    progress_callback(completed, total, len(results), keyword)

        finally:
            pass

        logger.info(
            f'Search probe reverse ASIN for {asin}: '
            f'{len(results)} rankings found out of {completed} checked'
        )
        return results

    def _probe_search(self, keyword, target_asin):
        rate_registry.acquire('search_probe')
        params = {'k': keyword, 'i': 'digital-text'}

        try:
            response = fetch(
                self.SEARCH_URL,
                params=params,
                headers=get_browser_headers(),
            )

            if response.status_code != 200:
                return None

            html = response.text

            if self._is_captcha(html):
                logger.warning(f'CAPTCHA detected for "{keyword}". Backing off 30s...')
                time.sleep(30)
                return None

            return self._find_asin_in_results(html, target_asin)

        except Exception as e:
            logger.error(f'Error probing search for "{keyword}": {e}')
            return None

    def _is_captcha(self, html):
        captcha_markers = [
            'Enter the characters you see below',
            "Sorry, we just need to make sure you're not a robot",
            '/errors/validateCaptcha',
            'Type the characters you see in this image',
        ]
        html_lower = html.lower()
        return any(m.lower() in html_lower for m in captcha_markers)

    def _find_asin_in_results(self, html, target_asin):
        soup = BeautifulSoup(html, 'html.parser')
        result_divs = soup.find_all('div', attrs={'data-asin': True})
        organic_position = 0

        for div in result_divs:
            asin = div.get('data-asin', '').strip().upper()
            if not asin:
                continue
            if self._is_sponsored(div):
                continue
            organic_position += 1
            if asin == target_asin:
                return organic_position

        return None

    def _is_sponsored(self, div):
        div_classes = ' '.join(div.get('class', []))
        div_html = str(div)
        for marker in self.SPONSORED_MARKERS:
            if marker in div_classes or marker in div_html:
                return True
        if div.find_all(string=re.compile(r'\bSponsored\b', re.IGNORECASE)):
            return True
        return False

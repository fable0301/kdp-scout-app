"""Amazon autocomplete API keyword miner — multi-marketplace edition.

Mines keywords from Amazon's autocomplete/suggestions endpoint.
Supports all major Amazon marketplaces and extended prefix variants
(a-z, 0-9, question prefixes).

New in this version:
- Multi-marketplace support: mine same seed across .com/.co.uk/.de/.fr/.ca/etc.
- Question prefixes: "best X", "how to X", "top X kindle" patterns
- Numeric prefixes (0-9) for quantity-related keywords
- Frequency scoring: keywords appearing more times = stronger signal
- Keyword frequency map returned alongside results
- Async parallel mining with aiohttp + semaphore concurrency control
- SQLite cache layer with 24-hour TTL
- Branch pruning at depth 2 for faster mining
- Random jitter to avoid rate limiting
"""

import json
import logging
import os
import random
import sqlite3
import string
import time

import requests

from kdp_scout.http_client import fetch
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config

# Graceful optional import of aiohttp + asyncio
try:
    import aiohttp
    import asyncio
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

logger = logging.getLogger(__name__)

# Adaptive backoff state (module-level)
_backoff_until = 0
_backoff_delay = 0

# Per-marketplace autocomplete endpoint configurations
MARKETPLACE_CONFIGS = {
    'us': {
        'url': 'https://completion.amazon.com/api/2017/suggestions',
        'mid': 'ATVPDKIKX0DER',
    },
    'uk': {
        'url': 'https://completion.amazon.co.uk/api/2017/suggestions',
        'mid': 'A1F83G8C2ARO7P',
    },
    'de': {
        'url': 'https://completion.amazon.de/api/2017/suggestions',
        'mid': 'A1PA6795UKMFR9',
    },
    'fr': {
        'url': 'https://completion.amazon.fr/api/2017/suggestions',
        'mid': 'A13V1IB3VIYZZH',
    },
    'ca': {
        'url': 'https://completion.amazon.ca/api/2017/suggestions',
        'mid': 'A2EUQ1WTGCTBG2',
    },
    'au': {
        'url': 'https://completion.amazon.com.au/api/2017/suggestions',
        'mid': 'A39IBJ37TRP1C6',
    },
    'jp': {
        'url': 'https://completion.amazon.co.jp/api/2017/suggestions',
        'mid': 'A1VC38T7YXB528',
    },
    'es': {
        'url': 'https://completion.amazon.es/api/2017/suggestions',
        'mid': 'A1RKKUPIHCS9HS',
    },
    'it': {
        'url': 'https://completion.amazon.it/api/2017/suggestions',
        'mid': 'APJ6JRA9NG5V4',
    },
    'mx': {
        'url': 'https://completion.amazon.com.mx/api/2017/suggestions',
        'mid': 'A1AM78C64UM0Y8',
    },
    'in': {
        'url': 'https://completion.amazon.in/api/2017/suggestions',
        'mid': 'A21TJRUUN4KGV',
    },
    'nl': {
        'url': 'https://completion.amazon.nl/api/2017/suggestions',
        'mid': 'A1805IZSGTT6HS',
    },
    'se': {
        'url': 'https://completion.amazon.se/api/2017/suggestions',
        'mid': 'A2NODRKZP88ZB9',
    },
    'pl': {
        'url': 'https://completion.amazon.pl/api/2017/suggestions',
        'mid': 'AZ8DMDRTYD4OY',
    },
    'br': {
        'url': 'https://completion.amazon.com.br/api/2017/suggestions',
        'mid': 'A2Q3Y263D00KWC',
    },
}

# Department alias mapping
DEPARTMENT_ALIASES = {
    'kindle': 'digital-text',
    'books': 'stripbooks',
    'all': 'aps',
    'digital-text': 'digital-text',
    'stripbooks': 'stripbooks',
    'aps': 'aps',
    'audible': 'audible',
}

# Extended prefix sets
ALPHA_PREFIXES = list(string.ascii_lowercase)
NUMERIC_PREFIXES = [str(i) for i in range(10)]

# Question/intent prefixes that reveal buyer intent
QUESTION_PREFIXES = [
    'best', 'top', 'how to', 'what is', 'guide to', 'introduction to',
    'beginner', 'advanced', 'complete', 'ultimate', 'essential',
]

# KDP-specific suffix patterns
KDP_SUFFIXES = [
    'kindle', 'kindle unlimited', 'ebook', 'paperback',
    'for beginners', 'for adults', 'for teens', 'for kids',
    'series', 'romance', 'fiction', 'nonfiction',
]


# ── SQLite Cache Layer ──────────────────────────────────────────────────────

_CACHE_TTL = 86400  # 24 hours
_cache_db_path = None
_cache_initialized = False


def _get_cache_db_path():
    global _cache_db_path
    if _cache_db_path is None:
        cache_dir = os.path.expanduser('~/.kdp_scout')
        os.makedirs(cache_dir, exist_ok=True)
        _cache_db_path = os.path.join(cache_dir, 'autocomplete_cache.db')
    return _cache_db_path


def _ensure_cache_table(conn):
    global _cache_initialized
    if not _cache_initialized:
        conn.execute(
            'CREATE TABLE IF NOT EXISTS cache ('
            '  prefix TEXT, alias TEXT, marketplace TEXT, results TEXT, ts REAL,'
            '  PRIMARY KEY(prefix, alias, marketplace)'
            ')'
        )
        conn.commit()
        _cache_initialized = True


def _cache_get(prefix, alias, marketplace):
    """Get cached results. Returns list of [keyword, position] or None if miss/expired."""
    try:
        conn = sqlite3.connect(_get_cache_db_path())
        _ensure_cache_table(conn)
        row = conn.execute(
            'SELECT results, ts FROM cache WHERE prefix=? AND alias=? AND marketplace=?',
            (prefix, alias, marketplace),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        results_json, ts = row
        if time.time() - ts > _CACHE_TTL:
            return None
        return json.loads(results_json)
    except Exception as e:
        logger.debug(f'Cache get error: {e}')
        return None


def _cache_set(prefix, alias, marketplace, results):
    """Store results in cache. Results is list of (keyword, position) tuples."""
    try:
        serializable = [[kw, pos] for kw, pos in results]
        conn = sqlite3.connect(_get_cache_db_path())
        _ensure_cache_table(conn)
        conn.execute(
            'INSERT OR REPLACE INTO cache (prefix, alias, marketplace, results, ts) '
            'VALUES (?, ?, ?, ?, ?)',
            (prefix, alias, marketplace, json.dumps(serializable), time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.debug(f'Cache set error: {e}')


def clear_cache():
    """Clear the entire autocomplete cache."""
    try:
        conn = sqlite3.connect(_get_cache_db_path())
        _ensure_cache_table(conn)
        conn.execute('DELETE FROM cache')
        conn.commit()
        conn.close()
        logger.info('Autocomplete cache cleared')
    except Exception as e:
        logger.warning(f'Failed to clear cache: {e}')


# ── Sync Mining (original, with cache + pruning) ───────────────────────────


def mine_autocomplete(seed, department='kindle', depth=1, progress_callback=None,
                      marketplace='us', include_questions=False):
    """Mine keywords from Amazon's autocomplete API for a single marketplace.

    Queries the seed keyword directly, then expands with a-z suffix variations.
    At depth 2, each result is further expanded with a-z. Optionally adds
    question-prefix variants for buyer-intent discovery.

    Args:
        seed: The seed keyword to mine (e.g., "historical fiction").
        department: Amazon department ('kindle', 'books', or 'all').
        depth: Mining depth. 1 = seed + a-z (27 queries).
               2 = depth 1 + expand each result with a-z.
        progress_callback: Optional callable(completed, total) for progress updates.
        marketplace: Marketplace code ('us', 'uk', 'de', etc.).
        include_questions: If True, also query common question prefixes.

    Returns:
        List of (keyword, position) tuples, deduplicated and sorted.
        Position reflects best autocomplete rank seen across all queries.
    """
    rate_registry.get_limiter('autocomplete', rate=Config.AUTOCOMPLETE_RATE_LIMIT)

    alias = DEPARTMENT_ALIASES.get(department, department)
    all_results = {}  # keyword -> best position

    # Phase 1: Query seed keyword directly + a-z expansions
    prefixes = [seed] + [f'{seed} {c}' for c in ALPHA_PREFIXES]

    # Add numeric prefixes
    prefixes += [f'{seed} {n}' for n in NUMERIC_PREFIXES]

    # Add question/intent prefixes if requested
    if include_questions:
        prefixes += [f'{q} {seed}' for q in QUESTION_PREFIXES]
        prefixes += [f'{seed} {s}' for s in KDP_SUFFIXES]

    total_queries = len(prefixes)
    completed = 0

    # Track which keywords produced results (for pruning at depth 2)
    productive_keywords = set()

    for prefix in prefixes:
        suggestions = _query_autocomplete(prefix, alias, marketplace=marketplace)
        for kw, pos in suggestions:
            if kw not in all_results or pos < all_results[kw]:
                all_results[kw] = pos
        if suggestions:
            productive_keywords.update(kw for kw, _ in suggestions)

        completed += 1
        if progress_callback:
            progress_callback(completed, total_queries)

    # Phase 2: Depth 2 expansion — expand each depth-1 result (with pruning)
    if depth >= 2:
        depth1_keywords = list(all_results.keys())
        expansion_prefixes = []
        for kw in depth1_keywords:
            # Pruning: skip keywords not in productive set
            if kw not in productive_keywords:
                continue
            # Pruning: skip keywords with more than 6 words
            if len(kw.split()) > 6:
                continue
            for c in ALPHA_PREFIXES:
                expansion_prefixes.append(f'{kw} {c}')

        total_queries = completed + len(expansion_prefixes)

        for prefix in expansion_prefixes:
            suggestions = _query_autocomplete(prefix, alias, marketplace=marketplace)
            for kw, pos in suggestions:
                if kw not in all_results or pos < all_results[kw]:
                    all_results[kw] = pos

            completed += 1
            if progress_callback:
                progress_callback(completed, total_queries)

    results = sorted(all_results.items(), key=lambda x: (x[1], x[0]))

    logger.info(
        f'Autocomplete mining for "{seed}" '
        f'(depth={depth}, dept={department}, marketplace={marketplace}): '
        f'{len(results)} keywords found'
    )

    return results


def mine_autocomplete_multi_marketplace(seed, department='kindle', depth=1,
                                        marketplaces=None, progress_callback=None):
    """Mine keywords across multiple Amazon marketplaces simultaneously.

    Runs autocomplete mining on each marketplace and merges results,
    annotating each keyword with which marketplaces it appears in.
    Keywords appearing in multiple marketplaces get a boost in position score.

    Args:
        seed: Seed keyword.
        department: Amazon department.
        depth: Mining depth.
        marketplaces: List of marketplace codes. Defaults to ['us', 'uk', 'de', 'fr', 'ca'].
        progress_callback: Optional callable(completed, total).

    Returns:
        List of dicts: [{'keyword': str, 'best_position': int,
                         'marketplaces': list, 'frequency': int}]
        Sorted by frequency DESC, then best_position ASC.
    """
    if marketplaces is None:
        marketplaces = ['us', 'uk', 'de', 'fr', 'ca']

    rate_registry.get_limiter('autocomplete', rate=Config.AUTOCOMPLETE_RATE_LIMIT)

    # keyword -> {'best_position': int, 'marketplaces': set, 'frequency': int}
    merged = {}

    total_phases = len(marketplaces)
    completed_phases = 0

    for mp in marketplaces:
        def sub_progress(c, t):
            if progress_callback:
                total_est = t * total_phases
                done_so_far = completed_phases * t + c
                progress_callback(done_so_far, total_est)

        try:
            results = mine_autocomplete(
                seed, department=department, depth=depth,
                marketplace=mp, progress_callback=sub_progress,
            )
        except Exception as e:
            logger.warning(f'Error mining marketplace {mp}: {e}')
            results = []

        for kw, pos in results:
            if kw not in merged:
                merged[kw] = {
                    'keyword': kw,
                    'best_position': pos,
                    'marketplaces': set(),
                    'frequency': 0,
                }
            entry = merged[kw]
            entry['frequency'] += 1
            entry['marketplaces'].add(mp)
            if pos < entry['best_position']:
                entry['best_position'] = pos

        completed_phases += 1
        if progress_callback:
            progress_callback(completed_phases * 27, total_phases * 27)  # Rough estimate

    # Convert sets to lists for serialization
    output = []
    for entry in merged.values():
        output.append({
            'keyword': entry['keyword'],
            'best_position': entry['best_position'],
            'marketplaces': sorted(entry['marketplaces']),
            'marketplace_count': len(entry['marketplaces']),
            'frequency': entry['frequency'],
        })

    # Sort: most marketplaces first, then best position
    output.sort(key=lambda x: (-x['marketplace_count'], x['best_position']))

    logger.info(
        f'Multi-marketplace mining for "{seed}": '
        f'{len(output)} unique keywords across {len(marketplaces)} marketplaces'
    )

    return output


def get_keyword_frequency_score(seed, department='kindle', marketplace='us'):
    """Compute a frequency score for a keyword by counting how many prefix
    queries return it in autocomplete suggestions.

    Higher frequency = Amazon shows it more consistently = stronger real-world signal.

    Args:
        seed: Keyword to score.
        department: Amazon department.
        marketplace: Marketplace code.

    Returns:
        Int: number of prefix queries (out of 27) that returned this keyword.
    """
    rate_registry.get_limiter('autocomplete', rate=Config.AUTOCOMPLETE_RATE_LIMIT)
    alias = DEPARTMENT_ALIASES.get(department, department)
    prefixes = [seed] + [f'{seed} {c}' for c in ALPHA_PREFIXES]

    count = 0
    for prefix in prefixes:
        suggestions = _query_autocomplete(prefix, alias, marketplace=marketplace)
        if any(kw == seed.lower() for kw, _ in suggestions):
            count += 1

    return count


# ── Async Mining ────────────────────────────────────────────────────────────


async def _query_autocomplete_async(session, sem, prefix, alias, marketplace='us'):
    """Async query of Amazon autocomplete API for a single prefix."""
    # Check cache first
    cached = _cache_get(prefix, alias, marketplace)
    if cached is not None:
        return [(kw, pos) for kw, pos in cached]

    async with sem:
        await asyncio.sleep(random.uniform(0.05, 0.25))  # jitter
        config = MARKETPLACE_CONFIGS.get(marketplace, MARKETPLACE_CONFIGS['us'])
        params = {'mid': config['mid'], 'alias': alias, 'prefix': prefix}
        headers = {
            'User-Agent': random.choice(Config.USER_AGENTS),
            'Accept': 'application/json, text/html, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        for attempt in range(3):
            try:
                async with session.get(
                    config['url'], params=params, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status in (429, 503):
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            f'Amazon {resp.status} for "{prefix}" — retry in {wait:.1f}s'
                        )
                        await asyncio.sleep(wait)
                        continue
                    if resp.status != 200:
                        return []
                    data = await resp.json(content_type=None)
                    suggestions = data.get('suggestions', [])
                    results = [
                        (s.get('value', '').strip().lower(), i + 1)
                        for i, s in enumerate(suggestions)
                        if s.get('value', '').strip()
                    ]
                    _cache_set(prefix, alias, marketplace, results)
                    return results
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if attempt == 2:
                    logger.error(f'Error querying autocomplete async for "{prefix}": {e}')
                    return []
                await asyncio.sleep(1)
        return []


async def mine_autocomplete_async(seed, department='kindle', depth=1,
                                  progress_callback=None, marketplace='us',
                                  include_questions=False):
    """Async version of mine_autocomplete with parallel requests.

    Uses aiohttp + semaphore for concurrency control (10 parallel requests),
    random jitter, retry on 429/503, cache, and branch pruning at depth 2.

    Args:
        seed: The seed keyword to mine.
        department: Amazon department ('kindle', 'books', or 'all').
        depth: Mining depth. 1 = seed + a-z. 2 = recursive expansion.
        progress_callback: Optional callable(completed, total). Called normally (not awaited).
        marketplace: Marketplace code ('us', 'uk', 'de', etc.).
        include_questions: If True, also query common question prefixes.

    Returns:
        List of (keyword, position) tuples, deduplicated and sorted.
    """
    if not HAS_AIOHTTP:
        # Fallback to sync
        return mine_autocomplete(
            seed, department=department, depth=depth,
            progress_callback=progress_callback, marketplace=marketplace,
            include_questions=include_questions,
        )

    alias = DEPARTMENT_ALIASES.get(department, department)
    all_results = {}  # keyword -> best position
    sem = asyncio.Semaphore(10)

    # Phase 1: Build prefixes
    prefixes = [seed] + [f'{seed} {c}' for c in ALPHA_PREFIXES]
    prefixes += [f'{seed} {n}' for n in NUMERIC_PREFIXES]

    if include_questions:
        prefixes += [f'{q} {seed}' for q in QUESTION_PREFIXES]
        prefixes += [f'{seed} {s}' for s in KDP_SUFFIXES]

    total_queries = len(prefixes)
    completed = [0]  # mutable for closure

    async with aiohttp.ClientSession() as session:
        # Phase 1: Execute all prefix queries in parallel
        async def _run_query_phase1(prefix):
            result = await _query_autocomplete_async(session, sem, prefix, alias, marketplace)
            completed[0] += 1
            if progress_callback:
                progress_callback(completed[0], total_queries)
            return prefix, result

        phase1_tasks = [_run_query_phase1(p) for p in prefixes]
        phase1_results = await asyncio.gather(*phase1_tasks, return_exceptions=True)

        # Collect results and track productive keywords
        productive_keywords = set()
        for item in phase1_results:
            if isinstance(item, Exception):
                logger.error(f'Phase 1 query error: {item}')
                continue
            prefix, suggestions = item
            for kw, pos in suggestions:
                if kw not in all_results or pos < all_results[kw]:
                    all_results[kw] = pos
            if suggestions:
                productive_keywords.update(kw for kw, _ in suggestions)

        # Phase 2: Depth 2 expansion with pruning
        if depth >= 2:
            depth1_keywords = list(all_results.keys())
            expansion_prefixes = []
            for kw in depth1_keywords:
                # Pruning: skip unproductive keywords
                if kw not in productive_keywords:
                    continue
                # Pruning: skip keywords with more than 6 words
                if len(kw.split()) > 6:
                    continue
                for c in ALPHA_PREFIXES:
                    expansion_prefixes.append(f'{kw} {c}')

            total_queries = completed[0] + len(expansion_prefixes)

            async def _run_query_phase2(prefix):
                result = await _query_autocomplete_async(session, sem, prefix, alias, marketplace)
                completed[0] += 1
                if progress_callback:
                    progress_callback(completed[0], total_queries)
                return result

            phase2_tasks = [_run_query_phase2(p) for p in expansion_prefixes]
            phase2_results = await asyncio.gather(*phase2_tasks, return_exceptions=True)

            for item in phase2_results:
                if isinstance(item, Exception):
                    logger.error(f'Phase 2 query error: {item}')
                    continue
                for kw, pos in item:
                    if kw not in all_results or pos < all_results[kw]:
                        all_results[kw] = pos

    results = sorted(all_results.items(), key=lambda x: (x[1], x[0]))

    logger.info(
        f'Async autocomplete mining for "{seed}" '
        f'(depth={depth}, dept={department}, marketplace={marketplace}): '
        f'{len(results)} keywords found'
    )

    return results


async def mine_autocomplete_multi_marketplace_async(seed, department='kindle', depth=1,
                                                    marketplaces=None, progress_callback=None):
    """Async version of mine_autocomplete_multi_marketplace.

    Mines each marketplace sequentially (to avoid overloading), but each
    marketplace's mining uses async parallel requests internally.

    Args:
        seed: Seed keyword.
        department: Amazon department.
        depth: Mining depth.
        marketplaces: List of marketplace codes. Defaults to ['us', 'uk', 'de', 'fr', 'ca'].
        progress_callback: Optional callable(completed, total).

    Returns:
        List of dicts with keyword, best_position, marketplaces, frequency.
    """
    if marketplaces is None:
        marketplaces = ['us', 'uk', 'de', 'fr', 'ca']

    merged = {}
    total_phases = len(marketplaces)
    completed_phases = 0

    for mp in marketplaces:
        def sub_progress(c, t, _cp=completed_phases):
            if progress_callback:
                total_est = t * total_phases
                done_so_far = _cp * t + c
                progress_callback(done_so_far, total_est)

        try:
            results = await mine_autocomplete_async(
                seed, department=department, depth=depth,
                marketplace=mp, progress_callback=sub_progress,
            )
        except Exception as e:
            logger.warning(f'Error mining marketplace {mp}: {e}')
            results = []

        for kw, pos in results:
            if kw not in merged:
                merged[kw] = {
                    'keyword': kw,
                    'best_position': pos,
                    'marketplaces': set(),
                    'frequency': 0,
                }
            entry = merged[kw]
            entry['frequency'] += 1
            entry['marketplaces'].add(mp)
            if pos < entry['best_position']:
                entry['best_position'] = pos

        completed_phases += 1
        if progress_callback:
            progress_callback(completed_phases * 27, total_phases * 27)

    output = []
    for entry in merged.values():
        output.append({
            'keyword': entry['keyword'],
            'best_position': entry['best_position'],
            'marketplaces': sorted(entry['marketplaces']),
            'marketplace_count': len(entry['marketplaces']),
            'frequency': entry['frequency'],
        })

    output.sort(key=lambda x: (-x['marketplace_count'], x['best_position']))

    logger.info(
        f'Async multi-marketplace mining for "{seed}": '
        f'{len(output)} unique keywords across {len(marketplaces)} marketplaces'
    )

    return output


# ── Internal helpers ──────────────────────────────────────────────────────


def _query_autocomplete(prefix, alias, marketplace='us'):
    """Query the Amazon autocomplete API for a single prefix (sync).

    Args:
        prefix: Search prefix string.
        alias: Amazon department alias.
        marketplace: Marketplace code.

    Returns:
        List of (keyword, position) tuples.
    """
    global _backoff_until, _backoff_delay

    # Check cache first
    cached = _cache_get(prefix, alias, marketplace)
    if cached is not None:
        return [(kw, pos) for kw, pos in cached]

    rate_registry.acquire('autocomplete')

    # Adaptive backoff
    now = time.monotonic()
    if now < _backoff_until:
        wait = _backoff_until - now
        logger.debug(f'Adaptive backoff: waiting {wait:.1f}s')
        time.sleep(wait)

    config = MARKETPLACE_CONFIGS.get(marketplace, MARKETPLACE_CONFIGS['us'])

    params = {
        'mid': config['mid'],
        'alias': alias,
        'prefix': prefix,
    }

    try:
        response = fetch(config['url'], params=params)
    except (requests.Timeout, requests.ConnectionError) as e:
        logger.error(f'Network error querying autocomplete for "{prefix}" ({marketplace}): {e}')
        return []
    except requests.RequestException as e:
        logger.error(f'Request error querying autocomplete for "{prefix}" ({marketplace}): {e}')
        return []

    try:
        if response.status_code in (429, 503):
            _backoff_delay = min(max(_backoff_delay * 2, 5), 60)
            _backoff_until = time.monotonic() + _backoff_delay
            logger.warning(
                f'Amazon {response.status_code} for "{prefix}" ({marketplace}) — '
                f'backing off {_backoff_delay}s'
            )
            return []

        if response.status_code != 200:
            logger.warning(
                f'Autocomplete returned {response.status_code} for "{prefix}" ({marketplace})'
            )
            return []

        # Success — reset backoff
        _backoff_delay = 0

        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f'Invalid JSON from autocomplete for "{prefix}": {e}')
            return []

        suggestions = data.get('suggestions', [])
        results = []
        for i, suggestion in enumerate(suggestions):
            keyword = suggestion.get('value', '').strip().lower()
            if keyword:
                results.append((keyword, i + 1))

        # Cache the results
        _cache_set(prefix, alias, marketplace, results)

        logger.debug(f'"{prefix}" ({marketplace}) -> {len(results)} suggestions')
        return results

    except Exception as e:
        logger.error(f'Error processing autocomplete for "{prefix}": {e}')
        return []

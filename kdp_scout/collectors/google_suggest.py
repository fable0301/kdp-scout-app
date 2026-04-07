"""Google Suggest collector for KDP keyword research.

Uses Google Autocomplete API (free, no key needed) to discover
trending and long-tail book keywords.
"""

import logging
import re
import string

from kdp_scout.http_client import fetch
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config

logger = logging.getLogger(__name__)

_ALPHABET = string.ascii_lowercase

# Book-specific query patterns for suggest mining
SUGGEST_PATTERNS = [
    "best {seed} books 2026",
    "{seed} books like",
    "new {seed} books",
    "top {seed} kindle",
    "{seed} kindle unlimited",
    "{seed} book recommendations",
    "{seed} books for",
]

TRENDING_CATEGORIES = [
    "romance", "thriller", "mystery", "fantasy", "sci fi",
    "horror", "self help", "historical fiction", "young adult",
    "true crime", "memoir", "business",
]

KDP_NICHES = [
    "dark romance", "booktok", "romantasy", "cozy mystery",
    "reverse harem", "litrpg", "slow burn romance", "paranormal romance",
    "psychological thriller", "space opera", "urban fantasy", "cottagecore",
    "coloring book", "activity book", "journal", "planner",
]


def query_google_suggest(query):
    """Query Google Autocomplete API.

    Returns list of (suggestion, position) tuples.
    """
    rate_registry.get_limiter("autocomplete", rate=Config.AUTOCOMPLETE_RATE_LIMIT)
    rate_registry.acquire("autocomplete")

    url = "https://suggestqueries.google.com/complete/search"
    params = {"client": "firefox", "q": query}

    try:
        response = fetch(url, params=params)
        if response.status_code != 200:
            return []
        data = response.json()
        if not isinstance(data, list) or len(data) < 2:
            return []
        results = []
        for i, suggestion in enumerate(data[1]):
            kw = suggestion.strip()
            if kw and kw.lower() != query.lower():
                results.append((kw, i + 1))
        return results
    except Exception as e:
        logger.debug(f"Google suggest failed for \"{query}\": {e}")
        return []


def discover_trending_suggest(custom_seeds=None, progress_callback=None, cancel_check=None):
    """Discover trending book keywords via Google Suggest.

    Args:
        custom_seeds: Optional list of seed keywords. If provided, performs
                      a deep alphabet crawl on those seeds instead of the
                      default broad category scan.
    Returns list of (keyword, position) tuples.
    """
    all_results = {}
    queries = []

    if not custom_seeds:
        seeds = TRENDING_CATEGORIES
        for category in seeds:
            for pattern in SUGGEST_PATTERNS:
                queries.append(pattern.format(seed=category))
        for niche in KDP_NICHES:
            queries.append(f"{niche} books")
            queries.append(f"best {niche} 2026")
    else:
        # Deep exploration for each custom seed:
        # all SUGGEST_PATTERNS + full alphabet crawl (same as mine_suggest_keywords)
        for seed in custom_seeds:
            for pattern in SUGGEST_PATTERNS:
                queries.append(pattern.format(seed=seed))
            queries.append(f"{seed} books")
            queries.append(f"best {seed} 2026")
            for letter in _ALPHABET:
                queries.append(f"{seed} {letter}")
                queries.append(f"{seed} book {letter}")

    total = len(queries)
    completed = 0

    for query in queries:
        if cancel_check and cancel_check():
            break
        suggestions = query_google_suggest(query)
        for kw, pos in suggestions:
            cleaned = _clean_book_keyword(kw)
            if cleaned and len(cleaned) >= 3:
                if cleaned not in all_results or pos < all_results[cleaned]:
                    all_results[cleaned] = pos
        completed += 1
        if progress_callback:
            progress_callback(completed, total)

    results = sorted(all_results.items(), key=lambda x: (x[1], x[0]))
    logger.info(f"Google Suggest trending: {len(results)} keywords")
    return results


def mine_suggest_keywords(seed, progress_callback=None, cancel_check=None):
    """Mine Google Suggest for a seed keyword using alphabet expansion.

    Returns list of dicts: {keyword, source, position}
    """
    all_results = {}
    queries = []

    # Base queries
    queries.append(seed)
    queries.append(f"{seed} book")
    queries.append(f"{seed} kindle")
    queries.append(f"best {seed} books")

    # Alphabet crawl
    for letter in _ALPHABET:
        queries.append(f"{seed} {letter}")
        queries.append(f"{seed} book {letter}")

    # Question patterns
    for prefix in ["how to", "what is", "why do", "best way to"]:
        queries.append(f"{prefix} {seed}")

    total = len(queries)
    completed = 0

    for query in queries:
        if cancel_check and cancel_check():
            break
        suggestions = query_google_suggest(query)
        for kw, pos in suggestions:
            kw_clean = kw.strip().lower()
            if kw_clean and kw_clean not in all_results:
                all_results[kw_clean] = {
                    "keyword": kw.strip(),
                    "source": f"Suggest: {query}",
                    "position": pos,
                }
        completed += 1
        if progress_callback:
            progress_callback(completed, total)

    results = sorted(all_results.values(), key=lambda x: x["position"])
    logger.info(f"Suggest mining for \"{seed}\": {len(results)} keywords")
    return results


def get_related_searches(query, progress_callback=None, cancel_check=None):
    """Get related searches by querying variations of a keyword.

    Returns list of dicts: {keyword, source, position}
    """
    all_results = {}
    queries = [
        query,
        f"{query} vs",
        f"{query} or",
        f"{query} like",
        f"{query} similar to",
        f"{query} alternative",
        f"{query} books similar",
        f"books like {query}",
        f"{query} genre",
        f"{query} niche",
    ]

    total = len(queries)
    for i, q in enumerate(queries):
        if cancel_check and cancel_check():
            break
        suggestions = query_google_suggest(q)
        for kw, pos in suggestions:
            kw_lower = kw.strip().lower()
            if kw_lower and kw_lower not in all_results:
                all_results[kw_lower] = {
                    "keyword": kw.strip(),
                    "source": f"Related: {q}",
                    "position": pos,
                }
        if progress_callback:
            progress_callback(i + 1, total)

    return sorted(all_results.values(), key=lambda x: x["position"])


# Fast async variant
try:
    import aiohttp as _aiohttp
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False


async def _discover_suggest_async(queries, progress_callback=None, cancel_check=None):
    """Async Google Suggest using aiohttp."""
    import asyncio
    sem = asyncio.Semaphore(10)
    results = []
    done = 0

    async def _fetch(session, q):
        nonlocal done
        if cancel_check and cancel_check():
            return []
        async with sem:
            if cancel_check and cancel_check():
                return []
            url = "https://suggestqueries.google.com/complete/search"
            params = {"client": "firefox", "q": q}
            try:
                async with session.get(url, params=params,
                                       timeout=_aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json(content_type=None)
                    done += 1
                    if progress_callback:
                        progress_callback(done, len(queries))
                    if isinstance(data, list) and len(data) >= 2:
                        return [(s.strip(), i + 1) for i, s in enumerate(data[1]) if s.strip()]
                    return []
            except Exception:
                done += 1
                if progress_callback:
                    progress_callback(done, len(queries))
                return []

    async with _aiohttp.ClientSession() as session:
        tasks = [_fetch(session, q) for q in queries]
        batch = await asyncio.gather(*tasks)
        for kws in batch:
            results.extend(kws)
    return results


def discover_trending_suggest_fast(custom_seeds=None, progress_callback=None, cancel_check=None):
    """Fast async variant of discover_trending_suggest."""
    import asyncio
    if not _HAS_AIOHTTP:
        return discover_trending_suggest(custom_seeds, progress_callback, cancel_check)

    queries = []

    if not custom_seeds:
        seeds = TRENDING_CATEGORIES + KDP_NICHES
        # Broad alphabet crawl for default mode
        for letter in _ALPHABET:
            queries.append(f"{letter} books")
            queries.append(f"{letter} kindle")
        for seed in seeds:
            queries.append(f"{seed} books")
            queries.append(f"best {seed} 2026")
            queries.append(f"new {seed} books")
    else:
        # Deep exploration for each custom seed:
        # all SUGGEST_PATTERNS + full alphabet crawl
        for seed in custom_seeds:
            for pattern in SUGGEST_PATTERNS:
                queries.append(pattern.format(seed=seed))
            queries.append(f"{seed} books")
            queries.append(f"best {seed} 2026")
            for letter in _ALPHABET:
                queries.append(f"{seed} {letter}")
                queries.append(f"{seed} book {letter}")

    raw = asyncio.run(_discover_suggest_async(queries, progress_callback, cancel_check))

    seen = {}
    for kw, pos in raw:
        cleaned = _clean_book_keyword(kw)
        if cleaned and len(cleaned) >= 3 and cleaned not in seen:
            seen[cleaned] = pos
    results = sorted(seen.items(), key=lambda x: (x[1], x[0]))
    logger.info(f"Google Suggest trending (fast): {len(results)} keywords")
    return results


def _clean_book_keyword(keyword):
    """Clean a suggest result into a KDP-relevant keyword."""
    kw = keyword.lower().strip()
    for prefix in ["best ", "top ", "new ", "most popular "]:
        if kw.startswith(prefix):
            kw = kw[len(prefix):]
    kw = re.sub(r"\b20\d{2}\b", "", kw)
    for suffix in [" books", " kindle", " kindle unlimited", " book",
                   " recommendations", " to read", " on amazon",
                   " for adults", " for beginners"]:
        if kw.endswith(suffix):
            kw = kw[:-len(suffix)]
    kw = re.sub(r"\s+", " ", kw).strip()
    return kw if len(kw) >= 3 else ""



def mine_suggest_keywords_fast(seed, progress_callback=None, cancel_check=None):
    """Fast async variant of mine_suggest_keywords using aiohttp."""
    import asyncio
    if not _HAS_AIOHTTP:
        return mine_suggest_keywords(seed, progress_callback, cancel_check)

    _ALPHA = __import__("string").ascii_lowercase
    queries = [seed, f"{seed} book", f"{seed} kindle", f"best {seed} books"]
    for letter in _ALPHA:
        queries.append(f"{seed} {letter}")
        queries.append(f"{seed} book {letter}")
    for prefix in ["how to", "what is", "why do", "best way to"]:
        queries.append(f"{prefix} {seed}")

    raw = asyncio.run(_discover_suggest_async(queries, progress_callback, cancel_check))

    all_results = {}
    for kw, pos in raw:
        kw_clean = kw.strip().lower()
        if kw_clean and kw_clean not in all_results:
            all_results[kw_clean] = {
                "keyword": kw.strip(),
                "source": "Google Suggest",
                "position": pos,
            }
    results = sorted(all_results.values(), key=lambda x: x["position"])
    logger.info(f"Suggest mining FAST for \"{seed}\": {len(results)} keywords")
    return results


def get_related_searches_fast(query, progress_callback=None, cancel_check=None):
    """Fast async variant of get_related_searches."""
    import asyncio
    if not _HAS_AIOHTTP:
        return get_related_searches(query, progress_callback, cancel_check)

    queries = [
        query, f"{query} vs", f"{query} or", f"{query} like",
        f"{query} similar to", f"{query} alternative",
        f"{query} books similar", f"books like {query}",
        f"{query} genre", f"{query} niche",
    ]

    raw = asyncio.run(_discover_suggest_async(queries, progress_callback, cancel_check))

    all_results = {}
    for kw, pos in raw:
        kw_lower = kw.strip().lower()
        if kw_lower and kw_lower not in all_results:
            all_results[kw_lower] = {
                "keyword": kw.strip(),
                "source": "Related Search",
                "position": pos,
            }
    return sorted(all_results.values(), key=lambda x: x["position"])

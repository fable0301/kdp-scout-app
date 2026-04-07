"""Auto-discovery engine v2 — "Niche Sniper".

Pipeline with configurable depth:
    ⚡ Quick  (1 pass) — harvest → cluster → score → classify
    🔍 Deep (2 pass) — quick + re-inject top clusters as new seeds → deeper clusters
    🎯 Sniper  (3 pass) — deep + micro-niche expansion → GO/NO-GO actionable cards

Market type filter: All / Low Content / Medium Content / High Content
Composite weighted scoring with GO score (0-100).
"""

import csv
import io
import logging
import math
import re
import statistics
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# ── Depth levels ─────────────────────────────────────────────────────────
DEPTH_QUICK = "quick"
DEPTH_DEEP = "deep"
DEPTH_SNIPER = "sniper"

# ── Market type filters ──────────────────────────────────────────────────
MARKET_ALL = "all"
MARKET_LOW_CONTENT = "low_content"
MARKET_MEDIUM_CONTENT = "medium_content"
MARKET_HIGH_CONTENT = "high_content"

# ── Autocomplete seed keywords ───────────────────────────────────────────

_SEEDS_HIGH_CONTENT = [
    'dark romance', 'romantasy', 'spicy romance', 'cozy mystery',
    'psychological thriller', 'fantasy romance', 'sapphic romance',
    'enemies to lovers', 'booktok', 'reverse harem', 'mafia romance',
    'bully romance', 'fae', 'haunted', 'true crime', 'hockey romance',
    'small town romance', 'dragon', 'witch', 'zombie', 'apocalypse',
    'dystopian', 'alien romance', 'age gap romance', 'forbidden romance',
    'gothic', 'paranormal', 'urban fantasy', 'litrpg', 'progression fantasy',
    'monster romance', 'why choose', 'omegaverse',
]

_SEEDS_MEDIUM_CONTENT = [
    'self help', 'self improvement', 'passive income', 'artificial intelligence',
    'anxiety', 'manifestation', 'stoicism', 'adhd', 'parenting',
    'keto', 'intermittent fasting', 'real estate investing',
    'day trading', 'crypto', 'journaling', 'mindfulness',
    'productivity', 'side hustle', 'retirement', 'leadership',
    'meal prep', 'gut health', 'autoimmune', 'dopamine',
]

_SEEDS_LOW_CONTENT = [
    'activity book', 'puzzle book', 'word search', 'sudoku',
    'gratitude journal', 'planner 2026', 'log book', 'notebook',
    'coloring book for adults', 'dot to dot', 'maze book',
    'password book', 'recipe book blank', 'coloring book for kids',
    'coloring book animals', 'coloring book flowers', 'sticker book',
    'tracing book', 'handwriting practice', 'composition notebook',
]

_AUTOCOMPLETE_SEEDS = _SEEDS_HIGH_CONTENT + _SEEDS_MEDIUM_CONTENT + _SEEDS_LOW_CONTENT

def _get_seeds_for_market(market_type):
    """Return seed list filtered by market type."""
    if market_type == MARKET_LOW_CONTENT:
        return _SEEDS_LOW_CONTENT
    elif market_type == MARKET_MEDIUM_CONTENT:
        return _SEEDS_MEDIUM_CONTENT
    elif market_type == MARKET_HIGH_CONTENT:
        return _SEEDS_HIGH_CONTENT
    return _AUTOCOMPLETE_SEEDS

# Marketplace autocomplete configs
_MP_CONFIG = {
    'us': {'completion_domain': 'completion.amazon.com',     'mid': 'ATVPDKIKX0DER',  'alias': 'digital-text', 'search_domain': 'www.amazon.com'},
    'uk': {'completion_domain': 'completion.amazon.co.uk',   'mid': 'A1F83G8C2ARO7P', 'alias': 'digital-text', 'search_domain': 'www.amazon.co.uk'},
    'de': {'completion_domain': 'completion.amazon.de',      'mid': 'A1PA6795UKMFR9', 'alias': 'digital-text', 'search_domain': 'www.amazon.de'},
    'fr': {'completion_domain': 'completion.amazon.fr',      'mid': 'A13V1IB3VIYBER', 'alias': 'digital-text', 'search_domain': 'www.amazon.fr'},
    'ca': {'completion_domain': 'completion.amazon.ca',      'mid': 'A2EUQ1WTGCTBG2', 'alias': 'digital-text', 'search_domain': 'www.amazon.ca'},
    'au': {'completion_domain': 'completion.amazon.com.au',  'mid': 'ANEGB3WVEVKZB',  'alias': 'digital-text', 'search_domain': 'www.amazon.com.au'},
}

# Stop-words for clustering
_STOP = {
    'a', 'an', 'the', 'of', 'in', 'on', 'at', 'to', 'for', 'and', 'or',
    'but', 'is', 'are', 'was', 'were', 'be', 'been', 'have', 'has', 'had',
    'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'can',
    'not', 'no', 'with', 'by', 'from', 'into', 'my', 'your', 'his', 'her',
    'its', 'our', 'their', 'this', 'that', 'these', 'those', 'what', 'who',
    'how', 'when', 'where', 'why', 'all', 'each', 'every', 'both', 'few',
    'more', 'most', 'other', 'some', 'such', 'so', 'than', 'too', 'very',
    'just', 'about', 'after', 'also', 'back', 'because', 'come', 'day',
    'even', 'first', 'get', 'give', 'go', 'good', 'know', 'like', 'look',
    'make', 'new', 'now', 'one', 'only', 'over', 'say', 'she', 'take',
    'them', 'then', 'there', 'think', 'time', 'two', 'up', 'us', 'want',
    'way', 'well', 'work', 'year', 'him', 'out', 'it', 'me', 'he', 'we',
    'you', 'they', 'i', 'ii', 'iii', 'iv', 'v', 'book', 'books', 'novel',
    'edition', 'volume', 'series', 'part', 'kindle', 'paperback', 'ebook',
    'best', 'seller', 'release', 'popular', 'trending', 'unlimited',
}


# ── Phase 1: Harvest ─────────────────────────────────────────────────────

def harvest_all_sources(marketplaces=None, progress_cb=None,
                        cancel_check=None, log_cb=None,
                        custom_seeds=None, use_tiktok=True,
                        use_autocomplete=True, use_reddit=True,
                        market_type=MARKET_ALL):
    """Harvest from all enabled sources.

    Args:
        marketplaces: list of marketplace codes
        progress_cb: callable(done, total)
        cancel_check: callable() -> bool
        log_cb: callable(str)
        custom_seeds: list of custom seed phrases
        use_tiktok: whether to include TikTok/BookTok trends
        use_autocomplete: whether to run built-in autocomplete seeds
        use_reddit: whether to include Reddit demand mining
        market_type: filter seeds by market type
    """
    if not marketplaces:
        marketplaces = ['us']

    def _log(msg):
        if log_cb:
            log_cb(msg)

    def _cancelled():
        return cancel_check and cancel_check()

    seeds = _get_seeds_for_market(market_type)
    all_items = []
    total_steps = len(marketplaces) * len(seeds) + 2
    done_steps = 0

    def _tick(n=1):
        nonlocal done_steps
        done_steps += n
        if progress_cb:
            progress_cb(done_steps, total_steps)

    # ── Built-in Autocomplete harvest ────────────────────────────────
    if use_autocomplete:
        _log(f"🔤 Amazon Autocomplete: ✅ ENABLED ({len(seeds)} seeds, market={market_type})")
        for mp in marketplaces:
            if _cancelled():
                return all_items
            conf = _MP_CONFIG.get(mp, _MP_CONFIG['us'])
            _log(f"  [{mp.upper()}] Querying {len(seeds)} seeds...")

            ac_items = _harvest_autocomplete_parallel(
                seeds=seeds,
                completion_domain=conf['completion_domain'],
                mid=conf['mid'],
                alias=conf['alias'],
                marketplace=mp,
                cancel_check=cancel_check,
                log_cb=log_cb,
                tick_cb=_tick,
            )
            all_items.extend(ac_items)
            _log(f"  ✓ [{mp.upper()}] {len(ac_items)} suggestions from built-in seeds")
    else:
        _log("🔤 Amazon Autocomplete: ❌ DISABLED")

    # ── Custom Seed Autocomplete (deep expansion) ────────────────────
    if custom_seeds:
        from kdp_scout.collectors.amazon_autocomplete_harvester import harvest_from_seed
        primary_mp = marketplaces[0]
        _log(f"🔎 Custom seed harvest ({len(custom_seeds)} seeds on {primary_mp.upper()})...")
        for seed in custom_seeds:
            if _cancelled():
                break
            seed = seed.strip()
            if not seed:
                continue
            items = harvest_from_seed(
                seed=seed,
                marketplace=primary_mp,
                depth=1,
                cancel_check=cancel_check,
                log_cb=log_cb,
            )
            all_items.extend(items)
            _log(f"  ✓ Custom seed '{seed}': {len(items)} suggestions")
        _tick()

    # ── TikTok / BookTok ─────────────────────────────────────────────
    if use_tiktok and not _cancelled():
        _log("🎵 TikTok/BookTok: ✅ ENABLED — harvesting trends...")
        try:
            from kdp_scout.collectors.tiktok_booktok import (
                fetch_booktok_trends, trends_to_items
            )
            trends = fetch_booktok_trends(cancel_check=cancel_check, log_cb=log_cb)
            primary_mp = marketplaces[0] if marketplaces else 'us'
            tiktok_items = trends_to_items(trends, marketplace=primary_mp)
            all_items.extend(tiktok_items)
            _log(f"  ✓ TikTok/BookTok: {len(tiktok_items)} trending items added")
        except Exception as e:
            _log(f"  ⚠ TikTok harvest failed: {e}")
        _tick()
    elif not use_tiktok:
        _log("🎵 TikTok/BookTok: ❌ DISABLED")

    # ── Reddit demand mining ────────────────────────────────────────
    if use_reddit and not _cancelled():
        _log("🤖 Reddit Demand: ✅ ENABLED — mining book subreddits...")
        try:
            from kdp_scout.collectors.reddit_demand import (
                fetch_reddit_demand,
            )
            from kdp_scout.collectors.reddit_demand import trends_to_items as reddit_to_items
            trends = fetch_reddit_demand(cancel_check=cancel_check, log_cb=log_cb)
            primary_mp = marketplaces[0] if marketplaces else 'us'
            reddit_items = reddit_to_items(trends, marketplace=primary_mp)
            all_items.extend(reddit_items)
            _log(f"  ✓ Reddit: {len(reddit_items)} demand signals added")
        except Exception as e:
            _log(f"  ⚠ Reddit harvest failed: {e}")
        _tick()
    elif not use_reddit:
        _log("🤖 Reddit Demand: ❌ DISABLED")

    # ── Google Trends ────────────────────────────────────────────────
    if not _cancelled():
        _log("🔥 Google Trends daily trending...")
        try:
            from kdp_scout.collectors.google_trends import get_trending_searches
            trends = get_trending_searches(geo="US")
            for t in trends:
                q = t.get('query') or t.get('title', '')
                if q:
                    all_items.append({
                        'title': q, 'keyword': q,
                        '_source_type': 'google_trend',
                        '_category': 'trending',
                        '_marketplace': 'us',
                    })
            _log(f"  ✓ Google Trends: {len(trends)} items")
        except Exception as e:
            _log(f"  ⚠ Google Trends skipped: {e}")
        _tick()

    _log(f"✅ Harvest complete: {len(all_items)} raw items across {', '.join(m.upper() for m in marketplaces)}")
    return all_items


def _harvest_autocomplete_parallel(seeds, completion_domain, mid, alias,
                                   marketplace, cancel_check=None,
                                   log_cb=None, tick_cb=None):
    from kdp_scout.http_client import get_session

    url = f"https://{completion_domain}/api/2017/suggestions"
    results = []
    session = get_session()

    def _fetch_one(seed):
        if cancel_check and cancel_check():
            return []
        try:
            params = {"mid": mid, "alias": alias, "prefix": seed}
            resp = session.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                items = []
                for s in data.get("suggestions", []):
                    val = s.get("value", "").strip()
                    if val and len(val) > 3:
                        items.append({
                            'title': val, 'keyword': val,
                            '_source_type': 'autocomplete',
                            '_category': _guess_category(val),
                            '_marketplace': marketplace,
                            '_seed': seed,
                        })
                return items
        except Exception:
            pass
        return []

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(_fetch_one, seed): seed for seed in seeds}
        for future in as_completed(futures):
            if cancel_check and cancel_check():
                break
            try:
                items = future.result(timeout=10)
                results.extend(items)
            except Exception:
                pass
            if tick_cb:
                tick_cb()

    seen = set()
    deduped = []
    for item in results:
        key = item['keyword'].lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _guess_category(keyword):
    kw = keyword.lower()
    cats = {
        'romance':     ['romance', 'love', 'spicy', 'enemies to lovers', 'boyfriend',
                        'billionaire', 'harem', 'mafia', 'bully', 'hockey', 'why choose',
                        'omegaverse', 'age gap', 'forbidden', 'monster romance'],
        'thriller':    ['thriller', 'suspense', 'serial killer', 'detective', 'crime'],
        'mystery':     ['mystery', 'cozy mystery', 'whodunit'],
        'fantasy':     ['fantasy', 'dragon', 'fae', 'witch', 'magic', 'romantasy',
                        'litrpg', 'progression', 'urban fantasy'],
        'sci_fi':      ['sci fi', 'science fiction', 'space', 'dystopian', 'cyberpunk'],
        'horror':      ['horror', 'haunted', 'zombie', 'apocalypse', 'ghost', 'gothic'],
        'self_help':   ['self help', 'self improvement', 'anxiety', 'mindfulness',
                        'manifestation', 'stoicism', 'adhd', 'confidence', 'dopamine'],
        'business':    ['business', 'investing', 'trading', 'passive income', 'real estate',
                        'crypto', 'money', 'finance', 'entrepreneur', 'side hustle'],
        'health':      ['keto', 'fasting', 'diet', 'fitness', 'health', 'weight loss',
                        'gut health', 'autoimmune', 'meal prep'],
        'children':    ['children', 'kids', 'bedtime', 'picture book'],
        'low_content': ['coloring', 'activity book', 'puzzle', 'sudoku', 'word search',
                        'journal', 'planner', 'log book', 'notebook', 'dot to dot',
                        'maze', 'password book', 'recipe book'],
    }
    for cat, patterns in cats.items():
        if any(p in kw for p in patterns):
            return cat
    return 'general'


# ── Phase 1b: Deep-dive pass (Deep/Sniper) ───────────────────────────

def deep_dive_clusters(clusters, marketplace='us', top_n=15,
                       harvester_depth=1, cancel_check=None, log_cb=None):
    """Re-inject top cluster names as seeds into Amazon Autocomplete.

    This produces much more specific long-tail keywords.
    E.g. "dark romance" → "dark romance mafia forced proximity"
    """
    from kdp_scout.collectors.amazon_autocomplete_harvester import harvest_from_seed

    def _log(msg):
        if log_cb:
            log_cb(msg)

    def _cancelled():
        return cancel_check and cancel_check()

    to_expand = clusters[:top_n]
    _log(f"🔬 Deep-dive: expanding top {len(to_expand)} clusters as seeds (depth={harvester_depth})...")

    all_items = []
    done = [0]

    def _expand_one(cluster):
        if _cancelled():
            return []
        name = cluster['name']
        try:
            items = harvest_from_seed(
                seed=name,
                marketplace=marketplace,
                depth=harvester_depth,
                cancel_check=cancel_check,
                log_cb=None,  # quiet — we log summary
            )
            # Tag as deep-dive source
            for item in items:
                item['_source_type'] = 'autocomplete_deep'
                item['_deep_seed'] = name
                item['_pass'] = 2
            return items
        except Exception as e:
            logger.debug(f"Deep-dive failed for '{name}': {e}")
            return []

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_expand_one, c): c for c in to_expand}
        for future in as_completed(futures):
            if _cancelled():
                break
            try:
                items = future.result(timeout=30)
                all_items.extend(items)
                done[0] += 1
                cluster = futures[future]
                if items:
                    _log(f"  [{done[0]}/{len(to_expand)}] '{cluster['name']}' → {len(items)} long-tail keywords")
            except Exception:
                done[0] += 1

    _log(f"  ✓ Deep-dive produced {len(all_items)} additional keywords")
    return all_items


def sniper_micro_expand(clusters, marketplace='us', top_n=10,
                        cancel_check=None, log_cb=None):
    """3rd pass: ultra-deep expansion on micro-niches (Sniper mode).

    Uses depth=2 harvester for even more specific long-tails.
    """
    from kdp_scout.collectors.amazon_autocomplete_harvester import harvest_from_seed

    def _log(msg):
        if log_cb:
            log_cb(msg)

    def _cancelled():
        return cancel_check and cancel_check()

    to_expand = clusters[:top_n]
    _log(f"🎯 Sniper pass: ultra-deep on top {len(to_expand)} micro-niches...")

    all_items = []

    def _expand_one(cluster):
        if _cancelled():
            return []
        name = cluster['name']
        try:
            items = harvest_from_seed(
                seed=name,
                marketplace=marketplace,
                depth=2,  # depth 2 = expand suggestions too
                cancel_check=cancel_check,
                log_cb=None,
            )
            for item in items:
                item['_source_type'] = 'autocomplete_sniper'
                item['_deep_seed'] = name
                item['_pass'] = 3
            return items
        except Exception as e:
            logger.debug(f"Sniper expand failed for '{name}': {e}")
            return []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_expand_one, c): c for c in to_expand}
        done = [0]
        for future in as_completed(futures):
            if _cancelled():
                break
            try:
                items = future.result(timeout=60)
                all_items.extend(items)
                done[0] += 1
                cluster = futures[future]
                if items:
                    _log(f"  [{done[0]}/{len(to_expand)}] '{cluster['name']}' → {len(items)} ultra-specific keywords")
            except Exception:
                done[0] += 1

    _log(f"  ✓ Sniper pass produced {len(all_items)} ultra-specific keywords")
    return all_items


# ── Phase 2: Cluster ─────────────────────────────────────────────────────

def cluster_books(books, min_cluster_size=2, max_clusters=30, log_cb=None):
    def _log(msg):
        if log_cb:
            log_cb(msg)

    phrase_to_books = defaultdict(list)
    for book in books:
        title = book.get('title') or book.get('keyword') or ''
        for phrase in _extract_cluster_phrases(title):
            phrase_to_books[phrase].append(book)

    scored = []
    for phrase, bks in phrase_to_books.items():
        if len(bks) < min_cluster_size:
            continue

        sources = Counter(b.get('_source_type', 'unknown') for b in bks)
        categories = list(set(b.get('_category', '') for b in bks if b.get('_category')))
        marketplaces = list(set(b.get('_marketplace', 'us') for b in bks if b.get('_marketplace')))
        seeds = list(set(b.get('_seed', '') for b in bks if b.get('_seed')))

        source_weights = {
            'movers': 3.0, 'new_release': 2.5, 'wished': 2.0,
            'bestseller_kw': 1.5, 'autocomplete': 1.8, 'google_trend': 1.2,
            'reddit_demand': 2.2, 'tiktok_booktok': 2.0,
            'autocomplete_custom': 2.5,
            'autocomplete_deep': 2.8,    # deep-dive gets higher weight
            'autocomplete_sniper': 3.2,  # sniper even higher
        }
        weighted_size = sum(
            source_weights.get(b.get('_source_type', ''), 1.0) for b in bks
        )
        source_diversity = len(sources)
        mp_diversity = len(marketplaces)

        multi_score = (weighted_size
                       * (1 + 0.3 * source_diversity)
                       * (1 + 0.25 * (mp_diversity - 1)))

        # Source-specific signals
        tiktok_books = [b for b in bks if b.get('_source_type') == 'tiktok_booktok']
        reddit_books = [b for b in bks if b.get('_source_type') == 'reddit_demand']
        custom_books = [b for b in bks if b.get('_source_type') == 'autocomplete_custom']
        deep_books = [b for b in bks if b.get('_source_type') in ('autocomplete_deep', 'autocomplete_sniper')]

        has_tiktok = len(tiktok_books) > 0
        has_reddit = len(reddit_books) > 0
        has_custom_seed = len(custom_books) > 0
        has_deep = len(deep_books) > 0

        tiktok_max_views = max((b.get('_views', 0) for b in tiktok_books), default=0)
        reddit_max_score = max((b.get('_reddit_score', 0) for b in reddit_books), default=0)
        custom_seed_names = list(set(b.get('_seed', '') for b in custom_books if b.get('_seed')))
        deep_seed_names = list(set(b.get('_deep_seed', '') for b in deep_books if b.get('_deep_seed')))

        # Determine pass level (which pass produced this cluster)
        max_pass = max((b.get('_pass', 1) for b in bks), default=1)

        if has_custom_seed:
            multi_score *= 1.5
        if has_deep:
            multi_score *= 1.3  # deep-dive clusters are more specific = bonus

        scored.append({
            'name': phrase,
            'keywords': _expand_cluster_keywords(phrase, bks),
            'books': bks,
            'categories': categories,
            'marketplaces': marketplaces,
            'seeds': seeds[:8],
            'sources': dict(sources),
            'size': len(bks),
            'multi_source_score': round(multi_score, 1),
            'source_count': len(sources),
            'has_tiktok': has_tiktok,
            'tiktok_max_views': tiktok_max_views,
            'has_reddit': has_reddit,
            'reddit_max_score': reddit_max_score,
            'has_custom_seed': has_custom_seed,
            'custom_seed_names': custom_seed_names,
            'has_deep': has_deep,
            'deep_seed_names': deep_seed_names,
            'pass_level': max_pass,
        })

    scored.sort(key=lambda c: c['multi_source_score'], reverse=True)

    # Dedup overlapping clusters
    final = []
    used_books = set()
    for cluster in scored:
        book_ids = {id(b) for b in cluster['books']}
        overlap = len(book_ids & used_books) / max(len(book_ids), 1)
        if overlap < 0.5:
            final.append(cluster)
            used_books |= book_ids
        if len(final) >= max_clusters:
            break

    _log(f"📊 Clustered into {len(final)} niches (from {len(scored)} raw clusters)")
    return final


# ── Phase 3: Score ───────────────────────────────────────────────────────

def score_clusters(clusters, marketplaces=None, max_probe=20,
                   progress_cb=None, cancel_check=None, log_cb=None):
    from kdp_scout.collectors.amazon_search import probe_competition
    from kdp_scout.collectors.bsr_model import (
        estimate_total_monthly_revenue, opportunity_score,
    )

    if not marketplaces:
        marketplaces = ['us']
    primary_mp = marketplaces[0]

    def _log(msg):
        if log_cb:
            log_cb(msg)

    def _cancelled():
        return cancel_check and cancel_check()

    to_probe = clusters[:max_probe]
    total = len(to_probe)
    done = [0]

    def _probe_one(cluster):
        if _cancelled():
            return cluster
        kw = cluster['name']
        try:
            probe = probe_competition(kw, marketplace=primary_mp, top_n=10)
            cluster['competition_count'] = probe.get('competition_count')
            cluster['avg_bsr'] = probe.get('avg_bsr_top10')
            cluster['median_reviews'] = probe.get('median_reviews')
            cluster['ku_ratio'] = probe.get('ku_ratio', 0)
            cluster['top_results'] = probe.get('top10_results', [])

            top_books = []
            prices = []
            review_counts = []
            for r in cluster['top_results'][:12]:
                title = r.get('title', '')[:80]
                asin = r.get('asin', '')
                price = r.get('price_kindle') or r.get('price') or 0
                reviews = r.get('review_count') or r.get('reviews') or 0
                rating = r.get('avg_rating') or r.get('rating') or 0
                bsr = r.get('bsr') or 0
                if price > 0:
                    prices.append(price)
                if reviews > 0:
                    review_counts.append(reviews)
                top_books.append({
                    'title': title, 'asin': asin,
                    'price': price, 'reviews': reviews,
                    'rating': round(rating, 1) if rating else 0,
                    'bsr': bsr,
                })
            cluster['top_books'] = top_books

            if prices:
                cluster['price_min'] = round(min(prices), 2)
                cluster['price_max'] = round(max(prices), 2)
                cluster['price_avg'] = round(statistics.mean(prices), 2)
            else:
                cluster['price_min'] = None
                cluster['price_max'] = None
                cluster['price_avg'] = 4.99

            if review_counts:
                cluster['reviews_min'] = min(review_counts)
                cluster['reviews_max'] = max(review_counts)
                cluster['reviews_avg'] = round(statistics.mean(review_counts))
            else:
                cluster['reviews_min'] = None
                cluster['reviews_max'] = None
                cluster['reviews_avg'] = None

            avg_price = cluster['price_avg'] or 4.99
            if cluster['avg_bsr']:
                rev = estimate_total_monthly_revenue(
                    cluster['avg_bsr'], avg_price,
                    ku_eligible=cluster['ku_ratio'] > 0.3,
                )
                cluster['est_revenue'] = rev['total']
                cluster['daily_sales'] = rev.get('daily_sales', 0)
            else:
                cluster['est_revenue'] = 0
                cluster['daily_sales'] = 0

            cluster['opportunity'] = opportunity_score(
                cluster.get('competition_count'),
                cluster.get('avg_bsr'),
                avg_price,
                median_reviews=cluster.get('median_reviews'),
                ku_ratio=cluster.get('ku_ratio', 0),
                organic_count=len(cluster.get('top_results', [])),
            )
        except Exception as e:
            cluster['competition_count'] = None
            cluster['avg_bsr'] = None
            cluster['median_reviews'] = None
            cluster['ku_ratio'] = 0
            cluster['est_revenue'] = 0
            cluster['daily_sales'] = 0
            cluster['opportunity'] = 0
            cluster['top_results'] = []
            cluster['top_books'] = []
            cluster['price_min'] = None
            cluster['price_max'] = None
            cluster['price_avg'] = None
            cluster['reviews_min'] = None
            cluster['reviews_max'] = None
            cluster['reviews_avg'] = None
            logger.error(f"Probe failed for '{kw}': {e}")
            _log(f"  ⚠ Probe failed for '{kw}': {e}")

        done[0] += 1
        return cluster

    _log(f"🔍 Probing {total} niches on {primary_mp.upper()} (4 threads)...")

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_probe_one, c): i for i, c in enumerate(to_probe)}
        for future in as_completed(futures):
            if _cancelled():
                break
            try:
                c = future.result(timeout=30)
                idx = done[0]
                _log(f"  [{idx}/{total}] {c['name']} → "
                     f"comp={c.get('competition_count', '?')} | "
                     f"BSR={c.get('avg_bsr', '?')} | "
                     f"${c.get('est_revenue', 0):,.0f}/mo | "
                     f"opp={c.get('opportunity', 0):.0f}")
                if progress_cb:
                    progress_cb(idx, total)
            except Exception:
                pass

    if progress_cb:
        progress_cb(total, total)

    for c in to_probe:
        c['recommendations'] = _generate_recommendations(c)

    _classify_clusters(to_probe, log_cb=log_cb)

    # Compute GO score (composite 0-100) and sort by it
    _compute_go_scores(to_probe)
    to_probe.sort(key=lambda c: c.get('go_score', 0), reverse=True)

    return to_probe


# ── Phase 4: Classify ────────────────────────────────────────────────────

def _classify_clusters(clusters, log_cb=None):
    """Assign classification using all available signals."""
    def _log(msg):
        if log_cb:
            log_cb(msg)

    if not clusters:
        return

    opps = [c.get('opportunity', 0) for c in clusters if c.get('opportunity', 0) > 0]
    revs = [c.get('est_revenue', 0) for c in clusters if c.get('est_revenue', 0) > 0]
    multis = [c.get('multi_source_score', 0) for c in clusters if c.get('multi_source_score', 0) > 0]
    comps = [c.get('competition_count', 0) for c in clusters if c.get('competition_count') and c['competition_count'] > 0]

    opp_p50 = _percentile(opps, 50) if opps else 0
    opp_p75 = _percentile(opps, 75) if opps else 0
    multi_p50 = _percentile(multis, 50) if multis else 0
    multi_p75 = _percentile(multis, 75) if multis else 0

    for c in clusters:
        opp = c.get('opportunity', 0)
        comp = c.get('competition_count')
        reviews = c.get('median_reviews')
        revenue = c.get('est_revenue', 0)
        multi = c.get('multi_source_score', 0)
        size = c.get('size', 0)

        # Compute niche_score
        ns = opp * 0.4
        if multis:
            max_multi = max(multis) if multis else 1
            ns += (multi / max(max_multi, 1)) * 20
        elif multi > 0:
            ns += min(multi * 3, 20)
        ns += min(size * 1.5, 10)

        if comp is not None and comp > 0:
            if comp < 2000:
                ns += 15
            elif comp < 5000:
                ns += 12
            elif comp < 15000:
                ns += 8
            elif comp < 50000:
                ns += 4
            elif comp > 100000:
                ns -= 5
        if reviews is not None:
            if reviews < 15:
                ns += 10
            elif reviews < 50:
                ns += 6
            elif reviews < 100:
                ns += 3
            elif reviews > 500:
                ns -= 5
        if revenue > 0:
            ns += min(revenue / 100, 5)

        c['_niche_score'] = round(ns, 1)

    scores = sorted([c['_niche_score'] for c in clusters])
    ns_p25 = _percentile(scores, 25) if scores else 0
    ns_p50 = _percentile(scores, 50) if scores else 0
    ns_p75 = _percentile(scores, 75) if scores else 0

    hot_count = gem_count = avoid_count = rising_count = 0

    for c in clusters:
        ns = c['_niche_score']
        comp = c.get('competition_count')
        reviews = c.get('median_reviews')
        multi = c.get('multi_source_score', 0)
        size = c.get('size', 0)
        opp = c.get('opportunity', 0)
        has_tiktok = c.get('has_tiktok', False)
        tiktok_views = c.get('tiktok_max_views', 0)
        has_reddit = c.get('has_reddit', False)
        reddit_score = c.get('reddit_max_score', 0)
        has_custom_seed = c.get('has_custom_seed', False)
        has_deep = c.get('has_deep', False)
        source_count = c.get('source_count', 1)

        # ── SOURCE-SPECIFIC OVERRIDES ────────────────────────────────
        if has_custom_seed and ns >= ns_p25:
            if ns >= ns_p75:
                c['classification'] = 'hot'
                c['badge'] = '🔥 Hot Niche'
                c['_override_reason'] = 'custom_seed_hot'
                hot_count += 1
            elif ns >= ns_p50:
                c['classification'] = 'gem'
                c['badge'] = '💎 Hidden Gem'
                c['_override_reason'] = 'custom_seed_gem'
                gem_count += 1
            else:
                c['classification'] = 'rising'
                c['badge'] = '📈 Rising'
                c['_override_reason'] = 'custom_seed_rising'
                rising_count += 1
            continue

        if source_count >= 3 and (has_tiktok or has_reddit):
            c['classification'] = 'hot'
            c['badge'] = '🔥 Hot Niche'
            c['_override_reason'] = 'cross_source_3'
            hot_count += 1
            continue

        if has_tiktok and tiktok_views > 200_000_000:
            c['classification'] = 'hot'
            c['badge'] = '🔥 Hot Niche'
            c['_override_reason'] = 'tiktok_viral'
            hot_count += 1
            continue

        if has_reddit and reddit_score > 60 and (comp is None or comp < 50_000):
            c['classification'] = 'gem'
            c['badge'] = '💎 Hidden Gem'
            c['_override_reason'] = 'reddit_demand'
            gem_count += 1
            continue

        if has_tiktok and ns >= ns_p50:
            c['classification'] = 'rising'
            c['badge'] = '📈 Rising'
            c['_override_reason'] = 'tiktok_confirmed'
            rising_count += 1
            continue

        # Deep-dive cluster with good score → likely a specific gem
        if has_deep and ns >= ns_p50 and (comp is None or comp < 30_000):
            c['classification'] = 'gem'
            c['badge'] = '💎 Hidden Gem'
            c['_override_reason'] = 'deep_dive_gem'
            gem_count += 1
            continue

        # ── PERCENTILE-BASED CLASSIFICATION ──────────────────────────
        is_saturated = False
        if comp is not None and comp > 50000:
            is_saturated = True
        if reviews is not None and reviews > 300:
            is_saturated = True
        if ns <= ns_p25 and opp <= 10 and size <= 3:
            is_saturated = True

        if ns <= ns_p25 and is_saturated:
            c['classification'] = 'avoid'
            c['badge'] = '⚠️ Saturated'
            avoid_count += 1
        elif ns >= ns_p75 and ns > 20:
            c['classification'] = 'hot'
            c['badge'] = '🔥 Hot Niche'
            hot_count += 1
        elif ns >= ns_p50 * 0.6 and (
            (comp is not None and comp < 20000) or
            (reviews is not None and reviews < 80) or
            (comp is None)
        ):
            c['classification'] = 'gem'
            c['badge'] = '💎 Hidden Gem'
            gem_count += 1
        elif multi >= max(multi_p75, 3) or size >= 8:
            c['classification'] = 'rising'
            c['badge'] = '📈 Rising'
            rising_count += 1
        elif ns <= ns_p25 * 0.8 and opp <= 15:
            c['classification'] = 'avoid'
            c['badge'] = '⚠️ Saturated'
            avoid_count += 1
        else:
            c['classification'] = 'moderate'
            c['badge'] = '➡️ Moderate'

    _log(f"📊 Classification: {hot_count}🔥 Hot | {gem_count}💎 Gem | "
         f"{rising_count}📈 Rising | {avoid_count}⚠️ Avoid | "
         f"{len(clusters) - hot_count - gem_count - rising_count - avoid_count}➡️ Moderate")


# ── GO Score (composite 0-100) ───────────────────────────────────────────

def _compute_go_scores(clusters):
    """Compute a composite GO score (0-100) for each cluster.

    Formula weights:
        Opportunity (0-100)     × 0.30
        Multi-source signal     × 0.20
        Low competition bonus   × 0.15
        Low review barrier      × 0.10
        Revenue potential       × 0.10
        Social signals          × 0.10
        Cluster specificity     × 0.05
    """
    if not clusters:
        return

    max_multi = max((c.get('multi_source_score', 0) for c in clusters), default=1) or 1
    max_rev = max((c.get('est_revenue', 0) for c in clusters), default=1) or 1

    for c in clusters:
        opp = min(c.get('opportunity', 0), 100)
        multi = c.get('multi_source_score', 0)
        comp = c.get('competition_count')
        reviews = c.get('median_reviews')
        revenue = c.get('est_revenue', 0)
        has_tiktok = c.get('has_tiktok', False)
        has_reddit = c.get('has_reddit', False)
        has_deep = c.get('has_deep', False)
        pass_level = c.get('pass_level', 1)

        # 1. Opportunity (30%)
        s_opp = opp * 0.30

        # 2. Multi-source (20%)
        s_multi = (multi / max_multi) * 100 * 0.20

        # 3. Low competition (15%)
        if comp is None:
            s_comp = 50 * 0.15  # unknown = neutral
        elif comp < 2000:
            s_comp = 100 * 0.15
        elif comp < 5000:
            s_comp = 85 * 0.15
        elif comp < 15000:
            s_comp = 60 * 0.15
        elif comp < 50000:
            s_comp = 30 * 0.15
        else:
            s_comp = 5 * 0.15

        # 4. Low review barrier (10%)
        if reviews is None:
            s_rev = 50 * 0.10
        elif reviews < 15:
            s_rev = 100 * 0.10
        elif reviews < 50:
            s_rev = 75 * 0.10
        elif reviews < 100:
            s_rev = 50 * 0.10
        elif reviews < 300:
            s_rev = 25 * 0.10
        else:
            s_rev = 5 * 0.10

        # 5. Revenue (10%)
        s_revenue = min((revenue / max_rev) * 100, 100) * 0.10

        # 6. Social signals (10%)
        social = 0
        if has_tiktok:
            social += 40
        if has_reddit:
            social += 40
        if c.get('source_count', 1) >= 3:
            social += 20
        s_social = min(social, 100) * 0.10

        # 7. Specificity bonus (5%) — deeper passes = more specific
        specificity = 0
        if pass_level >= 3:
            specificity = 100
        elif pass_level >= 2:
            specificity = 60
        elif has_deep:
            specificity = 40
        s_spec = specificity * 0.05

        go = round(s_opp + s_multi + s_comp + s_rev + s_revenue + s_social + s_spec, 1)
        c['go_score'] = min(go, 100)

        # GO verdict
        if go >= 70:
            c['go_verdict'] = 'GO'
            c['go_emoji'] = '🟢'
        elif go >= 45:
            c['go_verdict'] = 'MAYBE'
            c['go_emoji'] = '🟡'
        else:
            c['go_verdict'] = 'PASS'
            c['go_emoji'] = '🔴'


# ── Recommendations ──────────────────────────────────────────────────────

def _generate_recommendations(cluster):
    recs = []
    comp = cluster.get('competition_count')
    reviews = cluster.get('median_reviews')
    ku = cluster.get('ku_ratio', 0)
    price_avg = cluster.get('price_avg')
    opp = cluster.get('opportunity', 0)
    has_deep = cluster.get('has_deep', False)
    pass_level = cluster.get('pass_level', 1)

    # Price strategy
    if price_avg:
        if price_avg < 3.99:
            recs.append(f"💲 Low avg price (${price_avg:.2f}) — consider $2.99-$3.99 to hit 70% royalty")
        elif price_avg > 7.99:
            recs.append(f"💲 Premium niche (avg ${price_avg:.2f}) — room for value-priced entry at $4.99-$6.99")
        else:
            recs.append(f"💲 Sweet spot pricing (avg ${price_avg:.2f}) — match or slightly undercut at ${max(2.99, price_avg - 1):.2f}")

    # KU strategy
    if ku > 0.5:
        recs.append("📚 High KU saturation — enroll in KU, readers expect it here")
    elif ku > 0:
        recs.append("📚 Mixed KU presence — consider KU enrollment for visibility boost")
    else:
        recs.append("📚 Low KU — wide distribution could be more profitable")

    # Competition insight
    if comp is not None:
        if comp < 5000:
            recs.append(f"🎯 Very low competition ({comp:,} results) — fast ranking possible")
        elif comp < 20000:
            recs.append(f"🎯 Moderate competition ({comp:,}) — good with solid keywords + cover")
        elif comp < 50000:
            recs.append(f"🎯 Competitive ({comp:,}) — need strong differentiation")
        else:
            recs.append(f"🎯 Highly competitive ({comp:,}) — target long-tail sub-niches")

    # Review gap
    if reviews is not None:
        if reviews < 20:
            recs.append("⭐ Very few reviews on top books — new entrants can compete quickly")
        elif reviews < 100:
            recs.append("⭐ Moderate reviews — aim for 15-20 reviews in first month via ARC")
        else:
            recs.append("⭐ Well-reviewed competition — focus on unique angle / series")

    # Content strategy
    cats = cluster.get('categories', [])
    if 'low_content' in cats:
        recs.append("📖 Low-content niche — fast production, aim for 5-10 variations")
    elif 'romance' in cats or 'fantasy' in cats or 'thriller' in cats:
        recs.append("📖 Fiction — consider series (3+ books) for read-through revenue")
    elif 'self_help' in cats or 'business' in cats or 'health' in cats:
        recs.append("📖 Non-fiction — 25K-40K words, strong subtitle with keywords")

    # Deep-dive specificity note
    if pass_level >= 3:
        recs.append("🎯 Ultra-specific niche (Sniper pass) — high precision, low competition likely")
    elif pass_level >= 2:
        recs.append("🔬 Deep-dive niche — more specific than surface-level discovery")

    return recs


# ── Export helpers ────────────────────────────────────────────────────────

def export_clusters_csv(clusters):
    """Export clusters as CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Rank', 'GO Score', 'Verdict', 'Niche', 'Classification',
        'Competition', 'Avg BSR', 'Med Reviews', 'KU %',
        'Est Revenue/mo', 'Daily Sales', 'Opportunity',
        'Price Range', 'Keywords', 'Sources', 'Categories',
        'Recommendations',
    ])
    for i, c in enumerate(clusters):
        pmin = c.get('price_min')
        pmax = c.get('price_max')
        if pmin is not None and pmax is not None:
            price_str = f"${pmin:.2f}-${pmax:.2f}"
        elif c.get('price_avg'):
            price_str = f"~${c['price_avg']:.2f}"
        else:
            price_str = ""
        writer.writerow([
            i + 1,
            c.get('go_score', 0),
            c.get('go_verdict', ''),
            c.get('name', '').title(),
            c.get('classification', ''),
            c.get('competition_count', ''),
            c.get('avg_bsr', ''),
            c.get('median_reviews', ''),
            f"{c.get('ku_ratio', 0)*100:.0f}%",
            f"${c.get('est_revenue', 0):,.0f}",
            f"{c.get('daily_sales', 0):.1f}",
            c.get('opportunity', 0),
            price_str,
            ' | '.join(c.get('keywords', [])[:5]),
            ', '.join(c.get('sources', {}).keys()),
            ', '.join(c.get('categories', [])),
            ' | '.join(c.get('recommendations', [])[:3]),
        ])
    return output.getvalue()


# ── Helpers ──────────────────────────────────────────────────────────────

def _percentile(data, pct):
    if not data:
        return 0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * pct / 100)
    idx = min(idx, len(sorted_data) - 1)
    return sorted_data[idx]


def _extract_cluster_phrases(title):
    title = title.lower().strip()
    title = re.sub(r'[^a-z0-9\s]', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip()
    words = [w for w in title.split() if w not in _STOP and len(w) > 2]

    phrases = []
    if len(words) >= 2:
        for i in range(len(words) - 1):
            phrases.append(f"{words[i]} {words[i+1]}")
    if len(words) >= 3:
        for i in range(len(words) - 2):
            phrases.append(f"{words[i]} {words[i+1]} {words[i+2]}")
    for w in words:
        if len(w) >= 5:
            phrases.append(w)
    return phrases


def _expand_cluster_keywords(main_phrase, books):
    all_phrases = Counter()
    for book in books:
        title = book.get('title') or book.get('keyword') or ''
        for phrase in _extract_cluster_phrases(title):
            if phrase != main_phrase:
                all_phrases[phrase] += 1
    top = [p for p, c in all_phrases.most_common(8) if c >= 2]
    return [main_phrase] + top

"""Amazon Autocomplete Harvester.

Given a seed phrase like "coloring book for", expands it with every
letter a-z and 0-9 to harvest real Amazon search suggestions.

Depth 1 (default): seed + single character → ~36 API calls per seed
Depth 2: also expands each suggestion → deeper coverage

Returns harvest items compatible with discovery pipeline.
"""

import logging
import time
import string
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Marketplace autocomplete configs
_MP_CONFIG = {
    'us': {'completion_domain': 'completion.amazon.com',    'mid': 'ATVPDKIKX0DER',  'alias': 'digital-text'},
    'uk': {'completion_domain': 'completion.amazon.co.uk',  'mid': 'A1F83G8C2ARO7P', 'alias': 'digital-text'},
    'de': {'completion_domain': 'completion.amazon.de',     'mid': 'A1PA6795UKMFR9', 'alias': 'digital-text'},
    'fr': {'completion_domain': 'completion.amazon.fr',     'mid': 'A13V1IB3VIYBER', 'alias': 'digital-text'},
    'ca': {'completion_domain': 'completion.amazon.ca',     'mid': 'A2EUQ1WTGCTBG2', 'alias': 'digital-text'},
    'au': {'completion_domain': 'completion.amazon.com.au', 'mid': 'ANEGB3WVEVKZB',  'alias': 'digital-text'},
}

_EXPAND_CHARS = list(string.ascii_lowercase) + list('0123456789')


def harvest_from_seed(seed, marketplace='us', depth=1,
                      cancel_check=None, log_cb=None, progress_cb=None):
    """Expand a seed using Amazon autocomplete.

    Args:
        seed: e.g. "coloring book for"
        marketplace: marketplace code
        depth: 1 = seed+char, 2 = also expand top suggestions
        cancel_check: callable returning bool
        log_cb: callable(str) for log messages
        progress_cb: callable(done, total)

    Returns:
        list of harvest items (dicts compatible with discovery pipeline)
    """
    from kdp_scout.http_client import get_session

    def _log(msg):
        if log_cb:
            log_cb(msg)

    def _cancelled():
        return cancel_check and cancel_check()

    conf = _MP_CONFIG.get(marketplace, _MP_CONFIG['us'])
    session = get_session()
    url = f"https://{conf['completion_domain']}/api/2017/suggestions"

    _log(f"🔎 Autocomplete harvest: '{seed}' on {marketplace.upper()} (depth={depth})")

    # Build prefix list for depth 1
    prefixes_d1 = [f"{seed} {c}" for c in _EXPAND_CHARS] + [seed]

    results_raw = []
    done = [0]
    total = len(prefixes_d1)

    def _fetch(prefix):
        if _cancelled():
            return []
        try:
            resp = session.get(url, params={
                'mid': conf['mid'],
                'alias': conf['alias'],
                'prefix': prefix,
            }, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                items = []
                for s in data.get('suggestions', []):
                    val = s.get('value', '').strip()
                    if val and len(val) > 3:
                        items.append(val)
                return items
        except Exception:
            pass
        return []

    # Depth 1
    with ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(_fetch, p): p for p in prefixes_d1}
        for future in as_completed(futures):
            if _cancelled():
                break
            try:
                items = future.result(timeout=10)
                results_raw.extend(items)
            except Exception:
                pass
            done[0] += 1
            if progress_cb:
                progress_cb(done[0], total * (2 if depth >= 2 else 1))

    # Depth 2: expand top unique suggestions
    if depth >= 2 and not _cancelled():
        seen_d1 = list(dict.fromkeys(results_raw))[:20]
        prefixes_d2 = [f"{s} {c}" for s in seen_d1[:10] for c in _EXPAND_CHARS[:10]]
        total_d2 = len(prefixes_d2)

        _log(f"  Depth-2: expanding {len(seen_d1[:10])} suggestions × 10 chars...")

        with ThreadPoolExecutor(max_workers=12) as ex:
            futures2 = {ex.submit(_fetch, p): p for p in prefixes_d2}
            for future in as_completed(futures2):
                if _cancelled():
                    break
                try:
                    items = future.result(timeout=10)
                    results_raw.extend(items)
                except Exception:
                    pass
                done[0] += 1
                if progress_cb:
                    progress_cb(done[0], total + total_d2)

    # Deduplicate
    seen = set()
    deduped = []
    for kw in results_raw:
        key = kw.lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(kw)

    _log(f"  ✓ '{seed}': {len(deduped)} unique suggestions")

    return [
        {
            'title': kw,
            'keyword': kw,
            '_source_type': 'autocomplete_custom',
            '_category': _guess_category(kw),
            '_marketplace': marketplace,
            '_seed': seed,
        }
        for kw in deduped
    ]


def _guess_category(keyword):
    kw = keyword.lower()
    cats = {
        'romance':     ['romance', 'love', 'spicy', 'billionaire', 'harem', 'mafia',
                        'bully', 'hockey', 'why choose', 'omegaverse', 'age gap',
                        'forbidden', 'monster romance', 'enemies to lovers'],
        'fantasy':     ['fantasy', 'dragon', 'fae', 'witch', 'magic', 'romantasy',
                        'litrpg', 'progression', 'urban fantasy'],
        'thriller':    ['thriller', 'suspense', 'serial killer', 'detective', 'crime'],
        'mystery':     ['mystery', 'cozy mystery', 'whodunit'],
        'self_help':   ['self help', 'self improvement', 'anxiety', 'mindfulness',
                        'manifestation', 'stoicism', 'adhd', 'dopamine'],
        'business':    ['business', 'investing', 'trading', 'passive income', 'real estate',
                        'crypto', 'money', 'finance', 'side hustle'],
        'health':      ['keto', 'fasting', 'diet', 'fitness', 'health', 'weight loss',
                        'gut health', 'autoimmune', 'meal prep'],
        'low_content': ['coloring', 'activity book', 'puzzle', 'sudoku', 'word search',
                        'journal', 'planner', 'log book', 'notebook', 'dot to dot',
                        'maze', 'password book', 'recipe book'],
    }
    for cat, patterns in cats.items():
        if any(p in kw for p in patterns):
            return cat
    return 'general'

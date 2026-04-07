"""Trending keyword discovery for Amazon KDP.

Discovers trending/hot keywords without needing a seed phrase by:
1. Scraping Amazon Kindle bestseller pages
2. Scraping Amazon Movers & Shakers (fastest BSR climbers — updated hourly)
3. Scraping Amazon Most Wished For (demand signal: books on wishlists)
4. Scraping Amazon Hot New Releases (new books gaining traction)
5. Scraping Also Bought / Also Viewed for a given ASIN (related niches)
6. Using Google suggest with book-related query patterns
7. Mining a curated list of major KDP categories via autocomplete

New in this version:
- Movers & Shakers scraper (hourly updates, strongest trending signal)
- Most Wished For scraper (latent demand signal)
- Also Bought / Also Viewed from a product page
- Multi-page bestseller scraping (top 100 not just top 20)
- Multi-marketplace trending via Google Trends proxy
"""

import logging
import re
import string

from bs4 import BeautifulSoup

from kdp_scout.http_client import fetch, get_browser_headers
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config

logger = logging.getLogger(__name__)

_ALPHABET = string.ascii_lowercase

# Amazon list pages — all return HTML with consistent structure
BESTSELLER_URLS = {
    'kindle': 'https://www.amazon.com/gp/bestsellers/digital-text/',
    'kindle_free': 'https://www.amazon.com/gp/bestsellers/digital-text/154606011/',
    'kindle_new': 'https://www.amazon.com/gp/new-releases/digital-text/',
    'kindle_movers': 'https://www.amazon.com/gp/movers-and-shakers/digital-text/',
    'kindle_wished': 'https://www.amazon.com/gp/most-wished-for/digital-text/',
    'kindle_gifted': 'https://www.amazon.com/gp/most-gifted/digital-text/',
    # Books (physical)
    'books': 'https://www.amazon.com/gp/bestsellers/books/',
    'books_new': 'https://www.amazon.com/gp/new-releases/books/',
    'books_movers': 'https://www.amazon.com/gp/movers-and-shakers/books/',
    'books_wished': 'https://www.amazon.com/gp/most-wished-for/books/',
}

# Category-specific Movers & Shakers for deep-dive trending
CATEGORY_MOVERS_URLS = {
    'romance':           'https://www.amazon.com/gp/movers-and-shakers/digital-text/158566011/',
    'mystery_thriller':  'https://www.amazon.com/gp/movers-and-shakers/digital-text/157305011/',
    'sci_fi':            'https://www.amazon.com/gp/movers-and-shakers/digital-text/158591011/',
    'fantasy':           'https://www.amazon.com/gp/movers-and-shakers/digital-text/158576011/',
    'self_help':         'https://www.amazon.com/gp/movers-and-shakers/digital-text/156563011/',
    'business':          'https://www.amazon.com/gp/movers-and-shakers/digital-text/154821011/',
    'young_adult':       'https://www.amazon.com/gp/movers-and-shakers/digital-text/3511261011/',
    'children':          'https://www.amazon.com/gp/movers-and-shakers/digital-text/155009011/',
    'horror':            'https://www.amazon.com/gp/movers-and-shakers/digital-text/157060011/',
    'literary_fiction':  'https://www.amazon.com/gp/movers-and-shakers/digital-text/157028011/',
    'biographies':       'https://www.amazon.com/gp/movers-and-shakers/digital-text/154754011/',
    'true_crime':        'https://www.amazon.com/gp/movers-and-shakers/digital-text/157554011/',
    'cookbooks':         'https://www.amazon.com/gp/movers-and-shakers/digital-text/156154011/',
    'health_fitness':    'https://www.amazon.com/gp/movers-and-shakers/digital-text/156430011/',
}

# Category-specific Hot New Releases
CATEGORY_HNR_URLS = {
    'romance':           'https://www.amazon.com/gp/new-releases/digital-text/158566011/',
    'mystery_thriller':  'https://www.amazon.com/gp/new-releases/digital-text/157305011/',
    'sci_fi':            'https://www.amazon.com/gp/new-releases/digital-text/158591011/',
    'fantasy':           'https://www.amazon.com/gp/new-releases/digital-text/158576011/',
    'self_help':         'https://www.amazon.com/gp/new-releases/digital-text/156563011/',
    'business':          'https://www.amazon.com/gp/new-releases/digital-text/154821011/',
    'young_adult':       'https://www.amazon.com/gp/new-releases/digital-text/3511261011/',
    'children':          'https://www.amazon.com/gp/new-releases/digital-text/155009011/',
    'horror':            'https://www.amazon.com/gp/new-releases/digital-text/157060011/',
    'literary_fiction':  'https://www.amazon.com/gp/new-releases/digital-text/157028011/',
    'biographies':       'https://www.amazon.com/gp/new-releases/digital-text/154754011/',
    'true_crime':        'https://www.amazon.com/gp/new-releases/digital-text/157554011/',
    'cookbooks':         'https://www.amazon.com/gp/new-releases/digital-text/156154011/',
    'health_fitness':    'https://www.amazon.com/gp/new-releases/digital-text/156430011/',
}

# Category-specific Most Wished For
CATEGORY_WISHED_URLS = {
    'romance':           'https://www.amazon.com/gp/most-wished-for/digital-text/158566011/',
    'mystery_thriller':  'https://www.amazon.com/gp/most-wished-for/digital-text/157305011/',
    'sci_fi':            'https://www.amazon.com/gp/most-wished-for/digital-text/158591011/',
    'fantasy':           'https://www.amazon.com/gp/most-wished-for/digital-text/158576011/',
    'self_help':         'https://www.amazon.com/gp/most-wished-for/digital-text/156563011/',
    'business':          'https://www.amazon.com/gp/most-wished-for/digital-text/154821011/',
    'young_adult':       'https://www.amazon.com/gp/most-wished-for/digital-text/3511261011/',
    'children':          'https://www.amazon.com/gp/most-wished-for/digital-text/155009011/',
    'horror':            'https://www.amazon.com/gp/most-wished-for/digital-text/157060011/',
    'literary_fiction':  'https://www.amazon.com/gp/most-wished-for/digital-text/157028011/',
    'biographies':       'https://www.amazon.com/gp/most-wished-for/digital-text/154754011/',
    'true_crime':        'https://www.amazon.com/gp/most-wished-for/digital-text/157554011/',
    'cookbooks':         'https://www.amazon.com/gp/most-wished-for/digital-text/156154011/',
    'health_fitness':    'https://www.amazon.com/gp/most-wished-for/digital-text/156430011/',
}

# Category-specific Bestsellers
CATEGORY_BESTSELLER_URLS = {
    'romance':           'https://www.amazon.com/gp/bestsellers/digital-text/158566011/',
    'mystery_thriller':  'https://www.amazon.com/gp/bestsellers/digital-text/157305011/',
    'sci_fi':            'https://www.amazon.com/gp/bestsellers/digital-text/158591011/',
    'fantasy':           'https://www.amazon.com/gp/bestsellers/digital-text/158576011/',
    'self_help':         'https://www.amazon.com/gp/bestsellers/digital-text/156563011/',
    'business':          'https://www.amazon.com/gp/bestsellers/digital-text/154821011/',
    'young_adult':       'https://www.amazon.com/gp/bestsellers/digital-text/3511261011/',
    'children':          'https://www.amazon.com/gp/bestsellers/digital-text/155009011/',
    'horror':            'https://www.amazon.com/gp/bestsellers/digital-text/157060011/',
    'literary_fiction':  'https://www.amazon.com/gp/bestsellers/digital-text/157028011/',
    'biographies':       'https://www.amazon.com/gp/bestsellers/digital-text/154754011/',
    'true_crime':        'https://www.amazon.com/gp/bestsellers/digital-text/157554011/',
    'cookbooks':         'https://www.amazon.com/gp/bestsellers/digital-text/156154011/',
    'health_fitness':    'https://www.amazon.com/gp/bestsellers/digital-text/156430011/',
}

# Major KDP book categories to auto-mine
KDP_CATEGORY_SEEDS = [
    'romance', 'thriller', 'mystery', 'science fiction', 'fantasy',
    'historical fiction', 'horror', 'contemporary fiction', 'literary fiction',
    'young adult', 'children books', 'self help', 'personal development',
    'business', 'entrepreneurship', 'memoir', 'biography', 'true crime',
    'cookbook', 'health and fitness', 'weight loss', 'meditation', 'mindfulness',
    'parenting', 'relationship', 'money management', 'investing', 'real estate',
    'coloring book', 'activity book', 'journal', 'planner', 'workbook',
    'puzzle book', 'word search', 'sudoku', 'poetry', 'short stories',
    'graphic novel', 'manga', 'dystopian', 'urban fantasy', 'paranormal romance',
    'cozy mystery', 'psychological thriller', 'military science fiction',
    'space opera', 'dark romance', 'reverse harem', 'litrpg',
    'romantasy', 'cottagecore', 'booktok', 'slow burn romance',
]

# Google suggest query patterns
TRENDING_PATTERNS = [
    'best {category} books 2026',
    '{category} books like',
    'new {category} books',
    'top {category} kindle',
    '{category} kindle unlimited',
    '{category} book recommendations',
]

TRENDING_BASE_CATEGORIES = [
    'romance', 'thriller', 'mystery', 'fantasy', 'sci fi',
    'horror', 'self help', 'historical fiction', 'young adult',
    'true crime', 'memoir', 'business',
]


# ── Bestseller list scrapers ──────────────────────────────────────────────


def scrape_bestseller_keywords(list_type='kindle', category=None, progress_callback=None, cancel_check=None):
    """Scrape Amazon bestseller page for keyword ideas.

    Args:
        list_type: Key from BESTSELLER_URLS dict.
        progress_callback: Optional callable(completed, total).

    Returns:
        List of (keyword, source_info) tuples.
    """
    rate_registry.get_limiter('product_scrape', rate=Config.PRODUCT_SCRAPE_RATE_LIMIT)

    # Category-specific bestseller URL
    if category and category in CATEGORY_BESTSELLER_URLS:
        url = CATEGORY_BESTSELLER_URLS[category]
    else:
        url = BESTSELLER_URLS.get(list_type)
    if not url:
        logger.error(f'Unknown list type: {list_type}')
        return []

    rate_registry.acquire('product_scrape')

    try:
        response = fetch(url, headers=get_browser_headers())
    except Exception as e:
        logger.error(f'Error fetching {list_type} page: {e}')
        return []

    if response.status_code != 200:
        logger.warning(f'{list_type} page returned {response.status_code}')
        return []

    html = response.text
    if _is_captcha(html):
        logger.warning(f'CAPTCHA detected on {list_type} page')
        return []

    soup = BeautifulSoup(html, 'html.parser')
    keywords = {}

    for kw, info in _extract_title_keywords(soup):
        if kw not in keywords:
            keywords[kw] = info

    for kw, info in _extract_category_keywords(soup):
        if kw not in keywords:
            keywords[kw] = info

    results = list(keywords.items())

    if progress_callback:
        progress_callback(1, 1)

    logger.info(f'Bestseller scrape ({list_type}): {len(results)} keywords')
    return results


def scrape_movers_shakers(category=None, progress_callback=None, cancel_check=None):
    """Scrape Amazon Movers & Shakers for the fastest-rising books.

    Movers & Shakers is updated hourly and shows the biggest BSR gainers
    — it's the strongest real-time trending signal on Amazon.

    Args:
        category: Optional category key from CATEGORY_MOVERS_URLS.
                  If None, scrapes the main Kindle Movers & Shakers.
        progress_callback: Optional callable(completed, total).

    Returns:
        List of dicts with keys: keyword, asin, bsr_change, source, rank.
    """
    rate_registry.get_limiter('product_scrape', rate=Config.PRODUCT_SCRAPE_RATE_LIMIT)

    if category and category in CATEGORY_MOVERS_URLS:
        url = CATEGORY_MOVERS_URLS[category]
        source_label = f'Movers & Shakers: {category}'
    else:
        url = BESTSELLER_URLS['kindle_movers']
        source_label = 'Movers & Shakers: Kindle'

    rate_registry.acquire('product_scrape')

    try:
        response = fetch(url, headers=get_browser_headers())
    except Exception as e:
        logger.error(f'Error fetching Movers & Shakers: {e}')
        return []

    if response.status_code != 200:
        logger.warning(f'Movers & Shakers returned {response.status_code}')
        return []

    html = response.text
    if _is_captcha(html):
        logger.warning('CAPTCHA on Movers & Shakers page')
        return []

    soup = BeautifulSoup(html, 'html.parser')
    results = []
    rank = 1

    # Extract book items — Movers & Shakers uses the same zg-item structure
    seen = set()
    for item in _find_list_items(soup):
        asin = _get_item_asin(item)
        title_text = _get_item_title(item)
        bsr_change = _get_movers_change(item)
        author = _get_item_author(item)

        if title_text and title_text.lower() not in seen:
            seen.add(title_text.lower())
            results.append({
                'keyword': title_text,
                'asin': asin,
                'bsr_change': bsr_change,
                'source': source_label,
                'rank': rank,
                'title': title_text,
                'author': author,
            })
            rank += 1

    if progress_callback:
        progress_callback(1, 1)

    logger.info(f'Movers & Shakers scrape ({category or "main"}): {len(results)} keywords')
    return results


def scrape_most_wished_for(category=None, progress_callback=None, cancel_check=None):
    """Scrape popular Kindle books from multiple Amazon lists.

    Args:
        category: Optional category key from CATEGORY_WISHED_URLS (e.g. 'romance').
                  If None, scrapes a multi-source combination.

    Amazon's Most Wished For page is JS-rendered and cannot be scraped
    with requests. Instead we combine Free Kindle Bestsellers + Physical
    Books Bestsellers to surface books the main bestseller list misses.

    Returns list of dicts: {title, author, asin, rank, source}
    """
    # Category-specific scrape
    if category and category in CATEGORY_WISHED_URLS:
        url = CATEGORY_WISHED_URLS[category]
        label = category.replace('_', ' ').title() + ' — Most Wished For'
        results = _scrape_structured_list(url, label)
        if results:
            if progress_callback:
                progress_callback(1, 1)
            return results
        # Fallback: Most Wished For pages are often JS-rendered,
        # so if we got nothing, fall through to multi-source scrape

    sources = [
        (BESTSELLER_URLS['kindle_free'], 'Free Kindle Bestsellers'),
        (BESTSELLER_URLS['books'], 'Books Bestsellers'),
        (BESTSELLER_URLS['books_wished'], 'Books Most Wished For'),
    ]

    all_results = []
    seen_titles = set()
    total = len(sources)

    for idx, (url, label) in enumerate(sources):
        if cancel_check and cancel_check():
            return all_results

        items = _scrape_structured_list(url, label)
        for item in items:
            key = item.get('title', '').lower().strip()
            if key and key not in seen_titles:
                seen_titles.add(key)
                item['rank'] = len(all_results) + 1
                all_results.append(item)

        if progress_callback:
            progress_callback(idx + 1, total)

    # Also try the actual wished-for page (works if user has JS-capable env)
    if not cancel_check or not cancel_check():
        wished = _scrape_structured_list(
            BESTSELLER_URLS['kindle_wished'], 'Most Wished For'
        )
        for item in wished:
            key = item.get('title', '').lower().strip()
            if key and key not in seen_titles:
                seen_titles.add(key)
                item['rank'] = len(all_results) + 1
                all_results.append(item)

    logger.info(f'Most Wished For (multi-source): {len(all_results)} books')
    return all_results


def scrape_also_bought(asin, progress_callback=None, cancel_check=None):
    """Extract also-bought/also-viewed ASINs and keywords from a product page.

    Scrapes the "Customers who bought this also bought" carousel from an
    Amazon product page to discover related books in adjacent niches.

    Args:
        asin: Amazon ASIN to scrape.
        progress_callback: Optional callable(completed, total).

    Returns:
        List of dicts: [{'asin': str, 'title': str, 'keyword': str, 'source': str}]
    """
    rate_registry.get_limiter('product_scrape', rate=Config.PRODUCT_SCRAPE_RATE_LIMIT)
    rate_registry.acquire('product_scrape')

    url = f'https://www.amazon.com/dp/{asin}'

    try:
        response = fetch(url, headers=get_browser_headers())
    except Exception as e:
        logger.error(f'Error fetching product page for {asin}: {e}')
        return []

    if response.status_code != 200:
        logger.warning(f'Product page returned {response.status_code} for {asin}')
        return []

    html = response.text
    if _is_captcha(html):
        return []

    soup = BeautifulSoup(html, 'html.parser')
    results = []

    # Look for "also bought" carousels
    carousel_titles = []

    # Various selectors Amazon uses for carousels
    for sel in [
        'div[id*="also-bought"] .a-link-normal',
        'div[id*="customers-who-bought"] .a-link-normal',
        'div[class*="sims-fbt"] a.a-link-normal',
        'div[id*="p_dp_sims"] .a-link-normal',
        '[data-widget-name*="sims"] a.a-link-normal',
        '.a-carousel-card a.a-link-normal',
    ]:
        links = soup.select(sel)
        for link in links[:30]:
            href = link.get('href', '')
            # Extract ASIN from href
            asin_match = re.search(r'/(?:dp|product)/([A-Z0-9]{10})', href)
            if asin_match:
                related_asin = asin_match.group(1)
                title_el = link.find(['span', 'img'])
                title_text = ''
                if title_el:
                    title_text = title_el.get('alt', '') or title_el.get_text(strip=True)
                if title_text and len(title_text) > 5:
                    carousel_titles.append((related_asin, title_text))

    # Deduplicate by ASIN
    seen_asins = set()
    for related_asin, title_text in carousel_titles:
        if related_asin in seen_asins or related_asin == asin:
            continue
        seen_asins.add(related_asin)

        phrases = _extract_phrases_from_title(title_text)
        for phrase in phrases[:2]:
            results.append({
                'asin': related_asin,
                'title': title_text,
                'keyword': phrase,
                'source': f'Also Bought: {asin}',
            })

    if progress_callback:
        progress_callback(1, 1)

    logger.info(f'Also Bought for {asin}: {len(results)} keywords from {len(seen_asins)} related books')
    return results


def scrape_hot_new_releases(category=None, progress_callback=None, cancel_check=None):
    """Scrape Hot New Releases for recently published books gaining traction.

    Args:
        category: Optional category key from CATEGORY_HNR_URLS (e.g. 'romance').
                  If None, scrapes the main Kindle Hot New Releases.
    Returns list of dicts: {title, author, asin, rank, source}
    """
    if category and category in CATEGORY_HNR_URLS:
        url = CATEGORY_HNR_URLS[category]
        label = category.replace('_', ' ').title() + ' — Hot New Releases'
    else:
        url = BESTSELLER_URLS['kindle_new']
        label = 'Hot New Releases'
    results = _scrape_structured_list(url, label)
    if progress_callback:
        progress_callback(1, 1)
    return results


# ── Google suggest trending ───────────────────────────────────────────────


def discover_trending_keywords(progress_callback=None, cancel_check=None):
    """Discover trending book keywords via Google suggest.

    Args:
        progress_callback: Optional callable(completed, total).

    Returns:
        List of (keyword, position) tuples, deduplicated and sorted.
    """
    rate_registry.get_limiter('autocomplete', rate=Config.AUTOCOMPLETE_RATE_LIMIT)

    all_results = {}
    queries = []

    for category in TRENDING_BASE_CATEGORIES:
        for pattern in TRENDING_PATTERNS:
            queries.append(pattern.format(category=category))

    total = len(queries)
    completed = 0

    for query in queries:
        suggestions = _query_google_suggest(query)
        for kw, pos in suggestions:
            cleaned = _clean_book_keyword(kw)
            if cleaned and len(cleaned) >= 3:
                if cleaned not in all_results or pos < all_results[cleaned]:
                    all_results[cleaned] = pos

        completed += 1
        if progress_callback:
            progress_callback(completed, total)

    results = sorted(all_results.items(), key=lambda x: (x[1], x[0]))
    logger.info(f'Trending discovery: {len(results)} keywords')
    return results


def get_category_seeds():
    """Return the built-in list of KDP category seed keywords."""
    return list(KDP_CATEGORY_SEEDS)


# ── Internal helpers ──────────────────────────────────────────────────────


def _find_list_items(soup):
    """Find product items in a bestseller/movers page."""
    # Modern layout
    items = soup.select('div.zg-grid-general-faceout, li.zg-item-immersion')
    if items:
        return items

    # Legacy layout
    items = soup.select('li.zg-item, div.zg_item_compact')
    if items:
        return items

    # Very generic fallback
    items = soup.find_all('div', attrs={'data-asin': re.compile(r'[A-Z0-9]{10}')})
    return items[:100]


def _get_item_title(item):
    """Get the title from a list item."""
    for sel in [
        'div.p13n-sc-truncate',
        'div._cDEzb_p13n-sc-css-line-clamp-1_1Fn1y',
        'span.zg-text-center-align a span',
        'a.a-link-normal span.a-size-base',
        'span.a-size-small.a-color-base',
        'img',
    ]:
        el = item.select_one(sel)
        if el:
            text = el.get('alt', '') or el.get_text(strip=True)
            if text and len(text) > 5:
                return text
    return ''


def _get_item_author(item):
    """Get author name from a list item."""
    for sel in [
        'span.a-size-small.a-color-secondary',
        'a.a-size-small.a-link-child',
        'span.a-color-secondary span.a-size-small',
        'div.a-row.a-size-small span.a-color-secondary',
        'div.a-row span.a-size-small',
    ]:
        el = item.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text and len(text) > 1 and not text.startswith('#') and not text.startswith('$'):
                return text
    return ''


def _get_item_asin(item):
    """Get ASIN from a list item."""
    asin = item.get('data-asin', '').strip().upper()
    if asin and re.match(r'^[A-Z0-9]{10}$', asin):
        return asin
    link = item.select_one('a[href*="/dp/"]')
    if link:
        m = re.search(r'/dp/([A-Z0-9]{10})', link.get('href', ''))
        if m:
            return m.group(1)
    return ''


def _scrape_structured_list(url, source_label):
    """Scrape an Amazon list page and return structured book data.
    
    Returns list of dicts: {title, author, asin, rank, source}
    """
    rate_registry.get_limiter('product_scrape', rate=Config.PRODUCT_SCRAPE_RATE_LIMIT)
    rate_registry.acquire('product_scrape')

    try:
        response = fetch(url, headers=get_browser_headers())
    except Exception as e:
        logger.error(f'Error fetching {source_label}: {e}')
        return []

    if response.status_code != 200:
        logger.warning(f'{source_label} returned {response.status_code}')
        return []

    html = response.text
    if _is_captcha(html):
        logger.warning(f'CAPTCHA on {source_label}')
        return []

    soup = BeautifulSoup(html, 'html.parser')
    results = []
    seen_titles = set()
    rank = 1

    for item in _find_list_items(soup):
        title = _get_item_title(item)
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())
        author = _get_item_author(item)
        asin = _get_item_asin(item)
        results.append({
            'title': title,
            'author': author,
            'asin': asin,
            'rank': rank,
            'source': source_label,
        })
        rank += 1

    logger.info(f'{source_label}: {len(results)} books')
    return results

def _get_movers_change(item):
    """Extract BSR change percentage from a Movers & Shakers item."""
    for sel in [
        'span.zg-percent-change',
        'span.a-color-success',
        '.a-size-small.a-color-success',
    ]:
        el = item.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            match = re.search(r'([\d,]+)%', text)
            if match:
                return int(match.group(1).replace(',', ''))
    return None


def _extract_title_keywords(soup):
    """Extract keyword phrases from bestseller book titles."""
    results = []

    title_selectors = [
        'div.p13n-sc-truncate',
        'div._cDEzb_p13n-sc-css-line-clamp-1_1Fn1y',
        'span.zg-text-center-align a span',
        'a.a-link-normal span.a-size-base',
        'div[id^="p13n-asin-index-"] span.a-size-small',
        '.zg-item-immersion .a-link-normal span',
    ]

    titles = []
    for selector in title_selectors:
        elements = soup.select(selector)
        if elements:
            for el in elements:
                text = el.get_text(strip=True)
                if text and len(text) > 5:
                    titles.append(text)
            if len(titles) >= 20:
                break

    # Fallback
    if not titles:
        for link in soup.find_all('a', class_='a-link-normal'):
            span = link.find('span')
            if span:
                text = span.get_text(strip=True)
                if text and 10 < len(text) < 200:
                    titles.append(text)

    for title in titles[:50]:
        phrases = _extract_phrases_from_title(title)
        for phrase in phrases:
            results.append((phrase, f'bestseller title: {title[:50]}'))

    return results


def _extract_phrases_from_title(title):
    """Extract relevant keyword phrases from a book title."""
    title = title.lower().strip()

    # Clean punctuation and common noise
    title = re.sub(r'[:()\\[\\]{}|#*]', ' ', title)
    title = re.sub(
        r'\b(a|an|the|of|in|on|at|to|for|and|or|but|is|are|was|were|be|been|'
        r'have|has|had|do|does|did|will|would|could|should|may|might|can|shall|'
        r'must|need|dare|ought|used|am|with|by|from|into|through|during|before|'
        r'after|above|below|between|out|off|over|under|again|further|then|once|'
        r'here|there|when|where|why|how|all|each|every|both|few|more|most|other|'
        r'some|such|no|not|only|own|same|so|than|too|very)\b', ' ', title
    )
    title = re.sub(r'\b(book|volume|edition|series|novel|part)\s*\d*\b', '', title)
    title = re.sub(r'\s+', ' ', title).strip()

    phrases = []
    words = title.split()

    if len(words) >= 2:
        for i in range(len(words) - 1):
            bigram = f'{words[i]} {words[i+1]}'
            if len(bigram) >= 5:
                phrases.append(bigram)

        for i in range(len(words) - 2):
            trigram = f'{words[i]} {words[i+1]} {words[i+2]}'
            if len(trigram) >= 8:
                phrases.append(trigram)

    return phrases


def _extract_category_keywords(soup):
    """Extract category and genre keywords from the page."""
    results = []

    cat_selectors = [
        'ul#zg_browseRoot a',
        'div._p13n-zg-nav-tree-all_style_zg-browse-group__88fbz a',
        'span.zg_selected',
        'div.zg_browseRoot a',
        'ul.a-unordered-list.a-horizontal li a',
    ]

    for selector in cat_selectors:
        for el in soup.select(selector):
            text = el.get_text(strip=True).lower()
            if (text and 3 <= len(text) <= 50
                    and text not in ('any department', 'kindle store', 'kindle ebooks')
                    and not text.startswith('see top')):
                results.append((text, 'bestseller category'))

    return results


def _query_google_suggest(query):
    """Query Google's autocomplete for book-related suggestions."""
    rate_registry.acquire('autocomplete')

    url = 'https://suggestqueries.google.com/complete/search'
    params = {'client': 'firefox', 'q': query}

    try:
        response = fetch(url, params=params)
        if response.status_code != 200:
            return []

        data = response.json()
        if not isinstance(data, list) or len(data) < 2:
            return []

        suggestions = data[1]
        results = []
        for i, suggestion in enumerate(suggestions):
            keyword = suggestion.strip().lower()
            if keyword and keyword != query.lower():
                results.append((keyword, i + 1))

        return results
    except Exception as e:
        logger.debug(f'Google suggest failed for "{query}": {e}')
        return []


def _clean_book_keyword(keyword):
    """Clean a Google suggest result into a KDP-relevant keyword."""
    kw = keyword.lower().strip()

    for prefix in ['best ', 'top ', 'new ', 'most popular ']:
        if kw.startswith(prefix):
            kw = kw[len(prefix):]

    kw = re.sub(r'\b20\d{2}\b', '', kw)

    for suffix in [' books', ' kindle', ' kindle unlimited', ' book',
                   ' recommendations', ' to read', ' on amazon',
                   ' for adults', ' for beginners']:
        if kw.endswith(suffix):
            kw = kw[:-len(suffix)]

    kw = re.sub(r'\s+', ' ', kw).strip()
    return kw if len(kw) >= 3 else ''


def _is_captcha(html):
    """Check if the page is a CAPTCHA response."""
    captcha_markers = [
        'Enter the characters you see below',
        "Sorry, we just need to make sure you're not a robot",
        '/errors/validateCaptcha',
        'Type the characters you see in this image',
    ]
    html_lower = html.lower()
    return any(m.lower() in html_lower for m in captcha_markers)


# --- Fast async variant (aiohttp) ---
try:
    import aiohttp as _aiohttp
    _HAS_AIOHTTP = True
except ImportError:
    _HAS_AIOHTTP = False


async def _discover_trending_async(queries, progress_callback=None, cancel_check=None):
    """Async version using aiohttp for concurrent requests."""
    sem = __import__('asyncio').Semaphore(12)
    results = []
    done = 0

    async def _fetch(session, q):
        nonlocal done
        if cancel_check and cancel_check():
            return []
        async with sem:
            if cancel_check and cancel_check():
                return []
            url = "https://completion.amazon.com/api/2017/suggestions"
            params = {"mid": "ATVPDKIKX0DER", "alias": "digital-text", "prefix": q}
            try:
                async with session.get(url, params=params, timeout=_aiohttp.ClientTimeout(total=8)) as resp:
                    data = await resp.json(content_type=None)
                    done += 1
                    if progress_callback:
                        progress_callback(done, len(queries))
                    return [s.get("value", "") for s in data.get("suggestions", [])]
            except Exception:
                done += 1
                if progress_callback:
                    progress_callback(done, len(queries))
                return []

    async with _aiohttp.ClientSession() as session:
        tasks = [_fetch(session, q) for q in queries]
        batch = await __import__('asyncio').gather(*tasks)
        for kws in batch:
            results.extend(kws)
    return results


def discover_trending_keywords_fast(progress_callback=None, cancel_check=None):
    """Fast variant using aiohttp. Falls back to sync if unavailable."""
    import asyncio
    if not _HAS_AIOHTTP:
        return discover_trending_keywords(progress_callback, cancel_check=cancel_check)
    letters = list(_ALPHABET) if len(_ALPHABET) == 26 else [chr(c) for c in range(ord('a'), ord('z')+1)]
    queries = []
    for l in letters:
        queries.append(l)
        queries.append(f"{l} kindle")
    for seed in ['romance', 'thriller', 'fantasy', 'self help', 'mystery',
                 'horror', 'coloring book', 'journal', 'dark romance',
                 'booktok', 'ya', 'sci fi', 'memoir', 'true crime']:
        queries.append(seed)
        queries.append(f"{seed} 2026")
        queries.append(f"best {seed}")
    raw = asyncio.run(_discover_trending_async(queries, progress_callback, cancel_check=cancel_check))
    # Deduplicate and assign positions to match original return format: list of (keyword, position)
    seen = {}
    for kw in raw:
        if kw and kw not in seen:
            seen[kw] = len(seen) + 1
    results = sorted(seen.items(), key=lambda x: (x[1], x[0]))
    return results

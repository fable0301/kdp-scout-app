"""Amazon search results scraper for keyword competition analysis.

Scrapes the Amazon Kindle store search results page to extract:
- Top N organic results with ASIN, title, author, BSR, reviews, price
- Total competing books count
- Average BSR of top 10 organic results (demand signal)
- KU eligibility flags
- Series detection

Used by CompetitionProber in keyword_engine.py to enrich keyword metrics.
"""

import re
import logging
import time

from bs4 import BeautifulSoup

from kdp_scout.http_client import fetch, get_browser_headers
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config

logger = logging.getLogger(__name__)

# Search URLs per marketplace
MARKETPLACE_SEARCH_URLS = {
    'us': 'https://www.amazon.com/s',
    'uk': 'https://www.amazon.co.uk/s',
    'de': 'https://www.amazon.de/s',
    'fr': 'https://www.amazon.fr/s',
    'ca': 'https://www.amazon.ca/s',
    'au': 'https://www.amazon.com.au/s',
    'jp': 'https://www.amazon.co.jp/s',
    'es': 'https://www.amazon.es/s',
    'it': 'https://www.amazon.it/s',
    'mx': 'https://www.amazon.com.mx/s',
    'br': 'https://www.amazon.com.br/s',
    'in': 'https://www.amazon.in/s',
    'nl': 'https://www.amazon.nl/s',
    'se': 'https://www.amazon.se/s',
    'pl': 'https://www.amazon.pl/s',
    'tr': 'https://www.amazon.com.tr/s',
    'ae': 'https://www.amazon.ae/s',
    'sg': 'https://www.amazon.sg/s',
}

# Kindle department identifier per marketplace
MARKETPLACE_KINDLE_DEPT = {
    'us': 'digital-text',
    'uk': 'digital-text',
    'de': 'digital-text',
    'fr': 'digital-text',
    'ca': 'digital-text',
    'au': 'digital-text',
    'jp': 'digital-text',
    'es': 'digital-text',
    'it': 'digital-text',
    'mx': 'digital-text',
    'br': 'digital-text',
    'in': 'digital-text',
    'nl': 'digital-text',
    'se': 'digital-text',
    'pl': 'digital-text',
    'tr': 'digital-text',
    'ae': 'digital-text',
    'sg': 'digital-text',
}

# Sponsored result HTML markers
SPONSORED_MARKERS = [
    'AdHolder',
    'sp-sponsored-result',
    'puis-sponsored-label',
    's-sponsored-label',
    'a-spacing-micro s-sponsored-label',
]

# Currency symbols for price extraction
CURRENCY_PATTERN = r'[\$€£¥₹R\$]?\s*([\d,]+\.?\d*)'


class SearchResult:
    """Represents a single organic Amazon search result."""

    def __init__(self, asin, title=None, author=None, bsr=None,
                 review_count=None, avg_rating=None, price_kindle=None,
                 price_paperback=None, is_sponsored=False, position=0,
                 ku_eligible=False, series=None, publication_date=None):
        self.asin = asin
        self.title = title
        self.author = author
        self.bsr = bsr
        self.review_count = review_count
        self.avg_rating = avg_rating
        self.price_kindle = price_kindle
        self.price_paperback = price_paperback
        self.is_sponsored = is_sponsored
        self.position = position
        self.ku_eligible = ku_eligible
        self.series = series
        self.publication_date = publication_date

    def to_dict(self):
        return {
            'asin': self.asin,
            'title': self.title,
            'author': self.author,
            'bsr': self.bsr,
            'review_count': self.review_count,
            'avg_rating': self.avg_rating,
            'price_kindle': self.price_kindle,
            'price_paperback': self.price_paperback,
            'is_sponsored': self.is_sponsored,
            'position': self.position,
            'ku_eligible': self.ku_eligible,
            'series': self.series,
            'publication_date': self.publication_date,
        }


def search_kindle(keyword, marketplace='us', max_results=10, page=1, sort_by=None):
    """Search Amazon Kindle store and extract results with competition metrics.

    Args:
        keyword: The search term to query.
        marketplace: Two-letter marketplace code ('us', 'uk', 'de', etc.).
        max_results: Maximum number of organic results to return.
        page: Page number (1-indexed).
        sort_by: Amazon sort parameter. Common values:
            None / 'relevancerank' → relevance (default)
            'salesrank'            → Bestsellers
            'date-rank'            → New Releases

    Returns:
        Dict with:
            - results: List of result dicts (SearchResult.to_dict())
            - organic_count: Number of organic results on this page
            - competition_count: Estimated total competing books
            - avg_bsr_top10: Average BSR of top organic results (demand signal)
            - median_reviews: Median review count of top results (barrier to entry)
            - ku_ratio: Fraction of results that are KU-eligible
            - top_asins: List of top ASIN strings
            - total_results_text: Raw results count text from page
    """
    rate_registry.get_limiter('search_probe', rate=Config.SEARCH_PROBE_RATE_LIMIT)
    rate_registry.acquire('search_probe')

    base_url = MARKETPLACE_SEARCH_URLS.get(marketplace, MARKETPLACE_SEARCH_URLS['us'])
    dept = MARKETPLACE_KINDLE_DEPT.get(marketplace, 'digital-text')

    params = {
        'k': keyword,
        'i': dept,
    }
    if sort_by:
        params['s'] = sort_by
    if page > 1:
        params['page'] = page

    try:
        response = fetch(base_url, params=params, headers=get_browser_headers())
    except Exception as e:
        logger.error(f'Error searching "{keyword}" on {marketplace}: {e}')
        return _empty_result()

    if response.status_code != 200:
        logger.warning(f'Search returned {response.status_code} for "{keyword}" ({marketplace})')
        return _empty_result()

    html = response.text
    if _is_captcha(html):
        logger.warning(f'CAPTCHA detected searching "{keyword}" ({marketplace})')
        return _empty_result()

    result = _parse_search_page(html, max_results=max_results)
    logger.info(
        f'Search "{keyword}" ({marketplace}): {result["organic_count"]} results, '
        f'competition={result["competition_count"]}, avg_bsr={result["avg_bsr_top10"]}'
    )
    return result


def probe_competition(keyword, marketplace='us', top_n=10):
    """Get competition metrics for a keyword: result count + avg BSR of top N.

    Convenience wrapper around search_kindle() focused on competition signals.

    Args:
        keyword: The keyword to probe.
        marketplace: Marketplace code.
        top_n: Number of top results to use for BSR average.

    Returns:
        Dict with 'competition_count', 'avg_bsr_top10', 'ku_ratio',
        'median_reviews', 'top_asins'.
    """
    data = search_kindle(keyword, marketplace=marketplace, max_results=top_n)
    return {
        'competition_count': data['competition_count'],
        'avg_bsr_top10': data['avg_bsr_top10'],
        'ku_ratio': data['ku_ratio'],
        'median_reviews': data['median_reviews'],
        'top_asins': data['top_asins'],
        'top10_results': data['results'],
    }


def find_asin_in_search(keyword, target_asin, marketplace='us'):
    """Search for a keyword and find the organic position of a target ASIN.

    Used by ReverseASIN probe method.

    Args:
        keyword: The keyword to search.
        target_asin: ASIN to look for in results.
        marketplace: Marketplace code.

    Returns:
        1-based organic position if found, None if not found.
    """
    data = search_kindle(keyword, marketplace=marketplace, max_results=48)
    for result in data['results']:
        if result['asin'].upper() == target_asin.upper():
            return result['position']
    return None


# ── Internal parsing ──────────────────────────────────────────────────────


def _parse_search_page(html, max_results=10):
    """Parse Amazon search results HTML into structured data."""
    soup = BeautifulSoup(html, 'html.parser')

    results = []
    organic_position = 0

    # Get total results count
    competition_count = None
    total_results_text = ''

    # Try multiple selectors for result count
    for sel in [
        'span.a-size-base.a-color-base.s-results-count',
        'span[data-component-type="s-result-info-bar"] span',
        '.s-breadcrumb .a-size-medium span',
        'div.sg-col-inner div.a-section h1.a-size-large span',
    ]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if 'result' in text.lower() or any(c.isdigit() for c in text):
                total_results_text = text
                break

    if not total_results_text:
        # Fallback: scan all text
        full_text = soup.get_text()
        match = re.search(r'([\d,]+)\s+results?\s+for', full_text, re.IGNORECASE)
        if match:
            total_results_text = match.group(0)

    # Parse competition count
    count_match = re.search(r'(?:of\s+(?:over\s+)?)([\d,]+)', total_results_text, re.IGNORECASE)
    if not count_match:
        count_match = re.search(r'([\d,]+)\s+results?', total_results_text, re.IGNORECASE)
    if count_match:
        try:
            competition_count = int(count_match.group(1).replace(',', ''))
        except ValueError:
            pass

    # Find all result divs - Amazon uses data-asin on result containers
    result_divs = soup.find_all(
        'div',
        attrs={'data-asin': True, 'data-component-type': 's-search-result'},
    )
    if not result_divs:
        # Fallback
        result_divs = [
            d for d in soup.find_all('div', attrs={'data-asin': True})
            if d.get('data-asin', '').strip()
        ]

    for div in result_divs:
        asin = div.get('data-asin', '').strip().upper()
        if not asin:
            continue

        sponsored = _is_sponsored(div)

        if not sponsored:
            organic_position += 1

        if not sponsored:
            result = _parse_result_div(div, asin, position=organic_position, is_sponsored=False)
            results.append(result)

        if len(results) >= max_results:
            break

    # Compute aggregate metrics
    bsr_values = [r.bsr for r in results if r.bsr and r.bsr > 0]
    avg_bsr_top10 = round(sum(bsr_values) / len(bsr_values), 0) if bsr_values else None

    review_values = sorted([r.review_count for r in results if r.review_count and r.review_count > 0])
    if review_values:
        mid = len(review_values) // 2
        median_reviews = (
            review_values[mid]
            if len(review_values) % 2 == 1
            else (review_values[mid - 1] + review_values[mid]) // 2
        )
    else:
        median_reviews = None

    ku_count = sum(1 for r in results if r.ku_eligible)
    ku_ratio = round(ku_count / len(results), 2) if results else 0.0

    top_asins = [r.asin for r in results]

    return {
        'results': [r.to_dict() for r in results],
        'organic_count': len(results),
        'total_results_text': total_results_text,
        'competition_count': competition_count,
        'avg_bsr_top10': avg_bsr_top10,
        'median_reviews': median_reviews,
        'ku_ratio': ku_ratio,
        'top_asins': top_asins,
    }


def _parse_result_div(div, asin, position, is_sponsored):
    """Extract structured data from a search result div."""
    result = SearchResult(asin=asin, position=position, is_sponsored=is_sponsored)
    div_text = div.get_text(' ', strip=True)

    # Title — multiple possible selectors
    for sel in [
        'h2 a span',
        '.a-size-medium.a-color-base.a-text-normal',
        '.a-size-base-plus.a-color-base.a-text-normal',
        '.a-text-normal span',
    ]:
        el = div.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text and len(text) > 3:
                result.title = text
                break

    # Author
    for sel in [
        '.a-row .a-size-base.a-color-secondary',
        'span.a-size-base.a-color-base + span.a-size-base',
        '.a-row span.a-size-base',
    ]:
        el = div.select_one(sel)
        if el:
            text = el.get_text(strip=True)
            if text and not text.startswith('$') and not text.startswith('€') and len(text) > 2:
                # Avoid picking up "Kindle Edition" or prices
                if not re.match(r'^\d', text) and 'edition' not in text.lower():
                    result.author = text
                    break

    # Average rating
    for sel in [
        '.a-icon-star-small .a-icon-alt',
        'i[class*="a-star"] .a-icon-alt',
        'span[aria-label*="out of 5"]',
    ]:
        el = div.select_one(sel)
        if el:
            text = el.get('aria-label', '') or el.get_text()
            rating_match = re.search(r'([\d.]+)\s*(?:out of|stars?|von|étoiles?)', text, re.IGNORECASE)
            if not rating_match:
                rating_match = re.search(r'^([\d.]+)', text.strip())
            if rating_match:
                try:
                    val = float(rating_match.group(1))
                    if 0 < val <= 5:
                        result.avg_rating = val
                        break
                except ValueError:
                    pass

    # Review count
    for sel in [
        'span.a-size-base.s-underline-text',
        'span[aria-label*="ratings"]',
        'a span.a-size-base',
    ]:
        el = div.select_one(sel)
        if el:
            text = el.get('aria-label', '') or el.get_text()
            review_match = re.search(r'([\d,]+)', text)
            if review_match:
                try:
                    val = int(review_match.group(1).replace(',', ''))
                    if val > 0:
                        result.review_count = val
                        break
                except ValueError:
                    pass

    # Kindle price
    for sel in [
        '.a-price[data-a-color="base"] .a-offscreen',
        '.a-price .a-offscreen',
        'span.a-price span.a-offscreen',
    ]:
        el = div.select_one(sel)
        if el:
            price_text = el.get_text(strip=True)
            price_match = re.search(r'([\d,]+\.?\d*)', price_text.replace(',', '.') if ',' in price_text and '.' not in price_text else price_text)
            if price_match:
                try:
                    val = float(price_match.group(1).replace(',', ''))
                    if val >= 0:
                        result.price_kindle = val
                        break
                except ValueError:
                    pass

    # KU eligible — look for "Kindle Unlimited" badge or "Read for Free" text
    ku_markers = ['kindle unlimited', 'read for free', 'lire gratuitement',
                  'lesen mit kindle unlimited', 'incluido en kindle unlimited']
    if any(m in div_text.lower() for m in ku_markers):
        result.ku_eligible = True

    # Series — "Book 1", "Part 2", "(Series Name, #3)"
    series_match = re.search(
        r'\(([^)]{3,60}(?:Series|Book\s*\d|Teil\s*\d|Tome\s*\d|Part\s*\d|#\s*\d)[^)]{0,40})\)',
        div_text, re.IGNORECASE,
    )
    if series_match:
        result.series = series_match.group(1).strip()

    return result


def _is_sponsored(div):
    """Check if a search result div is a sponsored/ad result."""
    div_classes = ' '.join(div.get('class', []))
    div_html = str(div)[:2000]  # Only check first 2000 chars for performance
    for marker in SPONSORED_MARKERS:
        if marker in div_classes or marker in div_html:
            return True
    # Check for "Sponsored" text in small labels
    sponsored_labels = div.find_all(
        string=re.compile(r'\bSponsored\b|\bGesponsert\b|\bSponsorisé\b', re.IGNORECASE)
    )
    return bool(sponsored_labels)


def _is_captcha(html):
    """Check if the response is a CAPTCHA or block page."""
    captcha_markers = [
        'Enter the characters you see below',
        "Sorry, we just need to make sure you're not a robot",
        '/errors/validateCaptcha',
        'Type the characters you see in this image',
    ]
    html_lower = html.lower()
    return any(m.lower() in html_lower for m in captcha_markers)


def _empty_result():
    """Return an empty result dict."""
    return {
        'results': [],
        'organic_count': 0,
        'total_results_text': '',
        'competition_count': None,
        'avg_bsr_top10': None,
        'median_reviews': None,
        'ku_ratio': 0.0,
        'top_asins': [],
    }


class AmazonSearchCollector:
    """Thin class wrapper around module-level functions for use by keyword_engine."""

    def __init__(self, marketplace='us'):
        self.marketplace = marketplace

    def probe_competition(self, keyword, top_n=10):
        return probe_competition(keyword, marketplace=self.marketplace, top_n=top_n)

    def search(self, keyword, max_results=10, page=1):
        return search_kindle(keyword, marketplace=self.marketplace,
                             max_results=max_results, page=page)

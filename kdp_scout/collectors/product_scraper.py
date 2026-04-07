"""Amazon product page scraper for competitor analysis.

Scrapes Amazon book product pages to extract BSR, pricing, reviews,
categories, page count, and other metadata. Handles multiple page
layouts that Amazon serves and detects CAPTCHA/soft-block pages.

New in this version:
- Kindle Unlimited eligibility detection
- Hardcover price extraction
- Also Bought ASINs (first 10 related books)
- Series name extraction
- Available formats detection (Kindle / Paperback / Hardcover / Audiobook)
- Better BSR multi-category parsing
- ASIN-level review histogram (star breakdown)
- Publication date normalization
"""

import re
import json
import logging

import requests
from bs4 import BeautifulSoup

from kdp_scout.http_client import fetch, get_browser_headers
from kdp_scout.rate_limiter import registry as rate_registry
from kdp_scout.config import Config

logger = logging.getLogger(__name__)

PRODUCT_URL = 'https://www.amazon.com/dp/{asin}'


class CaptchaDetected(Exception):
    """Raised when Amazon serves a CAPTCHA or soft-block page."""
    pass


class ProductScraper:
    """Scrapes Amazon product pages for book metadata.

    Uses the shared HTTP client with rate limiting and user-agent rotation.
    Handles multiple Amazon page layouts by trying multiple selectors
    for each data field.
    """

    def __init__(self):
        """Initialize the scraper and register the rate limiter."""
        rate_registry.get_limiter('product_page', rate=Config.PRODUCT_SCRAPE_RATE_LIMIT)

    def scrape_product(self, asin):
        """Scrape an Amazon product page for book data.

        Args:
            asin: Amazon Standard Identification Number.

        Returns:
            Dict with product data fields:
                - title: str or None
                - author: str or None
                - bsr_overall: int or None
                - bsr_categories: dict (category_name -> rank) or {}
                - price_kindle: float or None
                - price_paperback: float or None
                - price_hardcover: float or None
                - review_count: int or None
                - avg_rating: float or None
                - page_count: int or None
                - categories: list of category path strings
                - publication_date: str or None
                - description: str or None
                - ku_eligible: bool
                - series_name: str or None
                - also_bought_asins: list of str
                - formats_available: list of str
                - review_histogram: dict {1: int, 2: int, 3: int, 4: int, 5: int}
                - language: str or None
                - publisher: str or None

        Raises:
            CaptchaDetected: If Amazon serves a CAPTCHA page.
            requests.RequestException: On network failure after retries.
        """
        rate_registry.acquire('product_page')

        url = PRODUCT_URL.format(asin=asin)
        logger.info(f'Scraping product page: {url}')

        try:
            response = fetch(url, headers=get_browser_headers())
        except (requests.Timeout, requests.ConnectionError) as e:
            logger.error(f'Network error scraping ASIN {asin}: {e}')
            return None
        except requests.RequestException as e:
            logger.error(f'Request error scraping ASIN {asin}: {e}')
            return None

        if response.status_code == 403:
            logger.warning(f'Amazon blocked request (403) for ASIN {asin}')
            raise CaptchaDetected(
                'Amazon returned 403 Forbidden. Try again later or use a proxy.'
            )

        if response.status_code != 200:
            logger.warning(f'Product page returned {response.status_code} for ASIN {asin}')
            return None

        html = response.text
        if not html or len(html) < 100:
            logger.warning(f'Empty or truncated response for ASIN {asin}')
            return None

        self._check_for_captcha(html)

        soup = BeautifulSoup(html, 'html.parser')

        data = {
            'asin': asin,
            'title': self._parse_title(soup),
            'author': self._parse_author(soup),
            'bsr_overall': None,
            'bsr_categories': {},
            'price_kindle': self._parse_kindle_price(soup),
            'price_paperback': self._parse_paperback_price(soup),
            'price_hardcover': self._parse_hardcover_price(soup),
            'review_count': self._parse_review_count(soup),
            'avg_rating': self._parse_avg_rating(soup),
            'page_count': self._parse_page_count(soup),
            'categories': self._parse_categories(soup),
            'publication_date': self._parse_publication_date(soup),
            'description': self._parse_description(soup),
            'ku_eligible': self._parse_ku_eligible(soup, html),
            'series_name': self._parse_series_name(soup),
            'also_bought_asins': self._parse_also_bought_asins(soup),
            'formats_available': self._parse_formats_available(soup),
            'review_histogram': self._parse_review_histogram(soup),
            'language': self._parse_language(soup),
            'publisher': self._parse_publisher(soup),
        }

        bsr_overall, bsr_categories = self._parse_bsr(soup)
        data['bsr_overall'] = bsr_overall
        data['bsr_categories'] = bsr_categories

        logger.info(
            f'Scraped ASIN {asin}: title="{data["title"]}", '
            f'BSR={data["bsr_overall"]}, '
            f'reviews={data["review_count"]}, '
            f'rating={data["avg_rating"]}, '
            f'KU={data["ku_eligible"]}, '
            f'series={data["series_name"]}'
        )

        return data

    def _check_for_captcha(self, html):
        """Check if the page is a CAPTCHA or soft-block response."""
        captcha_markers = [
            'Enter the characters you see below',
            'Sorry, we just need to make sure you\'re not a robot',
            'api-services-support@amazon.com',
            'Type the characters you see in this image',
            '/errors/validateCaptcha',
        ]
        html_lower = html.lower()
        for marker in captcha_markers:
            if marker.lower() in html_lower:
                logger.warning('CAPTCHA detected on Amazon product page')
                raise CaptchaDetected(
                    'Amazon is requesting CAPTCHA verification. '
                    'Try again later or use a proxy.'
                )

    # ── Title & Author ────────────────────────────────────────────────

    def _parse_title(self, soup):
        """Extract the book title."""
        for selector in ['#ebooksProductTitle', '#productTitle']:
            el = soup.select_one(selector)
            if el:
                return el.get_text(strip=True)

        meta = soup.find('meta', attrs={'name': 'title'})
        if meta and meta.get('content'):
            return meta['content'].strip()

        return None

    def _parse_author(self, soup):
        """Extract the author name."""
        byline = soup.select_one('#bylineInfo')
        if byline:
            author_link = byline.select_one('.author a, a.contributorNameID')
            if author_link:
                return author_link.get_text(strip=True)
            text = byline.get_text(strip=True)
            text = re.sub(r'^by\s+', '', text, flags=re.IGNORECASE)
            if text:
                return text.split('(')[0].strip()

        author_el = soup.select_one('.author a')
        if author_el:
            return author_el.get_text(strip=True)

        return None

    # ── BSR parsing ───────────────────────────────────────────────────

    def _parse_bsr(self, soup):
        """Extract BSR overall and category rankings."""
        bsr_overall = None
        bsr_categories = {}

        details = soup.select_one('#productDetails_detailBullets_sections1')
        if details:
            bsr_overall, bsr_categories = self._parse_bsr_from_table(details)

        if bsr_overall is None:
            bullets = soup.select_one('#detailBulletsWrapper_feature_div')
            if bullets:
                bsr_overall, bsr_categories = self._parse_bsr_from_bullets(bullets)

        if bsr_overall is None:
            detail_section = soup.select_one('#detailBullets_feature_div')
            if detail_section:
                bsr_overall, bsr_categories = self._parse_bsr_from_bullets(detail_section)

        if bsr_overall is None:
            bsr_overall, bsr_categories = self._parse_bsr_from_text(soup)

        return bsr_overall, bsr_categories

    def _parse_bsr_from_table(self, table):
        bsr_overall = None
        bsr_categories = {}
        for row in table.select('tr'):
            header = row.select_one('th')
            if header and 'best sellers rank' in header.get_text().lower():
                value_td = row.select_one('td')
                if value_td:
                    text = value_td.get_text()
                    bsr_overall, bsr_categories = self._extract_bsr_numbers(text)
                break
        return bsr_overall, bsr_categories

    def _parse_bsr_from_bullets(self, container):
        bsr_overall = None
        bsr_categories = {}
        text = container.get_text()
        bsr_match = re.search(
            r'Best\s*Sellers?\s*Rank[:\s]*(.*?)(?=Customer\s*Reviews|$)',
            text, re.IGNORECASE | re.DOTALL,
        )
        if bsr_match:
            bsr_text = bsr_match.group(1)
            bsr_overall, bsr_categories = self._extract_bsr_numbers(bsr_text)
        return bsr_overall, bsr_categories

    def _parse_bsr_from_text(self, soup):
        bsr_overall = None
        bsr_categories = {}
        text = soup.get_text()
        overall_match = re.search(
            r'#([\d,]+)\s+in\s+(?:Amazon\s+)?(?:Kindle\s+Store|Books)',
            text, re.IGNORECASE,
        )
        if overall_match:
            bsr_overall = int(overall_match.group(1).replace(',', ''))

        cat_matches = re.finditer(
            r'#([\d,]+)\s+in\s+([A-Z][^(#\n]+?)(?:\s*\(|$|\n)',
            text,
        )
        for match in cat_matches:
            rank = int(match.group(1).replace(',', ''))
            category = match.group(2).strip()
            if category.lower() not in ('kindle store', 'books'):
                bsr_categories[category] = rank

        return bsr_overall, bsr_categories

    def _extract_bsr_numbers(self, text):
        bsr_overall = None
        bsr_categories = {}
        matches = re.finditer(
            r'#([\d,]+)\s+in\s+([^(#\n]+?)(?:\s*\(|$|\n|#)',
            text,
        )
        for match in matches:
            rank = int(match.group(1).replace(',', ''))
            category = match.group(2).strip()
            if category.lower() in ('kindle store', 'books', 'amazon books'):
                if bsr_overall is None or rank < bsr_overall:
                    bsr_overall = rank
            else:
                bsr_categories[category] = rank
        return bsr_overall, bsr_categories

    # ── Price parsing ─────────────────────────────────────────────────

    def _parse_kindle_price(self, soup):
        """Extract the Kindle price."""
        for selector in [
            '#kindle-price',
            '.kindle-price .a-size-base',
            '#price',
            '.kindle-price',
            '#digital-list-price .a-color-price',
            'span.kindle-price span',
        ]:
            el = soup.select_one(selector)
            if el:
                price = self._extract_price(el.get_text())
                if price is not None:
                    return price

        for section in soup.select('.swatchElement'):
            text = section.get_text().lower()
            if 'kindle' in text:
                price = self._extract_price(text)
                if price is not None:
                    return price

        return None

    def _parse_paperback_price(self, soup):
        """Extract the paperback price."""
        for section in soup.select('.swatchElement'):
            text = section.get_text().lower()
            if 'paperback' in text:
                price = self._extract_price(text)
                if price is not None:
                    return price

        for selector in [
            '#paperback_meta_binding_price',
            '#a-autoid-3-announce .a-color-price',
        ]:
            el = soup.select_one(selector)
            if el:
                price = self._extract_price(el.get_text())
                if price is not None:
                    return price

        return None

    def _parse_hardcover_price(self, soup):
        """Extract the hardcover price."""
        for section in soup.select('.swatchElement'):
            text = section.get_text().lower()
            if 'hardcover' in text or 'hardback' in text:
                price = self._extract_price(text)
                if price is not None:
                    return price

        for selector in [
            '#hardcover_meta_binding_price',
            '#a-autoid-2-announce .a-color-price',
        ]:
            el = soup.select_one(selector)
            if el:
                price = self._extract_price(el.get_text())
                if price is not None:
                    return price

        return None

    # ── Reviews ───────────────────────────────────────────────────────

    def _parse_review_count(self, soup):
        """Extract the total review count."""
        el = soup.select_one('#acrCustomerReviewText')
        if el:
            match = re.search(r'([\d,]+)', el.get_text())
            if match:
                return int(match.group(1).replace(',', ''))

        el = soup.select_one('#acrCustomerReviewLink span')
        if el:
            match = re.search(r'([\d,]+)', el.get_text())
            if match:
                return int(match.group(1).replace(',', ''))

        return None

    def _parse_avg_rating(self, soup):
        """Extract the average star rating."""
        el = soup.select_one('#acrPopover')
        if el:
            title = el.get('title', '')
            match = re.search(r'([\d.]+)', title)
            if match:
                return float(match.group(1))

        el = soup.select_one('.a-icon-star .a-icon-alt')
        if el:
            match = re.search(r'([\d.]+)', el.get_text())
            if match:
                return float(match.group(1))

        el = soup.select_one('#averageCustomerReviews .a-icon-alt')
        if el:
            match = re.search(r'([\d.]+)', el.get_text())
            if match:
                return float(match.group(1))

        return None

    def _parse_review_histogram(self, soup):
        """Extract the star rating histogram (count per star level).

        Returns:
            Dict {1: count, 2: count, 3: count, 4: count, 5: count}
            or empty dict if not parseable.
        """
        histogram = {}
        text = soup.get_text()

        # Look for percentage or count patterns near star labels
        star_patterns = [
            (5, r'5\s*(?:star|out of 5)[^\d]*(\d+)\s*(?:percent|%)'),
            (4, r'4\s*star[^\d]*(\d+)\s*(?:percent|%)'),
            (3, r'3\s*star[^\d]*(\d+)\s*(?:percent|%)'),
            (2, r'2\s*star[^\d]*(\d+)\s*(?:percent|%)'),
            (1, r'1\s*star[^\d]*(\d+)\s*(?:percent|%)'),
        ]

        for stars, pattern in star_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    histogram[stars] = int(match.group(1))
                except ValueError:
                    pass

        return histogram

    # ── New fields ────────────────────────────────────────────────────

    def _parse_ku_eligible(self, soup, html):
        """Detect if the book is available on Kindle Unlimited.

        Returns:
            True if KU eligible, False otherwise.
        """
        ku_markers = [
            'kindle unlimited',
            'read for free',
            'free with your audible trial',
            'ku eligible',
            'included with kindle unlimited',
            'read and listen for free',
            'lire gratuitement',
            'inclus dans kindle unlimited',
        ]
        html_lower = html.lower()
        if any(m in html_lower for m in ku_markers):
            return True

        # Check for KU badge/button
        for sel in [
            '#a-autoid-0-announce',
            'span[id*="borrowButton"]',
            '#borrow-button',
            '#read-for-free',
            'a#borrowLink',
            'span.kindle-unlimited-badge',
        ]:
            el = soup.select_one(sel)
            if el:
                return True

        return False

    def _parse_series_name(self, soup):
        """Extract the series name if the book belongs to a series.

        Returns:
            Series name string or None.
        """
        # Check the product detail bullets
        text = soup.get_text()

        # Pattern: "(Series Name, Book 3)" in title or details
        series_match = re.search(
            r'\(([^)]{3,80}(?:Series|Saga|Trilogy|Duology|Chronicles|Universe|World)[^)]{0,30})\)',
            text, re.IGNORECASE,
        )
        if series_match:
            return series_match.group(1).strip()

        # Pattern: "Book N of M: Series Name"
        series_match = re.search(
            r'Book\s+\d+\s+(?:of\s+\d+\s+)?(?:in|of)?\s*(?:the\s+)?([A-Z][A-Za-z\s]{3,50}?)\s*(?:Series|Saga|Trilogy)',
            text, re.IGNORECASE,
        )
        if series_match:
            return series_match.group(1).strip()

        # Check series widget
        for sel in [
            '#series-childAsin-widget_feature_div a',
            '#seriesAsinList a',
            '.series-landing-page-link',
        ]:
            el = soup.select_one(sel)
            if el:
                text_el = el.get_text(strip=True)
                if text_el and len(text_el) > 2:
                    return text_el

        return None

    def _parse_also_bought_asins(self, soup):
        """Extract ASINs from the 'Also Bought' / 'Also Viewed' carousels.

        Returns:
            List of up to 10 ASIN strings.
        """
        asins = []
        seen = set()

        carousel_selectors = [
            'div[id*="also-bought"] a[href]',
            'div[id*="customers-who-bought"] a[href]',
            'div[id*="sims"] a[href]',
            '.a-carousel-card a[href*="/dp/"]',
            'li.a-carousel-card a[href]',
        ]

        for sel in carousel_selectors:
            for link in soup.select(sel):
                href = link.get('href', '')
                asin_match = re.search(r'/(?:dp|product)/([A-Z0-9]{10})', href)
                if asin_match:
                    asin = asin_match.group(1)
                    if asin not in seen:
                        seen.add(asin)
                        asins.append(asin)
                if len(asins) >= 10:
                    break
            if len(asins) >= 10:
                break

        return asins

    def _parse_formats_available(self, soup):
        """Detect which formats are available for this book.

        Returns:
            List of format strings like ['Kindle', 'Paperback', 'Hardcover', 'Audiobook']
        """
        formats = []
        text = soup.get_text().lower()

        format_markers = {
            'Kindle': ['kindle edition', 'kindle e-book'],
            'Paperback': ['paperback'],
            'Hardcover': ['hardcover', 'hardback'],
            'Audiobook': ['audible audiobook', 'audio cd', 'mp3 cd'],
            'Spiral-bound': ['spiral-bound'],
            'Board book': ['board book'],
            'Library Binding': ['library binding'],
        }

        # Also check format switcher
        swatch_section = soup.select('.swatchElement')
        swatch_text = ' '.join(el.get_text().lower() for el in swatch_section)

        combined = text + ' ' + swatch_text

        for fmt, markers in format_markers.items():
            if any(m in combined for m in markers):
                formats.append(fmt)

        return formats if formats else ['Kindle']  # Default

    def _parse_language(self, soup):
        """Extract the book language."""
        text = soup.get_text()
        match = re.search(r'Language\s*[:\s]+([A-Za-z]+)', text, re.IGNORECASE)
        if match:
            lang = match.group(1).strip()
            if lang.lower() not in ('unknown', 'other'):
                return lang
        return None

    def _parse_publisher(self, soup):
        """Extract the publisher name."""
        text = soup.get_text()
        match = re.search(r'Publisher\s*[:\s]+([^;\n(]+?)(?:\s*\(|;|\n)', text, re.IGNORECASE)
        if match:
            pub = match.group(1).strip()
            if pub and len(pub) > 2:
                return pub
        return None

    # ── Page count, categories, publication date, description ─────────

    def _parse_page_count(self, soup):
        """Extract the page count from product details."""
        text = soup.get_text()
        match = re.search(
            r'(?:Print\s+[Ll]ength|Pages)[:\s]*([\d,]+)\s*pages?',
            text, re.IGNORECASE,
        )
        if match:
            return int(match.group(1).replace(',', ''))

        match = re.search(r'(\d+)\s+pages?', text, re.IGNORECASE)
        if match:
            count = int(match.group(1))
            if 10 <= count <= 5000:
                return count

        return None

    def _parse_categories(self, soup):
        """Extract category paths from breadcrumbs or BSR section."""
        categories = []

        breadcrumb = soup.select('#wayfinding-breadcrumbs_feature_div a')
        if breadcrumb:
            path = ' > '.join(a.get_text(strip=True) for a in breadcrumb)
            if path:
                categories.append(path)

        _, bsr_categories = self._parse_bsr(soup)
        for cat_name in bsr_categories:
            if cat_name not in categories:
                categories.append(cat_name)

        return categories

    def _parse_publication_date(self, soup):
        """Extract the publication date."""
        text = soup.get_text()

        match = re.search(
            r'Publication\s+[Dd]ate[:\s]*([A-Z][a-z]+\s+\d{1,2},\s*\d{4})',
            text,
        )
        if match:
            return match.group(1).strip()

        # ISO format
        match = re.search(r'Publication\s+[Dd]ate[:\s]*(\d{4}-\d{2}-\d{2})', text)
        if match:
            return match.group(1).strip()

        match = re.search(
            r'Publisher[:\s].*?\(([A-Z][a-z]+\s+\d{1,2},\s*\d{4})\)',
            text,
        )
        if match:
            return match.group(1).strip()

        return None

    def _parse_description(self, soup):
        """Extract the book description."""
        desc = soup.select_one('#bookDescription_feature_div .a-expander-content')
        if desc:
            return desc.get_text(strip=True)

        for selector in [
            '#bookDescription_feature_div',
            '#productDescription',
            '#book_description_expander',
        ]:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(strip=True)
                if text:
                    return text

        return None

    # ── Price utility ─────────────────────────────────────────────────

    def _extract_price(self, text):
        """Extract a dollar price from text."""
        match = re.search(r'\$\s*([\d,]+\.?\d*)', text)
        if match:
            try:
                price = float(match.group(1).replace(',', ''))
                return price if price > 0 else None
            except ValueError:
                return None
        return None

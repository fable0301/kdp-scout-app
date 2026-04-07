"""Configuration management for KDP Scout.

Loads settings from .env file with sensible defaults for all options.

New in this version:
- SEARCH_COLLECTOR_RATE_LIMIT: rate for AmazonSearchCollector (competition probe)
- DEFAULT_MARKETPLACE: default marketplace code for all collectors
- MULTI_MARKETPLACE_LIST: default list of marketplaces for multi-MP mining
- TRENDING_RATE_LIMIT: rate for Movers & Shakers / Most Wished For scraping
- ALSO_BOUGHT_RATE_LIMIT: rate for also-bought scraping
- BSR_HISTORY_DAYS: default window for BSR history charts
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv


_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / '.env')


class Config:
    """Central configuration for KDP Scout."""

    # Database
    DB_PATH = os.getenv('DB_PATH', 'data/kdp_scout.db')

    # API Keys
    DATAFORSEO_LOGIN = os.getenv('DATAFORSEO_LOGIN', '')
    DATAFORSEO_API_KEY = os.getenv('DATAFORSEO_API_KEY', '')
    GOOGLE_BOOKS_API_KEY = os.environ.get('GOOGLE_BOOKS_API_KEY', '')

    # Proxy
    PROXY_URL = os.getenv('PROXY_URL', '')

    # Rate limits (seconds between requests)
    AUTOCOMPLETE_RATE_LIMIT = float(os.getenv('AUTOCOMPLETE_RATE_LIMIT', '1.5'))
    PRODUCT_SCRAPE_RATE_LIMIT = float(os.getenv('PRODUCT_SCRAPE_RATE_LIMIT', '2.0'))
    SEARCH_PROBE_RATE_LIMIT = float(os.getenv('SEARCH_PROBE_RATE_LIMIT', '2.0'))
    DATAFORSEO_RATE_LIMIT = float(os.getenv('DATAFORSEO_RATE_LIMIT', '0.5'))
    SEARCH_COLLECTOR_RATE_LIMIT = float(os.getenv('SEARCH_COLLECTOR_RATE_LIMIT', '2.5'))
    TRENDING_RATE_LIMIT = float(os.getenv('TRENDING_RATE_LIMIT', '3.0'))
    ALSO_BOUGHT_RATE_LIMIT = float(os.getenv('ALSO_BOUGHT_RATE_LIMIT', '2.5'))

    # Marketplace defaults
    DEFAULT_MARKETPLACE = os.getenv('DEFAULT_MARKETPLACE', 'us')
    MULTI_MARKETPLACE_LIST = os.getenv(
        'MULTI_MARKETPLACE_LIST', 'us,uk,de,ca'
    ).split(',')

    # BSR history window for charts
    BSR_HISTORY_DAYS = int(os.getenv('BSR_HISTORY_DAYS', '90'))

    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')

    # User agents for rotation
    USER_AGENTS = [
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1',
        'Mozilla/5.0 (iPad; CPU OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1',
    ]

    # Amazon marketplace URL map
    MARKETPLACE_DOMAINS = {
        'us': 'www.amazon.com',
        'uk': 'www.amazon.co.uk',
        'de': 'www.amazon.de',
        'fr': 'www.amazon.fr',
        'ca': 'www.amazon.ca',
        'au': 'www.amazon.com.au',
        'jp': 'www.amazon.co.jp',
        'es': 'www.amazon.es',
        'it': 'www.amazon.it',
        'mx': 'www.amazon.com.mx',
        'in': 'www.amazon.in',
    }

    # Amazon autocomplete search department codes
    DEPARTMENTS = {
        'kindle': 'digital-text',
        'books': 'stripbooks',
        'all': 'aps',
    }

    @classmethod
    def get_db_path(cls):
        """Return absolute path to the database file."""
        db_path = Path(cls.DB_PATH)
        if not db_path.is_absolute():
            db_path = _project_root / db_path
        return str(db_path)

    @classmethod
    def get_marketplace_domain(cls, marketplace='us'):
        """Return Amazon domain for a 2-letter marketplace code."""
        return cls.MARKETPLACE_DOMAINS.get(marketplace.lower(), 'www.amazon.com')

    @classmethod
    def setup_logging(cls):
        """Configure logging based on settings."""
        logging.basicConfig(
            level=getattr(logging, cls.LOG_LEVEL.upper(), logging.INFO),
            format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )

    @classmethod
    def as_dict(cls):
        """Return configuration as a dictionary for display."""
        return {
            'DB_PATH': cls.get_db_path(),
            'DATAFORSEO_LOGIN': cls.DATAFORSEO_LOGIN or '(not set)',
            'DATAFORSEO_API_KEY': '***' if cls.DATAFORSEO_API_KEY else '(not set)',
            'PROXY_URL': cls.PROXY_URL or '(not set)',
            'AUTOCOMPLETE_RATE_LIMIT': f'{cls.AUTOCOMPLETE_RATE_LIMIT}s',
            'PRODUCT_SCRAPE_RATE_LIMIT': f'{cls.PRODUCT_SCRAPE_RATE_LIMIT}s',
            'SEARCH_PROBE_RATE_LIMIT': f'{cls.SEARCH_PROBE_RATE_LIMIT}s',
            'SEARCH_COLLECTOR_RATE_LIMIT': f'{cls.SEARCH_COLLECTOR_RATE_LIMIT}s',
            'TRENDING_RATE_LIMIT': f'{cls.TRENDING_RATE_LIMIT}s',
            'ALSO_BOUGHT_RATE_LIMIT': f'{cls.ALSO_BOUGHT_RATE_LIMIT}s',
            'DATAFORSEO_RATE_LIMIT': f'{cls.DATAFORSEO_RATE_LIMIT}s',
            'DEFAULT_MARKETPLACE': cls.DEFAULT_MARKETPLACE,
            'MULTI_MARKETPLACE_LIST': ','.join(cls.MULTI_MARKETPLACE_LIST),
            'BSR_HISTORY_DAYS': str(cls.BSR_HISTORY_DAYS),
            'LOG_LEVEL': cls.LOG_LEVEL,
            'USER_AGENTS': f'{len(cls.USER_AGENTS)} configured',
        }

    # Goodreads / Open Library rate limits
    GOODREADS_RATE_LIMIT = 2.0   # seconds between Goodreads requests
    OPENLIBRARY_RATE_LIMIT = 1.0 # seconds between Open Library requests

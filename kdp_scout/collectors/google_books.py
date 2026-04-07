"""Google Books API collector for KDP research.

Uses the free Google Books API (1000 req/day with API key, limited without).
Provides book search, niche saturation analysis, and publication timeline.
"""

import logging
import re
from datetime import datetime

from kdp_scout.http_client import fetch
from kdp_scout.rate_limiter import registry as rate_registry

logger = logging.getLogger(__name__)

API_BASE = "https://www.googleapis.com/books/v1/volumes"


def _get_api_key():
    """Get Google Books API key from config, or None."""
    try:
        from kdp_scout.config import Config
        return getattr(Config, "GOOGLE_BOOKS_API_KEY", None) or None
    except Exception:
        return None


def _api_request(params, max_results=40):
    """Make a Google Books API request."""
    rate_registry.get_limiter("google_books", rate=0.5)
    rate_registry.acquire("google_books")

    params["maxResults"] = min(max_results, 40)
    api_key = _get_api_key()
    if api_key:
        params["key"] = api_key

    try:
        response = fetch(API_BASE, params=params)
        if response.status_code == 200:
            return response.json()
        logger.warning(f"Google Books API returned {response.status_code}")
        return None
    except Exception as e:
        logger.error(f"Google Books API error: {e}")
        return None


def _parse_volume(item):
    """Parse a Google Books volume item into a clean dict."""
    info = item.get("volumeInfo", {})
    sale = item.get("saleInfo", {})

    authors = info.get("authors", [])
    categories = info.get("categories", [])
    identifiers = info.get("industryIdentifiers", [])
    isbn = ""
    for ident in identifiers:
        if ident.get("type") in ("ISBN_13", "ISBN_10"):
            isbn = ident.get("identifier", "")
            break

    published = info.get("publishedDate", "")
    year = ""
    if published:
        m = re.match(r"(\d{4})", published)
        if m:
            year = m.group(1)

    return {
        "title": info.get("title", ""),
        "author": ", ".join(authors) if authors else "",
        "publisher": info.get("publisher", ""),
        "published": published,
        "year": year,
        "pages": info.get("pageCount", ""),
        "categories": ", ".join(categories) if categories else "",
        "rating": info.get("averageRating", ""),
        "ratings_count": info.get("ratingsCount", 0),
        "language": info.get("language", ""),
        "isbn": isbn,
        "description": (info.get("description", "") or "")[:200],
        "preview": info.get("previewLink", ""),
        "is_ebook": sale.get("isEbook", False),
        "price": sale.get("listPrice", {}).get("amount", ""),
    }


def search_books(query, order_by="relevance", lang="en",
                 max_results=40, progress_callback=None, cancel_check=None):
    """Search Google Books for a query.

    Args:
        query: Search query (supports subject:, intitle:, inauthor: prefixes)
        order_by: 'relevance' or 'newest'
        lang: Language filter (e.g., 'en')
        max_results: Max results (up to 40 per request, paginates up to 120)

    Returns list of parsed volume dicts.
    """
    all_results = []
    start_index = 0
    pages_to_fetch = min(3, (max_results + 39) // 40)

    for page in range(pages_to_fetch):
        if cancel_check and cancel_check():
            break

        params = {
            "q": query,
            "orderBy": order_by,
            "langRestrict": lang,
            "printType": "books",
            "startIndex": start_index,
        }

        data = _api_request(params, max_results=40)
        if not data or "items" not in data:
            break

        for item in data["items"]:
            vol = _parse_volume(item)
            if vol["title"]:
                all_results.append(vol)

        start_index += 40
        if progress_callback:
            progress_callback(page + 1, pages_to_fetch)

        total_items = data.get("totalItems", 0)
        if start_index >= total_items:
            break

    logger.info(f"Google Books search \"{query}\": {len(all_results)} results")
    return all_results


def analyze_niche(subject, progress_callback=None, cancel_check=None):
    """Analyze a niche/category for saturation and opportunity.

    Returns dict with metrics and book list.
    """
    query = f"subject:{subject}"
    params = {
        "q": query,
        "orderBy": "relevance",
        "langRestrict": "en",
        "printType": "books",
        "maxResults": 40,
    }

    data = _api_request(params)
    if not data:
        return {"total_books": 0, "books": [], "metrics": {}}

    total = data.get("totalItems", 0)
    books = []
    for item in data.get("items", []):
        vol = _parse_volume(item)
        if vol["title"]:
            books.append(vol)

    if progress_callback:
        progress_callback(1, 2)

    # Get newest books for recency analysis
    params_new = {
        "q": query,
        "orderBy": "newest",
        "langRestrict": "en",
        "printType": "books",
        "maxResults": 40,
    }
    if cancel_check and cancel_check():
        return {"total_books": total, "books": books, "metrics": {}}

    data_new = _api_request(params_new)
    new_books = []
    if data_new and "items" in data_new:
        for item in data_new["items"]:
            vol = _parse_volume(item)
            if vol["title"]:
                new_books.append(vol)

    if progress_callback:
        progress_callback(2, 2)

    # Calculate metrics
    current_year = datetime.now().year
    recent_count = sum(1 for b in new_books if b.get("year") and str(b["year"]) >= str(current_year - 1))
    avg_pages = 0
    page_counts = [int(b["pages"]) for b in books + new_books if b.get("pages")]
    if page_counts:
        avg_pages = sum(page_counts) // len(page_counts)

    ratings = [float(b["rating"]) for b in books if b.get("rating")]
    avg_rating = round(sum(ratings) / len(ratings), 1) if ratings else 0

    metrics = {
        "total_books_in_niche": total,
        "recent_publications": recent_count,
        "avg_pages": avg_pages,
        "avg_rating": avg_rating,
        "has_ebooks": sum(1 for b in books if b.get("is_ebook")),
        "saturation": "High" if total > 10000 else "Medium" if total > 1000 else "Low",
    }

    combined = {b["title"]: b for b in new_books}
    for b in books:
        if b["title"] not in combined:
            combined[b["title"]] = b

    return {
        "total_books": total,
        "books": list(combined.values()),
        "metrics": metrics,
    }


def get_publication_timeline(subject, progress_callback=None, cancel_check=None):
    """Get newest books in a niche to analyze publication velocity.

    Returns list of book dicts sorted by publication date (newest first).
    """
    return search_books(
        f"subject:{subject}",
        order_by="newest",
        max_results=120,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )

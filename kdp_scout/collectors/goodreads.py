"""Goodreads & Open Library collector for KDP niche research.

Scrapes public Goodreads pages for reader sentiment data (ratings, shelves,
want-to-read counts, similar books) and uses Open Library API for metadata.

Speed optimisations
-------------------
- ThreadPoolExecutor for parallel book-detail fetching (like discovery.py)
- Session reuse via http_client.get_session()
- Configurable rate-limiting via rate_limiter registry
"""

import logging
import re
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus
from bs4 import BeautifulSoup
from kdp_scout.http_client import fetch, get_browser_headers, get_session
from kdp_scout.rate_limiter import registry as rate_registry

logger = logging.getLogger(__name__)

GOODREADS_BASE = "https://www.goodreads.com"
OPENLIBRARY_BASE = "https://openlibrary.org"

# Max parallel workers for Goodreads (conservative to avoid blocks)
_GR_WORKERS = 4
# Max parallel workers for Open Library (generous — official API)
_OL_WORKERS = 6


# ---------------------------------------------------------------------------
# Rate limiters
# ---------------------------------------------------------------------------

def _init_limiters():
    """Ensure rate limiters are registered (idempotent)."""
    rate_registry.get_limiter("goodreads", rate=2.0)   # 1 req per 2s
    rate_registry.get_limiter("openlibrary", rate=0.5)  # 1 req per 0.5s


def _gr_fetch(url):
    """Fetch a Goodreads page with browser headers and rate limiting."""
    _init_limiters()
    rate_registry.acquire("goodreads")
    headers = get_browser_headers()
    headers['Referer'] = 'https://www.goodreads.com/'
    try:
        resp = fetch(url, headers=headers)
        if resp.status_code == 200:
            return resp.text
        logger.warning(f"Goodreads returned {resp.status_code} for {url}")
        return None
    except Exception as e:
        logger.error(f"Goodreads fetch error: {e}")
        return None


def _ol_api(endpoint, params=None):
    """Call Open Library API with rate limiting."""
    _init_limiters()
    rate_registry.acquire("openlibrary")
    url = f"{OPENLIBRARY_BASE}{endpoint}"
    try:
        resp = fetch(url, params=params)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        logger.error(f"Open Library API error: {e}")
        return None


# ---------------------------------------------------------------------------
# Goodreads helpers
# ---------------------------------------------------------------------------

def _parse_minirating(text):
    """Parse a minirating string like '4.12 avg rating — 1,234 ratings'."""
    rating = 0.0
    count = 0
    try:
        m = re.search(r'([\d.]+)\s*avg\s*rating', text)
        if m:
            rating = float(m.group(1))
        m = re.search(r'([\d,]+)\s*rating', text)
        if m:
            count = int(m.group(1).replace(',', ''))
    except Exception:
        pass
    return rating, count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_goodreads(query, max_results=20, progress_callback=None, cancel_check=None):
    """Search Goodreads for books matching *query*.

    Returns a list of dicts with keys:
        title, author, rating, ratings_count, url, goodreads_id, cover_url
    """
    encoded = quote_plus(query)
    url = f"{GOODREADS_BASE}/search?q={encoded}&search_type=books"
    html = _gr_fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    rows = soup.select('tr[itemtype="http://schema.org/Book"]')
    if not rows:
        rows = soup.select('table.tableList tr')

    for i, row in enumerate(rows[:max_results]):
        if cancel_check and cancel_check():
            break
        if progress_callback:
            progress_callback(i + 1, min(len(rows), max_results))

        book = {
            "title": "",
            "author": "",
            "rating": 0.0,
            "ratings_count": 0,
            "url": "",
            "goodreads_id": "",
            "cover_url": "",
        }

        try:
            title_el = row.select_one('a.bookTitle') or row.select_one('.bookTitle')
            if title_el:
                book["title"] = title_el.get_text(strip=True)
                href = title_el.get("href", "")
                book["url"] = f"{GOODREADS_BASE}{href}" if href.startswith("/") else href
                m = re.search(r'/show/(\d+)', href)
                if m:
                    book["goodreads_id"] = m.group(1)
        except Exception:
            pass

        try:
            author_el = row.select_one('a.authorName') or row.select_one('.authorName')
            if author_el:
                book["author"] = author_el.get_text(strip=True)
        except Exception:
            pass

        try:
            mini = row.select_one('span.minirating') or row.select_one('.minirating')
            if mini:
                book["rating"], book["ratings_count"] = _parse_minirating(mini.get_text())
        except Exception:
            pass

        try:
            img = row.select_one('img')
            if img:
                book["cover_url"] = img.get("src", "")
        except Exception:
            pass

        if book["title"]:
            results.append(book)

    return results


def get_book_details(goodreads_url, cancel_check=None):
    """Scrape a single Goodreads book page for detailed info.

    Returns a dict with keys:
        title, author, rating, ratings_count, reviews_count, want_to_read_count,
        shelves, description, pages, published_date, genres, similar_books
    """
    html = _gr_fetch(goodreads_url)
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")

    details = {
        "title": "",
        "author": "",
        "rating": 0.0,
        "ratings_count": 0,
        "reviews_count": 0,
        "want_to_read_count": 0,
        "shelves": [],
        "description": "",
        "pages": 0,
        "published_date": "",
        "genres": [],
        "similar_books": [],
    }

    # Try JSON-LD first
    try:
        ld_script = soup.find('script', type='application/ld+json')
        if ld_script:
            ld = json.loads(ld_script.string)
            details["title"] = ld.get("name", "")
            if "author" in ld:
                authors = ld["author"]
                if isinstance(authors, list):
                    details["author"] = ", ".join(a.get("name", "") for a in authors)
                elif isinstance(authors, dict):
                    details["author"] = authors.get("name", "")
            ar = ld.get("aggregateRating", {})
            details["rating"] = float(ar.get("ratingValue", 0))
            details["ratings_count"] = int(ar.get("ratingCount", 0))
            details["reviews_count"] = int(ar.get("reviewCount", 0))
            details["pages"] = int(ld.get("numberOfPages", 0))
    except Exception:
        pass

    # Title fallback
    if not details["title"]:
        try:
            el = soup.select_one('h1[data-testid="bookTitle"]') or soup.select_one('h1#bookTitle') or soup.find('h1')
            if el:
                details["title"] = el.get_text(strip=True)
        except Exception:
            pass

    # Author fallback
    if not details["author"]:
        try:
            el = soup.select_one('span[data-testid="name"]') or soup.select_one('.authorName')
            if el:
                details["author"] = el.get_text(strip=True)
        except Exception:
            pass

    # Rating fallback
    if not details["rating"]:
        try:
            el = soup.select_one('[data-testid="averageRating"]') or soup.select_one('.RatingStatistics__rating')
            if el:
                details["rating"] = float(el.get_text(strip=True))
        except Exception:
            pass

    # Ratings/reviews count fallback
    if not details["ratings_count"]:
        try:
            el = soup.select_one('[data-testid="ratingsCount"]')
            if el:
                text = el.get_text(strip=True).replace(',', '')
                m = re.search(r'([\d]+)', text)
                if m:
                    details["ratings_count"] = int(m.group(1))
        except Exception:
            pass

    if not details["reviews_count"]:
        try:
            el = soup.select_one('[data-testid="reviewsCount"]')
            if el:
                text = el.get_text(strip=True).replace(',', '')
                m = re.search(r'([\d]+)', text)
                if m:
                    details["reviews_count"] = int(m.group(1))
        except Exception:
            pass

    # Want-to-read count
    try:
        wtr_el = soup.find(string=re.compile(r'want to read', re.I))
        if wtr_el:
            parent_text = wtr_el.parent.get_text() if wtr_el.parent else str(wtr_el)
            m = re.search(r'([\d,]+)', parent_text)
            if m:
                details["want_to_read_count"] = int(m.group(1).replace(',', ''))
    except Exception:
        pass

    # Also try the stats JSON in <script> tags
    try:
        for script in soup.find_all('script'):
            if script.string and 'wantToRead' in script.string:
                m = re.search(r'"wantToRead"\s*:\s*(\d+)', script.string)
                if m:
                    details["want_to_read_count"] = max(details["want_to_read_count"], int(m.group(1)))
                break
    except Exception:
        pass

    # Description
    try:
        desc_el = (
            soup.select_one('[data-testid="description"]')
            or soup.select_one('.BookPageMetadataSection__description')
            or soup.select_one('#description span')
        )
        if desc_el:
            details["description"] = desc_el.get_text(strip=True)[:500]
    except Exception:
        pass

    # Pages fallback
    if not details["pages"]:
        try:
            pages_el = soup.find(string=re.compile(r'\d+\s*pages', re.I))
            if pages_el:
                m = re.search(r'(\d+)\s*pages', pages_el, re.I)
                if m:
                    details["pages"] = int(m.group(1))
        except Exception:
            pass

    # Published date
    try:
        pub_el = soup.select_one('[data-testid="publicationInfo"]')
        if not pub_el:
            pub_el = soup.find(string=re.compile(r'(Published|First published)', re.I))
            if pub_el:
                pub_el = pub_el.parent
        if pub_el:
            details["published_date"] = pub_el.get_text(strip=True)[:100]
    except Exception:
        pass

    # Genres / shelves
    try:
        genre_els = soup.select('[data-testid="genresList"] a') or soup.select('.BookPageMetadataSection__genreButton a') or soup.select('.actionLinkLite.bookPageGenreLink')
        details["genres"] = [g.get_text(strip=True) for g in genre_els[:10]]
    except Exception:
        pass

    # Shelves (reader-defined)
    try:
        shelf_els = soup.select('.shelfStat') or soup.select('.BookPageMetadataSection__shelf')
        shelves = []
        for se in shelf_els[:15]:
            name = se.get_text(strip=True)
            if name:
                shelves.append(name)
        details["shelves"] = shelves if shelves else details["genres"]
    except Exception:
        details["shelves"] = details["genres"]

    # Similar books
    try:
        sim_els = soup.select('.BookCard__title') or soup.select('.similarBooks a')
        details["similar_books"] = [s.get_text(strip=True) for s in sim_els[:8]]
    except Exception:
        pass

    return details


def search_shelves(query, progress_callback=None, cancel_check=None):
    """Search Goodreads lists/shelves for reader-defined sub-niches.

    Returns list of dicts: name, url, books_count, voters
    """
    encoded = quote_plus(query)
    url = f"{GOODREADS_BASE}/search?q={encoded}&search_type=lists"
    html = _gr_fetch(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    list_rows = soup.select('.listImgs') or soup.select('table.tableList tr') or soup.select('.cell')
    if not list_rows:
        list_rows = soup.find_all('a', href=re.compile(r'/list/show/'))

    for i, row in enumerate(list_rows[:30]):
        if cancel_check and cancel_check():
            break
        if progress_callback:
            progress_callback(i + 1, min(len(list_rows), 30))

        item = {"name": "", "url": "", "books_count": 0, "voters": 0}

        try:
            if row.name == 'a':
                item["name"] = row.get_text(strip=True)
                href = row.get("href", "")
                item["url"] = f"{GOODREADS_BASE}{href}" if href.startswith("/") else href
            else:
                link = row.find('a', href=re.compile(r'/list/show/'))
                if link:
                    item["name"] = link.get_text(strip=True)
                    href = link.get("href", "")
                    item["url"] = f"{GOODREADS_BASE}{href}" if href.startswith("/") else href

            text = row.get_text()
            m = re.search(r'([\d,]+)\s*books?', text, re.I)
            if m:
                item["books_count"] = int(m.group(1).replace(',', ''))
            m = re.search(r'([\d,]+)\s*voters?', text, re.I)
            if m:
                item["voters"] = int(m.group(1).replace(',', ''))
        except Exception:
            pass

        if item["name"]:
            results.append(item)

    return results


def analyze_niche_goodreads(query, max_books=10, progress_callback=None,
                            cancel_check=None, log_callback=None):
    """Orchestrator: search Goodreads → get details for top books → aggregate.

    Uses ThreadPoolExecutor to fetch book details in parallel (like discovery.py).

    Returns dict with:
        books: list of book detail dicts
        metrics: aggregated niche metrics
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)

    if progress_callback:
        progress_callback(0, max_books + 1)

    # Step 1: search
    _log(f"🔍 Searching Goodreads for '{query}'...")
    search_results = search_goodreads(query, max_results=max_books, cancel_check=cancel_check)
    if cancel_check and cancel_check():
        return {"books": [], "metrics": {}}

    _log(f"  ✓ Found {len(search_results)} books — fetching details in parallel...")
    if progress_callback:
        progress_callback(1, max_books + 1)

    # Step 2: get details in PARALLEL using ThreadPoolExecutor
    books = []
    urls_to_fetch = [(i, sr) for i, sr in enumerate(search_results[:max_books]) if sr.get("url")]

    def _fetch_one(item):
        idx, sr = item
        if cancel_check and cancel_check():
            return None
        details = get_book_details(sr["url"], cancel_check=cancel_check)
        if details:
            # Merge search-level data as fallback
            for key in ("title", "author", "rating", "ratings_count"):
                if not details.get(key) and sr.get(key):
                    details[key] = sr[key]
        return details

    with ThreadPoolExecutor(max_workers=_GR_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, item): item for item in urls_to_fetch}
        done_count = 0
        for future in as_completed(futures):
            if cancel_check and cancel_check():
                executor.shutdown(wait=False, cancel_futures=True)
                break
            try:
                result = future.result()
                if result:
                    books.append(result)
                    _log(f"    📖 {result.get('title', '?')[:50]} — ⭐ {result.get('rating', 0)}")
            except Exception as e:
                logger.debug(f"Book detail fetch error: {e}")
            done_count += 1
            if progress_callback:
                progress_callback(done_count + 1, max_books + 1)

    _log(f"  ✓ Got details for {len(books)}/{len(urls_to_fetch)} books")

    # Step 3: aggregate metrics
    metrics = _aggregate_metrics(books)

    return {"books": books, "metrics": metrics}


def _aggregate_metrics(books):
    """Compute aggregated niche metrics from a list of book detail dicts."""
    if not books:
        return {}

    ratings = [b.get("rating", 0) for b in books if b.get("rating")]
    rating_counts = [b.get("ratings_count", 0) for b in books]
    review_counts = [b.get("reviews_count", 0) for b in books]
    wtr_counts = [b.get("want_to_read_count", 0) for b in books]

    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else 0
    total_ratings = sum(rating_counts)
    total_reviews = sum(review_counts)
    avg_want_to_read = round(sum(wtr_counts) / len(wtr_counts), 1) if wtr_counts else 0

    # Common shelves
    shelf_counter = {}
    for b in books:
        for s in b.get("shelves", []) + b.get("genres", []):
            s_lower = s.strip().lower()
            if s_lower:
                shelf_counter[s_lower] = shelf_counter.get(s_lower, 0) + 1
    common_shelves = sorted(shelf_counter, key=shelf_counter.get, reverse=True)[:10]
    shelf_tags = list(shelf_counter.keys())[:30]

    # Publication gap
    pub_years = []
    for b in books:
        pd = b.get("published_date", "")
        m = re.search(r'(\d{4})', pd)
        if m:
            pub_years.append(int(m.group(1)))
    pub_years.sort()
    if len(pub_years) >= 2:
        span_months = (pub_years[-1] - pub_years[0]) * 12
        publication_gap = round(span_months / (len(pub_years) - 1), 1)
    else:
        publication_gap = 0

    # Reader demand score (0-100)
    max_wtr = max(wtr_counts) if wtr_counts else 0
    wtr_score = min(40, (avg_want_to_read / 500) * 40) if avg_want_to_read else 0
    rating_score = min(30, (total_ratings / 50000) * 30)
    quality_score = min(30, (avg_rating / 5.0) * 30) if avg_rating else 0
    reader_demand_score = round(min(100, wtr_score + rating_score + quality_score))

    return {
        "avg_rating": avg_rating,
        "total_ratings": total_ratings,
        "total_reviews": total_reviews,
        "avg_want_to_read": avg_want_to_read,
        "common_shelves": common_shelves,
        "shelf_tags": shelf_tags,
        "publication_gap_months": publication_gap,
        "reader_demand_score": reader_demand_score,
        "books_analyzed": len(books),
    }


def search_open_library(query, max_results=20, progress_callback=None, cancel_check=None):
    """Search Open Library for books matching *query*.

    Returns list of dicts with keys:
        title, author, first_publish_year, isbn, subject, edition_count,
        ebook_access, ratings_average, ratings_count, want_to_read_count,
        already_read_count
    """
    data = _ol_api("/search.json", params={"q": query, "limit": max_results})
    if not data:
        return []

    docs = data.get("docs", [])
    results = []

    for i, doc in enumerate(docs[:max_results]):
        if cancel_check and cancel_check():
            break
        if progress_callback:
            progress_callback(i + 1, min(len(docs), max_results))

        authors = doc.get("author_name", [])
        subjects = doc.get("subject", [])
        isbns = doc.get("isbn", [])

        book = {
            "title": doc.get("title", ""),
            "author": ", ".join(authors[:3]) if authors else "",
            "first_publish_year": doc.get("first_publish_year", ""),
            "isbn": isbns[0] if isbns else "",
            "subject": ", ".join(subjects[:5]) if subjects else "",
            "edition_count": doc.get("edition_count", 0),
            "ebook_access": doc.get("ebook_access", ""),
            "ratings_average": round(doc.get("ratings_average", 0), 2),
            "ratings_count": doc.get("ratings_count", 0),
            "want_to_read_count": doc.get("want_to_read_count", 0),
            "already_read_count": doc.get("already_read_count", 0),
        }
        results.append(book)

    return results


def search_open_library_parallel(queries, max_per_query=10, progress_callback=None,
                                  cancel_check=None):
    """Search Open Library for multiple queries in parallel.

    Uses ThreadPoolExecutor with _OL_WORKERS threads.
    Returns dict: {query: [results]}
    """
    all_results = {}

    def _search_one(q):
        if cancel_check and cancel_check():
            return q, []
        return q, search_open_library(q, max_results=max_per_query, cancel_check=cancel_check)

    with ThreadPoolExecutor(max_workers=_OL_WORKERS) as executor:
        futures = {executor.submit(_search_one, q): q for q in queries}
        done = 0
        for future in as_completed(futures):
            if cancel_check and cancel_check():
                break
            try:
                q, results = future.result()
                all_results[q] = results
            except Exception as e:
                logger.debug(f"OL parallel search error: {e}")
            done += 1
            if progress_callback:
                progress_callback(done, len(queries))

    return all_results


def get_open_library_subjects(subject, limit=20):
    """Get books in a subject from Open Library.

    Returns dict: name, work_count, books (list of book dicts)
    """
    slug = subject.lower().replace(' ', '_')
    data = _ol_api(f"/subjects/{slug}.json", params={"limit": limit})
    if not data:
        return {"name": subject, "work_count": 0, "books": []}

    books = []
    for work in data.get("works", []):
        authors = work.get("authors", [])
        author_names = [a.get("name", "") for a in authors]
        books.append({
            "title": work.get("title", ""),
            "author": ", ".join(author_names),
            "cover_id": work.get("cover_id", ""),
            "edition_count": work.get("edition_count", 0),
            "first_publish_year": work.get("first_publish_year", ""),
            "subject": subject,
        })

    return {
        "name": data.get("name", subject),
        "work_count": data.get("work_count", 0),
        "books": books,
    }


def get_open_library_subjects_parallel(subjects, limit=20, progress_callback=None,
                                        cancel_check=None):
    """Fetch multiple OL subjects in parallel.

    Returns dict: {subject: {name, work_count, books}}
    """
    all_results = {}

    def _fetch_one(subj):
        if cancel_check and cancel_check():
            return subj, {"name": subj, "work_count": 0, "books": []}
        return subj, get_open_library_subjects(subj, limit=limit)

    with ThreadPoolExecutor(max_workers=_OL_WORKERS) as executor:
        futures = {executor.submit(_fetch_one, s): s for s in subjects}
        done = 0
        for future in as_completed(futures):
            if cancel_check and cancel_check():
                break
            try:
                subj, result = future.result()
                all_results[subj] = result
            except Exception as e:
                logger.debug(f"OL subject fetch error: {e}")
            done += 1
            if progress_callback:
                progress_callback(done, len(subjects))

    return all_results


def gap_analysis(keyword, progress_callback=None, cancel_check=None, log_callback=None):
    """Cross-reference Goodreads popularity to find underserved opportunities.

    Searches Goodreads → gets top books with high ratings/want-to-read,
    flags those with high demand. Uses ThreadPoolExecutor for parallel fetching.

    Returns list of opportunity dicts.
    """
    def _log(msg):
        if log_callback:
            log_callback(msg)

    if progress_callback:
        progress_callback(0, 10)

    _log(f"🔍 Searching Goodreads for '{keyword}'...")
    gr_books = search_goodreads(keyword, max_results=10, cancel_check=cancel_check)
    if cancel_check and cancel_check():
        return []

    _log(f"  ✓ Found {len(gr_books)} books — analysing in parallel...")
    if progress_callback:
        progress_callback(1, len(gr_books) + 1)

    # Parallel detail fetching
    opportunities = []

    def _analyse_one(item):
        idx, book = item
        if cancel_check and cancel_check():
            return None
        url = book.get("url", "")
        details = get_book_details(url, cancel_check=cancel_check) if url else {}

        rating = details.get("rating", 0) or book.get("rating", 0)
        ratings_count = details.get("ratings_count", 0) or book.get("ratings_count", 0)
        wtr = details.get("want_to_read_count", 0)

        # Opportunity score heuristic
        score = 0
        if wtr > 100:
            score += min(40, (wtr / 1000) * 40)
        if rating >= 4.0:
            score += 25
        elif rating >= 3.5:
            score += 15
        if ratings_count > 1000:
            score += min(20, (ratings_count / 10000) * 20)
        pub_date = details.get("published_date", "")
        m = re.search(r'(\d{4})', pub_date)
        if m and int(m.group(1)) >= 2020:
            score += 15
        score = round(min(100, score))

        return {
            "title": details.get("title", "") or book.get("title", ""),
            "author": details.get("author", "") or book.get("author", ""),
            "gr_rating": rating,
            "gr_ratings_count": ratings_count,
            "gr_want_to_read": wtr,
            "opportunity_score": score,
            "genres": details.get("genres", []),
            "published_date": pub_date,
        }

    items = [(i, b) for i, b in enumerate(gr_books)]
    with ThreadPoolExecutor(max_workers=_GR_WORKERS) as executor:
        futures = {executor.submit(_analyse_one, item): item for item in items}
        done_count = 0
        for future in as_completed(futures):
            if cancel_check and cancel_check():
                executor.shutdown(wait=False, cancel_futures=True)
                break
            try:
                result = future.result()
                if result:
                    opportunities.append(result)
                    _log(f"    📖 {result.get('title', '?')[:50]} — score {result.get('opportunity_score', 0)}")
            except Exception as e:
                logger.debug(f"Gap analysis error: {e}")
            done_count += 1
            if progress_callback:
                progress_callback(done_count + 1, len(gr_books) + 1)

    opportunities.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
    return opportunities

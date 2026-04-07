"""Reddit demand mining for KDP niches.

Scrapes book-related subreddits via Reddit's public JSON API (no auth).
Extracts "looking for", "suggest me", "recommend me" posts to surface
real reader demand before it peaks on Amazon.

Strategy:
  1. Fetch top/hot posts from book subreddits via .json endpoint
  2. Extract keywords/genres from titles and selftext
  3. Score by engagement (upvotes + comments)
  4. Curated baseline if scraping fails

Rate limit: ~60 req/min without auth — we stay well under.
"""

import logging
import re
import time
from collections import Counter

logger = logging.getLogger(__name__)

# Subreddits to monitor (ordered by relevance)
_SUBREDDITS = [
    "suggestmeabook",
    "booksuggestions",
    "romancebooks",
    "Fantasy",
    "horrorlit",
    "cozymysteries",
    "selfpublish",
    "kdp",
    "litrpg",
    "ProgressionFantasy",
    "booktok",
    "thrillbooks",
]

# Genre/trope patterns to extract
_GENRE_PATTERNS = re.compile(
    r'\b('
    r'dark romance|romantasy|cozy mystery|psychological thriller|'
    r'enemies to lovers|slow burn|hockey romance|fae romance|mafia romance|'
    r'bully romance|reverse harem|monster romance|age gap romance|why choose|'
    r'omegaverse|sapphic romance|gothic romance|urban fantasy|'
    r'litrpg|progression fantasy|spicy romance|small town romance|'
    r'forbidden romance|paranormal romance|supernatural thriller|'
    r'dystopian|post apocalyptic|alien romance|time travel romance|'
    r'coloring book|activity book|puzzle book|word search|sudoku|'
    r'gratitude journal|self help|self improvement|stoicism|adhd|'
    r'passive income|real estate investing|intermittent fasting|'
    r'true crime|serial killer|haunted house|ghost story|zombie|'
    r'ya fantasy|ya romance|new adult|science fiction|space opera|'
    r'regency romance|historical romance|contemporary romance|'
    r'military romance|second chance romance|fake dating|'
    r'grumpy sunshine|found family|portal fantasy|sword and sorcery'
    r')\b',
    re.IGNORECASE,
)

# Demand signal patterns in titles
_DEMAND_PATTERNS = re.compile(
    r'\b(looking for|suggest me|recommend|searching for|need a book|'
    r'any books like|books similar to|want to read|what should i read|'
    r'help me find|craving|desperately need)\b',
    re.IGNORECASE,
)

_BASELINE_TRENDS = [
    {"keyword": "enemies to lovers", "score": 95, "subreddit": "romancebooks"},
    {"keyword": "dark romance", "score": 92, "subreddit": "romancebooks"},
    {"keyword": "cozy mystery", "score": 88, "subreddit": "cozymysteries"},
    {"keyword": "progression fantasy", "score": 85, "subreddit": "ProgressionFantasy"},
    {"keyword": "litrpg", "score": 84, "subreddit": "litrpg"},
    {"keyword": "romantasy", "score": 82, "subreddit": "Fantasy"},
    {"keyword": "sapphic romance", "score": 78, "subreddit": "romancebooks"},
    {"keyword": "psychological thriller", "score": 76, "subreddit": "thrillbooks"},
    {"keyword": "hockey romance", "score": 74, "subreddit": "romancebooks"},
    {"keyword": "gothic romance", "score": 72, "subreddit": "horrorlit"},
    {"keyword": "slow burn romance", "score": 70, "subreddit": "suggestmeabook"},
    {"keyword": "found family", "score": 68, "subreddit": "Fantasy"},
    {"keyword": "grumpy sunshine", "score": 66, "subreddit": "romancebooks"},
    {"keyword": "monster romance", "score": 64, "subreddit": "romancebooks"},
    {"keyword": "fake dating", "score": 62, "subreddit": "romancebooks"},
    {"keyword": "true crime", "score": 60, "subreddit": "suggestmeabook"},
    {"keyword": "self improvement", "score": 58, "subreddit": "selfpublish"},
    {"keyword": "coloring book", "score": 55, "subreddit": "kdp"},
    {"keyword": "second chance romance", "score": 54, "subreddit": "romancebooks"},
    {"keyword": "portal fantasy", "score": 52, "subreddit": "Fantasy"},
    # Reddit-exclusive demand signals (not in Amazon autocomplete seeds)
    {"keyword": "morally grey romance", "score": 88, "subreddit": "romancebooks"},
    {"keyword": "underrated thriller", "score": 82, "subreddit": "thrillbooks"},
    {"keyword": "character driven fantasy", "score": 79, "subreddit": "Fantasy"},
    {"keyword": "villain pov novel", "score": 75, "subreddit": "Fantasy"},
    {"keyword": "comfort reread romance", "score": 72, "subreddit": "romancebooks"},
    {"keyword": "books that make you cry", "score": 70, "subreddit": "suggestmeabook"},
    {"keyword": "unreliable narrator thriller", "score": 68, "subreddit": "thrillbooks"},
    {"keyword": "dark academia fiction", "score": 77, "subreddit": "suggestmeabook"},
    {"keyword": "antiheroine fiction", "score": 65, "subreddit": "Fantasy"},
    {"keyword": "dual timeline novel", "score": 63, "subreddit": "suggestmeabook"},
    {"keyword": "cozy fantasy", "score": 80, "subreddit": "Fantasy"},
    {"keyword": "book boyfriend romance", "score": 76, "subreddit": "romancebooks"},
]


def fetch_reddit_demand(cancel_check=None, log_cb=None):
    """Fetch demand signals from Reddit book subreddits.

    Returns list of dicts: {keyword, score, subreddit, posts, engagement}
    """
    def _log(msg):
        if log_cb:
            log_cb(msg)

    def _cancelled():
        return cancel_check and cancel_check()

    all_posts = []

    # Scrape subreddits
    scraped_count = 0
    for sub in _SUBREDDITS:
        if _cancelled():
            break
        posts = _fetch_subreddit(sub, sort="hot", limit=25,
                                 cancel_check=cancel_check, log_cb=log_cb)
        if posts:
            all_posts.extend(posts)
            scraped_count += 1
            _log(f"    r/{sub}: {len(posts)} posts")
        time.sleep(0.3)

    # Also fetch top/week for demand subreddits
    demand_subs = ["suggestmeabook", "booksuggestions", "romancebooks"]
    for sub in demand_subs:
        if _cancelled():
            break
        posts = _fetch_subreddit(sub, sort="top", time_filter="week",
                                 limit=25, cancel_check=cancel_check,
                                 log_cb=log_cb)
        if posts:
            all_posts.extend(posts)
            _log(f"    r/{sub} (top/week): {len(posts)} posts")
        time.sleep(0.3)

    if scraped_count > 0:
        _log(f"  ✓ Reddit: scraped {scraped_count}/{len(_SUBREDDITS)} subreddits, "
             f"{len(all_posts)} total posts")
    else:
        _log("  ⚠ Reddit scraping failed — using baseline only")

    # Extract genre/keyword mentions
    trends = _extract_trends(all_posts)
    _log(f"  ✓ Reddit: {len(trends)} genre/keyword trends extracted")

    # Add baseline
    _log(f"  📚 Reddit baseline: {len(_BASELINE_TRENDS)} curated demand signals added")
    for b in _BASELINE_TRENDS:
        trends.append(b)

    # Deduplicate, keeping highest score
    seen = {}
    for t in trends:
        key = t["keyword"].lower().strip()
        if key not in seen or t.get("score", 0) > seen[key].get("score", 0):
            seen[key] = t
    return list(seen.values())


def _fetch_subreddit(subreddit, sort="hot", time_filter=None,
                     limit=25, cancel_check=None, log_cb=None):
    """Fetch posts from a subreddit via JSON API."""
    from kdp_scout.http_client import get_session

    session = get_session()
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
    params = {"limit": limit, "raw_json": 1}
    if time_filter:
        params["t"] = time_filter

    headers = {
        "User-Agent": "KDP-Scout/3.0 (book niche research tool)",
        "Accept": "application/json",
    }

    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            posts = []
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                if post.get("stickied"):
                    continue
                posts.append({
                    "title": post.get("title", ""),
                    "selftext": (post.get("selftext", "") or "")[:500],
                    "subreddit": subreddit,
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "upvote_ratio": post.get("upvote_ratio", 0),
                    "url": post.get("url", ""),
                })
            return posts
        elif resp.status_code == 429:
            logger.debug(f"Reddit rate limited on r/{subreddit}")
            time.sleep(2)
        else:
            logger.debug(f"Reddit r/{subreddit}: HTTP {resp.status_code}")
    except Exception as e:
        logger.debug(f"Reddit r/{subreddit} failed: {e}")

    return []


def _extract_trends(posts):
    """Extract genre/keyword demand from post titles and text."""
    keyword_data = {}  # keyword -> {score, posts, engagement, subreddits}

    for post in posts:
        title = post.get("title", "")
        text = post.get("selftext", "")
        combined = f"{title} {text}"
        subreddit = post.get("subreddit", "")
        upvotes = post.get("score", 0)
        comments = post.get("num_comments", 0)
        engagement = upvotes + comments * 2  # comments weighted higher

        # Check if this is a demand post (looking for / suggest me)
        is_demand = bool(_DEMAND_PATTERNS.search(title))
        demand_multiplier = 1.5 if is_demand else 1.0

        # Extract genre mentions
        genres = _GENRE_PATTERNS.findall(combined)
        for genre in genres:
            key = genre.lower().strip()
            if key not in keyword_data:
                keyword_data[key] = {
                    "keyword": key,
                    "score": 0,
                    "posts": 0,
                    "engagement": 0,
                    "subreddits": set(),
                }
            kd = keyword_data[key]
            kd["posts"] += 1
            kd["engagement"] += engagement
            kd["subreddits"].add(subreddit)
            kd["score"] += engagement * demand_multiplier

        # Also extract from title directly for demand posts
        if is_demand and len(title) > 10:
            # Extract significant phrases from demand titles
            clean = re.sub(r'[^a-z\s]', ' ', title.lower())
            clean = re.sub(r'\s+', ' ', clean).strip()
            words = clean.split()
            # Look for 2-3 word phrases that could be niches
            stop = {'a', 'an', 'the', 'of', 'in', 'on', 'for', 'and', 'or',
                    'me', 'my', 'i', 'is', 'any', 'like', 'to', 'with',
                    'looking', 'suggest', 'recommend', 'book', 'books',
                    'read', 'reading', 'need', 'want', 'help', 'find',
                    'please', 'just', 'some', 'good', 'best', 'new',
                    'that', 'this', 'what', 'can', 'anyone', 'something',
                    'similar', 'about', 'but', 'not', 'more', 'really',
                    'been', 'have', 'had', 'would', 'could', 'should'}
            filtered = [w for w in words if w not in stop and len(w) > 2]
            if 2 <= len(filtered) <= 4:
                phrase = " ".join(filtered[:3])
                if phrase not in keyword_data:
                    keyword_data[phrase] = {
                        "keyword": phrase,
                        "score": 0,
                        "posts": 0,
                        "engagement": 0,
                        "subreddits": set(),
                    }
                kd = keyword_data[phrase]
                kd["posts"] += 1
                kd["engagement"] += engagement
                kd["subreddits"].add(subreddit)
                kd["score"] += engagement * 0.5  # lower weight for extracted phrases

    # Normalize scores and convert sets
    results = []
    if keyword_data:
        max_score = max(kd["score"] for kd in keyword_data.values()) or 1
        for kd in keyword_data.values():
            if kd["posts"] < 1:
                continue
            # Boost for multi-subreddit presence
            sub_boost = 1 + 0.2 * (len(kd["subreddits"]) - 1)
            normalized = min(100, (kd["score"] / max_score) * 100 * sub_boost)
            results.append({
                "keyword": kd["keyword"],
                "score": round(normalized, 1),
                "posts": kd["posts"],
                "engagement": kd["engagement"],
                "subreddit": ", ".join(sorted(kd["subreddits"])),
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:50]


def trends_to_items(trends, marketplace="us"):
    """Convert Reddit trend dicts to harvest items for discovery pipeline."""
    items = []
    for t in trends:
        kw = t.get("keyword", "").strip()
        if not kw or len(kw) < 3:
            continue
        items.append({
            "title": kw,
            "keyword": kw,
            "_source_type": "reddit_demand",
            "_category": _guess_reddit_category(kw),
            "_marketplace": marketplace,
            "_reddit_score": t.get("score", 0),
            "_reddit_posts": t.get("posts", 0),
            "_subreddit": t.get("subreddit", ""),
        })
    return items


def _guess_reddit_category(keyword):
    kw = keyword.lower()
    if any(x in kw for x in ["romance", "lovers", "harem", "omegaverse",
                               "romantasy", "spicy", "forbidden", "sapphic",
                               "dating", "sunshine", "grumpy"]):
        return "romance"
    if any(x in kw for x in ["fantasy", "fae", "magic", "litrpg",
                               "progression", "portal", "sword"]):
        return "fantasy"
    if any(x in kw for x in ["thriller", "mystery", "crime", "true crime",
                               "cozy", "serial killer"]):
        return "thriller"
    if any(x in kw for x in ["horror", "gothic", "haunted", "zombie",
                               "apocalyptic", "ghost"]):
        return "horror"
    if any(x in kw for x in ["self help", "self improvement", "stoicism",
                               "adhd", "passive income", "investing",
                               "fasting", "coloring", "journal"]):
        return "self_help"
    return "general"


# ---- Public aliases for the UI page ----
SUBREDDITS = [{"name": s} for s in _SUBREDDITS]


def _fetch_subreddit_json(name, sort="hot", time_filter=None, limit=25):
    """Alias for _fetch_subreddit returning raw Reddit JSON children."""
    from kdp_scout.http_client import get_session

    session = get_session()
    url = f"https://www.reddit.com/r/{name}/{sort}.json"
    params = {"limit": limit, "raw_json": 1}
    if time_filter:
        params["t"] = time_filter

    headers = {
        "User-Agent": "KDP-Scout/3.0 (book niche research tool)",
        "Accept": "application/json",
    }

    try:
        resp = session.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            children = data.get("data", {}).get("children", [])
            return [c for c in children if not c.get("data", {}).get("stickied")]
        return []
    except Exception:
        return []


def harvest_reddit_demand(progress_cb=None):
    """Alias for fetch_reddit_demand matching the page's expected API."""
    return fetch_reddit_demand(
        cancel_check=None,
        log_cb=progress_cb,
    )

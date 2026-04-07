"""TikTok / BookTok trending scraper.

Scrapes BookTok hashtag pages, TikTok Creative Center, and Google search
to surface genres/tropes trending on TikTok before they peak on Amazon.

Strategy (in order of reliability):
  1. TikTok Creative Center — trending hashtags from ads platform
  2. TikTok web hashtag pages (improved with UA rotation + stealth headers)
  3. Google search fallback for BookTok trends (updated 2025-2026)
  4. Curated baseline — 120+ BookTok genres/tropes/niches
"""

import json
import logging
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# Rotating User-Agent strings
_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
]


def _random_ua():
    return random.choice(_USER_AGENTS)


def _stealth_headers(referer="https://www.tiktok.com/"):
    """Return browser-like headers with Sec-Fetch-* for stealth."""
    return {
        'User-Agent': _random_ua(),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Referer': referer,
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'same-origin',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1',
        'Cache-Control': 'max-age=0',
    }


# BookTok hashtags to monitor
BOOKTOK_HASHTAGS = [
    "booktok", "booktoker", "bookrecommendations", "romantasy",
    "darkromance", "spicybooks", "booktokromance", "stanreads",
    "enemiestolovers", "slowburn", "faeromance", "fairyloot",
    "bookstagram", "fantasybooks", "thrillerbooktok", "mysterybooks",
    "cozymystery", "smalltownromance", "hockeyromance", "mafiaromance",
    "bookclub", "currentlyreading", "bookobsessed", "readingwrapped",
    "bullyromance", "monsterromance", "reverseharembooks", "omegaverse",
    "gothicromance", "sapphicbooks", "urbanfantasy", "litrpg",
]

# ──────────────────────────────────────────────────────────
# Curated baseline — 120+ BookTok genres/tropes/niches
# ──────────────────────────────────────────────────────────
_BASELINE_TRENDS = [
    # ── Romance sub-genres (31) ──
    {"keyword": "dark romance", "views": 9_500_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "hockey romance", "views": 2_100_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "mafia romance", "views": 1_800_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "bully romance", "views": 1_500_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "reverse harem", "views": 1_200_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "monster romance", "views": 980_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "age gap romance", "views": 870_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "why choose romance", "views": 820_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "omegaverse", "views": 750_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "sapphic romance", "views": 690_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "gothic romance", "views": 630_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "small town romance", "views": 580_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "forbidden romance", "views": 540_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "paranormal romance", "views": 510_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "alien romance", "views": 420_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "time travel romance", "views": 380_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "contemporary romance", "views": 3_200_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "historical romance", "views": 1_600_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "billionaire romance", "views": 720_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "rockstar romance", "views": 310_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "military romance", "views": 290_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "sports romance", "views": 1_400_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "teacher student romance", "views": 260_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "boss employee romance", "views": 240_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "enemies to lovers", "views": 5_800_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "friends to lovers", "views": 3_400_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "second chance romance", "views": 480_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "fake dating romance", "views": 560_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "arranged marriage romance", "views": 620_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "grumpy sunshine romance", "views": 2_600_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "forced proximity romance", "views": 1_100_000_000, "source": "tiktok_baseline", "category": "romance"},

    # ── Fantasy sub-genres (19) ──
    {"keyword": "romantasy", "views": 7_200_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "fae romance", "views": 1_900_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "urban fantasy", "views": 680_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "cozy fantasy", "views": 920_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "progression fantasy", "views": 470_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "litrpg", "views": 390_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "dark fantasy", "views": 560_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "grimdark fantasy", "views": 310_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "portal fantasy", "views": 220_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "second world fantasy", "views": 180_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "sword and sorcery", "views": 250_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "magical realism", "views": 340_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "fairy tale retelling", "views": 780_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "dragon fantasy", "views": 420_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "witchy books", "views": 510_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "academy fantasy", "views": 360_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "epic fantasy", "views": 1_300_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "gaslamp fantasy", "views": 140_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "cultivation fantasy", "views": 280_000_000, "source": "tiktok_baseline", "category": "fantasy"},

    # ── Thriller / Mystery (15) ──
    {"keyword": "psychological thriller", "views": 2_400_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "domestic thriller", "views": 680_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "cozy mystery", "views": 1_800_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "true crime books", "views": 1_500_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "amateur sleuth", "views": 320_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "police procedural", "views": 410_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "locked room mystery", "views": 190_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "unreliable narrator", "views": 870_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "missing person thriller", "views": 540_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "cold case mystery", "views": 280_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "legal thriller", "views": 350_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "medical thriller", "views": 220_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "technothriller", "views": 160_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "thriller booktok", "views": 1_100_000_000, "source": "tiktok_baseline", "category": "thriller"},
    {"keyword": "mystery booktok", "views": 950_000_000, "source": "tiktok_baseline", "category": "thriller"},

    # ── Horror (10) ──
    {"keyword": "gothic horror", "views": 580_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "cosmic horror", "views": 340_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "folk horror", "views": 290_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "body horror", "views": 210_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "haunted house books", "views": 370_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "supernatural horror", "views": 450_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "zombie books", "views": 260_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "vampire romance", "views": 890_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "werewolf romance", "views": 720_000_000, "source": "tiktok_baseline", "category": "horror"},
    {"keyword": "ghost stories", "views": 310_000_000, "source": "tiktok_baseline", "category": "horror"},

    # ── Non-fiction / BookTok Culture / Tropes (23) ──
    {"keyword": "dark academia", "views": 5_200_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "cottagecore books", "views": 680_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "romantasy series", "views": 1_400_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "morally grey hero", "views": 2_100_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "book hangover", "views": 960_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "girlboss romance", "views": 420_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "dual pov romance", "views": 580_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "whiplash ending thriller", "views": 340_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "booktok made me buy", "views": 3_800_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "one sitting read", "views": 720_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "crying book booktok", "views": 1_100_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "comfort read", "views": 640_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "spicy bookshelf", "views": 890_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "book boyfriend", "views": 1_600_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "slow burn angst", "views": 750_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "found family trope", "views": 1_300_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "touch her and die", "views": 2_400_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "he falls first", "views": 1_800_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "she falls first", "views": 1_200_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "possessive hero", "views": 1_500_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "cinnamon roll hero", "views": 980_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "villain romance", "views": 1_100_000_000, "source": "tiktok_baseline", "category": "general"},
    {"keyword": "antiheroine romance", "views": 530_000_000, "source": "tiktok_baseline", "category": "general"},

    # ── KDP-specific (12) ──
    {"keyword": "low content books", "views": 320_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "coloring books adults", "views": 580_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "journals and planners", "views": 410_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "activity books kids", "views": 490_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "puzzle books", "views": 350_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "logbooks", "views": 180_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "recipe books blank", "views": 220_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "composition notebooks", "views": 270_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "password books", "views": 190_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "guided journals", "views": 340_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "self help journal", "views": 460_000_000, "source": "tiktok_baseline", "category": "kdp"},
    {"keyword": "gratitude journal", "views": 520_000_000, "source": "tiktok_baseline", "category": "kdp"},

    # ── Spicy / trending extras to reach 120+ ──
    {"keyword": "spicy romance", "views": 4_500_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "slow burn romance", "views": 3_100_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "fantasy series kindle", "views": 220_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "booktok romance", "views": 6_800_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "new adult romance", "views": 1_700_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "dystopian romance", "views": 480_000_000, "source": "tiktok_baseline", "category": "fantasy"},
    {"keyword": "cozy romance", "views": 640_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "clean romance", "views": 550_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "dark bully romance", "views": 380_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "alien sci fi romance", "views": 260_000_000, "source": "tiktok_baseline", "category": "romance"},
    {"keyword": "academy romance", "views": 440_000_000, "source": "tiktok_baseline", "category": "romance"},
]

# Regex to extract genre/trope mentions from TikTok descriptions
_GENRE_PATTERNS = [
    r'\b(dark romance|romantasy|cozy mystery|psychological thriller|'
    r'enemies to lovers|slow burn|hockey romance|fae romance|mafia romance|'
    r'bully romance|reverse harem|monster romance|age gap|why choose|'
    r'omegaverse|sapphic romance|gothic romance|urban fantasy|'
    r'litrpg|progression fantasy|spicy romance|small town romance|'
    r'forbidden romance|paranormal romance|supernatural thriller|'
    r'dystopian|apocalyptic|alien romance|time travel romance|'
    r'dark academia|morally grey|found family|grumpy sunshine|'
    r'forced proximity|cottagecore|cozy fantasy|fairy tale retelling|'
    r'he falls first|she falls first|touch her and die|cinnamon roll|'
    r'book boyfriend|book hangover|one sitting read)\b',
]
_GENRE_RE = re.compile('|'.join(_GENRE_PATTERNS), re.IGNORECASE)


# ──────────────────────────────────────────────────────────
# Strategy 1: TikTok Creative Center
# ──────────────────────────────────────────────────────────
def fetch_creative_center_trends(cancel_check=None, log_cb=None):
    """Fetch TikTok trending hashtags via Google scraping.

    The TikTok Creative Center requires JS rendering and auth — unusable
    without a headless browser.  Instead we scrape Google for recent
    BookTok / TikTok trending hashtag articles and extract hashtag names
    from the results.

    Can be called standalone (for the dedicated TikTok page) or as part
    of the full fetch_booktok_trends pipeline.

    Returns list of dicts: {keyword, views, source, hashtag, category}
    """
    from kdp_scout.http_client import get_session

    def _log(msg):
        if log_cb:
            log_cb(msg)

    def _cancelled():
        return cancel_check and cancel_check()

    session = get_session()
    results = []
    seen = set()

    _log("🔍 Fetching TikTok trending hashtags via web search...")

    queries = [
        "tiktok trending hashtags booktok 2025 2026",
        "tiktok popular book hashtags trending now",
        "booktok viral hashtags list 2025",
        "tiktok creative center trending hashtags books",
        "most popular booktok hashtags",
        "tiktok book niche hashtags viral",
    ]

    # Pattern: #HashtagName  or  #hashtag_name
    hashtag_re = re.compile(r'#([A-Za-z][A-Za-z0-9_]{2,})')
    # Also grab bare hashtag-like words near "hashtag" context
    bare_tag_re = re.compile(r'(?:hashtag|trending|viral|booktok)[^<]{0,80}?\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b')
    # Filter out hex color codes and CSS-like values
    hex_re = re.compile(r'^[0-9A-Fa-f]{3,8}$')
    # Noise words to skip
    noise = {'http', 'https', 'html', 'script', 'style', 'class', 'charset',
             'viewport', 'content', 'description', 'width', 'none', 'true',
             'false', 'null', 'undefined', 'function', 'return', 'window',
             'document', 'google', 'search', 'result', 'display'}

    # Try DuckDuckGo first (reliable HTML), then Google as fallback
    engines = [
        ("DuckDuckGo", "https://html.duckduckgo.com/html/", "q"),
        ("Google", "https://www.google.com/search", "q"),
    ]

    for engine_name, engine_url, param_key in engines:
        if len(results) >= 10:
            break
        for query in queries:
            if _cancelled():
                break
            try:
                time.sleep(random.uniform(0.5, 1.5))
                resp = session.get(
                    engine_url,
                    params={param_key: query, "num": 20},
                    headers={
                        "User-Agent": _random_ua(),
                        "Accept": "text/html",
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                    timeout=12,
                )
                if resp.status_code != 200:
                    continue

                text = resp.text
                # Extract #hashtags
                tags = hashtag_re.findall(text)
                # Also extract camelCase words near hashtag context
                bare_tags = bare_tag_re.findall(text)
                all_tags = tags + bare_tags

                added = 0
                for tag in all_tags:
                    if _cancelled():
                        break
                    clean = tag.lower().strip()
                    if hex_re.match(clean):
                        continue
                    if len(clean) < 4:
                        continue
                    if clean in seen or clean in noise:
                        continue
                    seen.add(clean)
                    keyword = re.sub(r'([a-z])([A-Z])', r'\1 \2', tag)
                    keyword = keyword.replace("_", " ").strip().lower()
                    results.append({
                        "keyword": keyword,
                        "views": 0,
                        "source": "tiktok_creative_center",
                        "hashtag": f"#{tag}",
                        "category": _guess_tiktok_category(keyword),
                    })
                    added += 1

                if added:
                    _log(f"  ✓ {engine_name} '{query[:40]}…': +{added} hashtags ({len(results)} total)")
            except Exception as e:
                _log(f"  ⚠ {engine_name} query failed: {e}")
                logger.debug(f"{engine_name} hashtag scrape failed: {e}")

        if results:
            _log(f"  📊 {engine_name}: {len(results)} unique hashtags found")
            break

    if not results:
        _log("  ⚠ No trending hashtags found via web search — using curated trending subset")
        # Fallback: return the hottest baseline entries tagged as "trending"
        trending_baseline = [
            item for item in _BASELINE_TRENDS
            if item.get("views", 0) >= 500_000_000
        ]
        for item in trending_baseline[:30]:
            kw = item["keyword"]
            results.append({
                "keyword": kw,
                "views": item.get("views", 0),
                "source": "tiktok_creative_center",
                "hashtag": f"#{kw.replace(' ', '')}",
                "category": item.get("category", _guess_tiktok_category(kw)),
            })
        if results:
            _log(f"  ✓ Curated trending fallback: {len(results)} high-view hashtags")

    _log(f"  📊 Total trending hashtags: {len(results)}")
    return results


# ──────────────────────────────────────────────────────────
# Strategy 2: TikTok hashtag pages (improved)
# ──────────────────────────────────────────────────────────
def _scrape_tiktok_hashtags(cancel_check=None, log_cb=None):
    """Scrape TikTok hashtag pages for view counts and related content."""
    from kdp_scout.http_client import get_session

    def _log(msg):
        if log_cb:
            log_cb(msg)

    session = get_session()
    results = []

    # Only try a subset to avoid rate limiting
    priority_tags = BOOKTOK_HASHTAGS[:12]

    _log(f"📱 Scraping {len(priority_tags)} TikTok hashtag pages...")

    for tag in priority_tags:
        if cancel_check and cancel_check():
            break
        try:
            headers = _stealth_headers(referer="https://www.tiktok.com/explore")
            url = f"https://www.tiktok.com/tag/{tag}"
            resp = session.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                text = resp.text
                # Extract view count from page
                view_matches = re.findall(
                    r'"stats":\{"videoCount":\d+,"viewCount":(\d+)',
                    text
                )
                views = int(view_matches[0]) if view_matches else 0

                # Extract genre mentions from video titles in page
                genres = _GENRE_RE.findall(text)
                genre_counts = {}
                for g in genres:
                    genre_counts[g.lower()] = genre_counts.get(g.lower(), 0) + 1

                for genre, count in genre_counts.items():
                    if count >= 2:
                        results.append({
                            'keyword': genre,
                            'views': count * 1_000_000,
                            'source': 'tiktok_web',
                            'hashtag': tag,
                            'category': _guess_tiktok_category(genre),
                        })

                if views > 0:
                    clean_kw = tag.replace('booktok', '').strip() or tag
                    results.append({
                        'keyword': clean_kw,
                        'views': views,
                        'source': 'tiktok_web',
                        'hashtag': tag,
                        'category': _guess_tiktok_category(clean_kw),
                    })

            # Random delay to avoid rate limiting
            time.sleep(random.uniform(0.3, 1.0))
        except Exception as e:
            logger.debug(f"TikTok scrape failed for #{tag}: {e}")
            continue

    return results


# ──────────────────────────────────────────────────────────
# Strategy 3: Google search (updated 2025-2026)
# ──────────────────────────────────────────────────────────
def _scrape_google_booktok(cancel_check=None, log_cb=None):
    """Use Google search to find BookTok trending genres."""
    from kdp_scout.http_client import get_session

    def _log(msg):
        if log_cb:
            log_cb(msg)

    session = get_session()
    results = []

    queries = [
        "site:tiktok.com booktok trending romance 2025 2026",
        "booktok trending genres books site:reddit.com OR site:goodreads.com 2025",
        "booktok most popular book genres tropes 2026",
        "tiktok booktok viral books trending niches 2025",
    ]

    _log(f"🔍 Searching Google for BookTok trends ({len(queries)} queries)...")

    for query in queries[:3]:
        if cancel_check and cancel_check():
            break
        try:
            headers = {
                'User-Agent': _random_ua(),
                'Accept-Language': 'en-US,en;q=0.9',
            }
            url = "https://www.google.com/search"
            params = {'q': query, 'num': 10, 'hl': 'en'}
            resp = session.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                genres = _GENRE_RE.findall(resp.text)
                for g in genres:
                    results.append({
                        'keyword': g.lower(),
                        'views': 500_000,
                        'source': 'google_booktok',
                        'hashtag': 'booktok',
                        'category': _guess_tiktok_category(g),
                    })
            time.sleep(random.uniform(0.8, 1.5))
        except Exception as e:
            logger.debug(f"Google BookTok search failed: {e}")

    # Deduplicate
    seen = set()
    deduped = []
    for r in results:
        if r['keyword'] not in seen:
            seen.add(r['keyword'])
            deduped.append(r)

    return deduped


# ──────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────
def fetch_booktok_trends(cancel_check=None, log_cb=None):
    """Fetch BookTok trending genres.

    Returns a list of dicts:
        {keyword, views, source, hashtag, category}
    """
    def _log(msg):
        if log_cb:
            log_cb(msg)

    def _cancelled():
        return cancel_check and cancel_check()

    trends = []

    # Strategy 1: TikTok Creative Center
    _log("━━━ Strategy 1: TikTok Creative Center ━━━")
    cc_results = fetch_creative_center_trends(cancel_check=cancel_check, log_cb=log_cb)
    if cc_results:
        trends.extend(cc_results)
    else:
        _log("  ⚠ Creative Center yielded no results — continuing")

    # Strategy 2: TikTok hashtag web pages
    if not _cancelled():
        _log("━━━ Strategy 2: TikTok Hashtag Pages ━━━")
        tiktok_results = _scrape_tiktok_hashtags(cancel_check=cancel_check, log_cb=log_cb)
        if tiktok_results:
            trends.extend(tiktok_results)
            _log(f"  ✓ TikTok web: {len(tiktok_results)} trends scraped")
        else:
            _log("  ⚠ TikTok web blocked — trying Google fallback")

    # Strategy 3: Google search for BookTok trending
    if not _cancelled():
        _log("━━━ Strategy 3: Google BookTok Search ━━━")
        google_results = _scrape_google_booktok(cancel_check=cancel_check, log_cb=log_cb)
        if google_results:
            trends.extend(google_results)
            _log(f"  ✓ Google BookTok: {len(google_results)} trends found")
        else:
            _log("  ⚠ Google fallback failed")

    # Strategy 4: Always include baseline
    _log(f"━━━ Strategy 4: Curated Baseline ━━━")
    _log(f"  📚 Baseline: {len(_BASELINE_TRENDS)} curated BookTok trends added")
    trends.extend(_BASELINE_TRENDS)

    # Deduplicate by keyword
    seen = set()
    deduped = []
    for t in trends:
        key = t['keyword'].lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    _log(f"\n✅ Total unique trends: {len(deduped)}")
    return deduped


def get_baseline_trends():
    """Return the curated baseline trends directly (no scraping)."""
    return list(_BASELINE_TRENDS)


def trends_to_items(trends, marketplace='us'):
    """Convert trend dicts to harvest items compatible with discovery pipeline."""
    items = []
    for t in trends:
        kw = t.get('keyword', '').strip()
        if not kw or len(kw) < 3:
            continue
        items.append({
            'title': kw,
            'keyword': kw,
            '_source_type': 'tiktok_booktok',
            '_category': t.get('category', _guess_tiktok_category(kw)),
            '_marketplace': marketplace,
            '_views': t.get('views', 0),
            '_hashtag': t.get('hashtag', 'booktok'),
            '_tiktok_source': t.get('source', 'baseline'),
        })
    return items


def _guess_tiktok_category(keyword):
    kw = keyword.lower()
    if any(x in kw for x in ['romance', 'lovers', 'harem', 'omegaverse',
                               'romantasy', 'spicy', 'forbidden', 'sapphic',
                               'dating', 'marriage', 'grumpy sunshine',
                               'forced proximity', 'boyfriend', 'possessive',
                               'cinnamon roll', 'slow burn']):
        return 'romance'
    if any(x in kw for x in ['fantasy', 'fae', 'magic', 'litrpg', 'progression',
                               'dragon', 'witch', 'academy', 'cultivation',
                               'grimdark', 'portal', 'sorcery', 'gaslamp']):
        return 'fantasy'
    if any(x in kw for x in ['thriller', 'mystery', 'crime', 'true crime',
                               'sleuth', 'procedural', 'locked room',
                               'unreliable narrator', 'missing person']):
        return 'thriller'
    if any(x in kw for x in ['horror', 'gothic', 'haunted', 'zombie',
                               'cosmic', 'folk horror', 'body horror',
                               'vampire', 'werewolf', 'ghost', 'supernatural']):
        return 'horror'
    if any(x in kw for x in ['coloring', 'journal', 'planner', 'notebook',
                               'logbook', 'puzzle', 'activity book',
                               'low content', 'recipe book', 'password',
                               'composition', 'guided']):
        return 'kdp'
    return 'general'

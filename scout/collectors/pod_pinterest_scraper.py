"""
PodPinterestScraper - Scrape Pinterest for POD trends and niche discovery.
"""
import json
import time
import requests
from bs4 import BeautifulSoup
from typing import Dict, List, Any
import re

try:
    from scout.config import POD_PINTEREST_RATE_LIMIT
except ImportError:
    POD_PINTEREST_RATE_LIMIT = 2.0


def scrape_pinterest_search(keyword: str, mode: str = "all") -> Dict[str, Any]:
    """
    Scrape Pinterest for a keyword.
    
    Args:
        keyword: The keyword to search
        mode: 'suggest', 'boards', 'trending', 'all'
    
    Returns:
        Dict with suggestions, top_pins, top_boards, trending
    """
    result = {
        "suggestions": [],
        "top_pins": [],
        "top_boards": [],
        "trending": [],
        "pin_count_estimate": 0,
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    
    def _log(msg):
        """Internal logger that prints prefixed messages."""
        print(f"[Pinterest] {msg}")

    def _extract_json_data(soup):
        """Try to extract embedded JSON data from Pinterest page."""
        for script_id in ['__NEXT_DATA__', '__PWS_INITIAL_STATE__', '__PWS_DATA__']:
            script = soup.find('script', {'id': script_id})
            if script and script.string:
                try:
                    return json.loads(script.string)
                except (json.JSONDecodeError, TypeError):
                    pass
        for script in soup.find_all('script', {'type': 'application/json'}):
            if script and script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        return data
                except (json.JSONDecodeError, TypeError):
                    pass
        return None

    def _parse_followers(text):
        """Parse follower count text like '12.5K' or '1.2M'."""
        if not text:
            return 0
        text = text.strip()
        if 'M' in text:
            return int(float(text.replace('M', '').replace(',', '')) * 1000000)
        if 'K' in text:
            return int(float(text.replace('K', '').replace(',', '')) * 1000)
        try:
            return int(re.sub(r'[^0-9]', '', text))
        except ValueError:
            return 0

    def _extract_suggestions_from_json(json_data, keyword, result):
        """Recursively find suggestion-like strings in Pinterest JSON data."""
        if isinstance(json_data, dict):
            for k, v in json_data.items():
                if k in ('query', 'term', 'phrase', 'suggestion', 'related') and isinstance(v, str) and len(v) > 2:
                    if v.lower() != keyword.lower() and not any(s['suggestion'] == v for s in result['suggestions']):
                        result['suggestions'].append({"suggestion": v, "source": "pinterest_suggest"})
                        if len(result['suggestions']) >= 15:
                            return
                _extract_suggestions_from_json(v, keyword, result)
        elif isinstance(json_data, list):
            for item in json_data:
                _extract_suggestions_from_json(item, keyword, result)

    def _extract_boards_from_json(json_data, result):
        """Recursively find board objects in Pinterest JSON data."""
        if isinstance(json_data, dict):
            if 'name' in json_data and 'id' in json_data:
                name = json_data.get('name', '')
                followers = _parse_followers(str(json_data.get('follower_count', json_data.get('followers', 0))))
                if name and not any(b['board_name'] == name for b in result['top_boards']):
                    result['top_boards'].append({
                        "board_name": name,
                        "followers": followers,
                        "pin_count": json_data.get('pin_count', 0),
                    })
                    return
            for v in json_data.values():
                _extract_boards_from_json(v, result)
        elif isinstance(json_data, list):
            for item in json_data:
                _extract_boards_from_json(item, result)
                if len(result['top_boards']) >= 10:
                    return

    # Get autocomplete suggestions
    if mode in ["suggest", "all"]:
        suggest_headers = {
            **headers,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.pinterest.com/",
            "Origin": "https://www.pinterest.com",
        }

        # Strategy 1: typeahead API
        try:
            suggest_url = "https://www.pinterest.com/api/v3/search/typeahead/"
            params = {"q": keyword, "scope": "boards", "count": 10}
            resp = requests.get(suggest_url, params=params, headers=suggest_headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                suggestions = data.get('results', [])
                result["suggestions"] = [
                    {"suggestion": s.get('term', ''), "source": "pinterest_suggest"}
                    for s in suggestions if s.get('term')
                ]
                _log(f"Typeahead: {len(result['suggestions'])} suggestions")
        except Exception as e:
            _log(f"Typeahead failed: {e}")

        # Strategy 2: autocomplete pins endpoint
        if not result["suggestions"]:
            try:
                url2 = "https://www.pinterest.com/autocomplete/pins/"
                resp2 = requests.get(url2, params={"q": keyword}, headers=suggest_headers, timeout=5)
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    sugs2 = data2.get('suggestions', [])
                    result["suggestions"] = [
                        {"suggestion": s.get('phrase', ''), "source": "pinterest_suggest"}
                        for s in sugs2 if s.get('phrase')
                    ]
                    _log(f"Fallback suggest: {len(result['suggestions'])}")
            except Exception as e:
                _log(f"Fallback suggest failed: {e}")

        # Strategy 3: parse suggest from search page JSON
        if not result["suggestions"]:
            try:
                search_url = f"https://www.pinterest.com/search/pins/?q={keyword}"
                resp3 = requests.get(search_url, headers=headers, timeout=8)
                if resp3.status_code == 200:
                    soup3 = BeautifulSoup(resp3.text, 'html.parser')
                    json_data = _extract_json_data(soup3)
                    if json_data:
                        _extract_suggestions_from_json(json_data, keyword, result)
                        if result["suggestions"]:
                            _log(f"Search page JSON suggest: {len(result['suggestions'])}")
            except Exception as e:
                _log(f"Search page suggest failed: {e}")

        # Strategy 4: parse search results page for related searches
        if not result["suggestions"]:
            try:
                search_url = f"https://www.pinterest.com/search/pins/?q={keyword}"
                resp4 = requests.get(search_url, headers=headers, timeout=8)
                if resp4.status_code == 200:
                    soup4 = BeautifulSoup(resp4.text, 'html.parser')
                    # Look for related search terms in page text
                    seen = set()
                    for tag in soup4.find_all(['a', 'span', 'div']):
                        text = tag.get_text(strip=True)
                        if text and keyword.lower() in text.lower() and len(text) > len(keyword) + 2 and text not in seen:
                            seen.add(text)
                            result["suggestions"].append({
                                "suggestion": text,
                                "source": "pinterest_suggest",
                            })
                    if result["suggestions"]:
                        result["suggestions"] = result["suggestions"][:15]
                        _log(f"Search page text suggest: {len(result['suggestions'])}")
            except Exception as e:
                _log(f"Search page text suggest failed: {e}")

        # Strategy 5: word-based fallback
        if not result["suggestions"]:
            words = keyword.strip().split()
            if len(words) >= 1:
                base = words[-1]
                fallback_suggestions = [
                    f"{keyword} gift",
                    f"{keyword} decor",
                    f"{keyword} t-shirt",
                    f"{keyword} mug",
                    f"{keyword} sticker",
                    f"{keyword} apparel",
                    f"{keyword} accessories",
                    f"{keyword} art",
                    f"{keyword} design",
                    f"{keyword} idea",
                ]
                result["suggestions"] = [
                    {"suggestion": s, "source": "pinterest_suggest"}
                    for s in fallback_suggestions
                ]
                _log(f"Word-based fallback suggest: {len(result['suggestions'])}")

        time.sleep(POD_PINTEREST_RATE_LIMIT)

    # Search Pinterest boards
    if mode in ["boards", "all"]:
        try:
            search_url = f"https://www.pinterest.com/search/boards/?q={keyword}"
            resp = requests.get(search_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')

                # Strategy 1: Try embedded JSON data
                json_data = _extract_json_data(soup)
                if json_data:
                    _extract_boards_from_json(json_data, result)

                # Strategy 2: data-test-id selector
                if not result["top_boards"]:
                    board_elements = soup.find_all('div', {'data-test-id': 'board-card'})[:10]
                    for board_elem in board_elements:
                        name_elem = board_elem.find(['h3', 'h2', 'div'], class_=re.compile(r'[Tt]itle|[Nn]ame'))
                        name = name_elem.get_text(strip=True) if name_elem else ''
                        all_text = board_elem.get_text()
                        followers = _parse_followers(all_text)
                        result["top_boards"].append({
                            "board_name": name,
                            "followers": followers,
                            "pin_count": 0,
                        })

                # Strategy 3: class-based selectors
                if not result["top_boards"]:
                    for cls_pattern in ['BoardCard', 'boardCard', 'board_card', 'board-card', 'boardcard']:
                        board_elements = soup.find_all('div', class_=re.compile(cls_pattern, re.I))[:10]
                        if board_elements:
                            for board_elem in board_elements:
                                name = board_elem.get('aria-label', '') or board_elem.get_text(strip=True)[:60]
                                followers = _parse_followers(board_elem.get_text())
                                result["top_boards"].append({
                                    "board_name": name,
                                    "followers": followers,
                                    "pin_count": 0,
                                })
                            break

                # Strategy 4: find board-like links
                if not result["top_boards"]:
                    for a in soup.find_all('a', href=re.compile(r'/[^/]+/[^/]+/?$')):
                        href = a.get('href', '')
                        text = a.get_text(strip=True)
                        if text and '/' in href[1:] and not href.startswith('/search') and len(text) > 2:
                            result["top_boards"].append({
                                "board_name": text,
                                "followers": 0,
                                "pin_count": 0,
                            })
                            if len(result["top_boards"]) >= 10:
                                break

                # Pin count estimate
                meta = soup.find('meta', {'name': 'description'})
                if meta:
                    m = re.search(r'([,\d]+)\s+results', meta.get('content', ''))
                    if m:
                        result["pin_count_estimate"] = int(m.group(1).replace(',', ''))

                _log(f"Boards: {len(result['top_boards'])} boards, ~{result['pin_count_estimate']} pins")
        except Exception as e:
            _log(f"Board search failed: {e}")

        time.sleep(POD_PINTEREST_RATE_LIMIT)

    # Get trending from Pinterest explore page
    if mode in ["trending", "all"]:
        try:
            trending_url = "https://www.pinterest.com/today/"
            resp = requests.get(trending_url, headers=headers, timeout=10)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                trending_items = []
                for a in soup.find_all('a', href=True):
                    href = a.get('href', '')
                    text = a.get_text(strip=True)
                    if '/ideas/' in href and text and len(text) > 3:
                        trending_items.append({
                            "trend": text,
                            "category": text,
                            "source": "pinterest_trending",
                        })
                if trending_items:
                    result["trending"] = trending_items[:15]
                    _log(f"Trending: {len(result['trending'])} items from Pinterest")
        except Exception as e:
            _log(f"Trending parse failed: {e}")
        
        # Fallback: richer set of known POD trends
        if not result["trending"]:
            result["trending"] = [
                {"trend": "Whimsical Art", "category": "Art"},
                {"trend": "Quote Typography", "category": "Typography"},
                {"trend": "Cute Animal Stickers", "category": "Stickers"},
                {"trend": "Minimalist Logo", "category": "Design"},
                {"trend": "Boho Rainbow", "category": "Patterns"},
                {"trend": "Retro 90s", "category": "Nostalgia"},
                {"trend": "Dark Academia", "category": "Aesthetic"},
                {"trend": "Cottagecore", "category": "Lifestyle"},
                {"trend": "Funny Sarcastic", "category": "Humor"},
                {"trend": "Watercolor Floral", "category": "Art"},
                {"trend": "Gradient Abstract", "category": "Design"},
                {"trend": "Vintage Travel", "category": "Travel"},
            ]
            _log(f"Trending: using fallback ({len(result['trending'])} items)")
    
    return result


def get_pinterest_boards(keyword: str) -> List[Dict[str, Any]]:
    """Get Pinterest boards related to a keyword."""
    result = scrape_pinterest_search(keyword, mode="boards")
    return result.get("top_boards", [])


if __name__ == "__main__":
    # Test
    result = scrape_pinterest_search("cat lover", mode="all")
    print(f"Suggestions: {len(result['suggestions'])}")
    print(f"Boards: {len(result['top_boards'])}")
    print(f"Pin estimate: {result['pin_count_estimate']}")

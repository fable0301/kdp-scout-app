"""
PodGoogleSuggest - Get Google Suggest queries for POD keywords.
Deep recursive mining with alphabetical expansion.
"""
import requests
from typing import List, Dict, Any, Set
from concurrent.futures import ThreadPoolExecutor, as_completed


def get_suggestions(keyword: str, prefix_with_product: bool = True, depth: int = 2) -> List[Dict[str, Any]]:
    """
    Get Google Suggest suggestions for a keyword with recursive expansion.
    
    Args:
        keyword: Base keyword
        prefix_with_product: If True, also get suggestions with product prefixes
        depth: Recursion depth for expansion (1 = base only, 2 = base + first expansion)
    
    Returns:
        List of suggestion dicts with 'suggestion' key
    """
    results = []
    seen: Set[str] = set()
    
    # Base suggestions
    base_sugs = _fetch_google_suggest(keyword)
    for sug in base_sugs:
        if sug not in seen and len(sug) >= 3:
            seen.add(sug)
            results.append({"suggestion": sug, "source": "google_suggest"})
    
    # With product prefixes
    if prefix_with_product:
        products = ["t-shirt", "mug", "sticker", "gift for", "design", "funny"]
        for product in products:
            query = f"{product} {keyword}"
            product_sugs = _fetch_google_suggest(query)
            for sug in product_sugs:
                if sug not in seen and len(sug) >= 3:
                    seen.add(sug)
                    results.append({"suggestion": sug, "source": "google_suggest"})
    
    # Recursive + alphabetical expansion only if depth > 1
    if depth > 1:
        new_seeds = list(seen)[:15]
        expanded = _expand_recursively(new_seeds, seen, depth - 1)
        for exp in expanded:
            if exp not in seen:
                seen.add(exp)
                results.append({"suggestion": exp, "source": "google_suggest"})
        
        alpha_expansions = _expand_alphabetically(keyword, seen)
        for exp in alpha_expansions:
            if exp not in seen:
                seen.add(exp)
                results.append({"suggestion": exp, "source": "google_suggest"})
    
    return results


def _expand_recursively(seeds: List[str], seen: Set[str], remaining_depth: int) -> List[str]:
    """Recursively expand seeds (low concurrency to avoid rate limits)."""
    if remaining_depth <= 0 or not seeds:
        return []
    
    expanded = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_map = {pool.submit(_fetch_google_suggest, seed): seed for seed in seeds}
        for f in as_completed(fut_map):
            try:
                results = f.result()
                for r in results:
                    if r not in seen and len(r) >= 3:
                        expanded.append(r)
                        seen.add(r)
            except Exception:
                pass
    
    if remaining_depth > 1 and expanded:
        more = _expand_recursively(expanded[:10], seen, remaining_depth - 1)
        expanded.extend(more)
    
    return expanded


def _expand_alphabetically(base_keyword: str, seen: Set[str]) -> List[str]:
    """Expand with alphabetical suffixes (base + a, base + b, etc.)."""
    expanded = []
    letters = "abcdefghijklmnopqrstuvwxyz"
    
    def fetch_and_collect(query: str) -> List[str]:
        results = _fetch_google_suggest(query)
        return [r for r in results if r not in seen and len(r) >= 3]
    
    with ThreadPoolExecutor(max_workers=6) as pool:
        fut_map = {}
        # Suffixes: "cat a", "cat b", ...
        for letter in letters:
            query = f"{base_keyword} {letter}"
            fut_map[pool.submit(fetch_and_collect, query)] = query
        
        # Prefixes: "a cat", "b cat", ...
        for letter in letters:
            query = f"{letter} {base_keyword}"
            fut_map[pool.submit(fetch_and_collect, query)] = query
        
        for f in as_completed(fut_map):
            try:
                results = f.result()
                expanded.extend(results)
            except Exception:
                pass
    
    return expanded


def _fetch_google_suggest(query: str) -> List[str]:
    """Fetch suggestions from Google Suggest with multiple fallback strategies."""
    import time
    
    # Strategy 1: googlesearch-python library (web scraping, bypasses API blocks)
    try:
        from googlesearch import search
        for attempt in range(2):
            try:
                results = list(search(query, num_results=8, lang="en", timeout=8))
                if results:
                    # Extract keywords from result page titles via URL patterns
                    keywords = []
                    for url in results:
                        # Parse URL path for potential keywords
                        path = url.replace("https://", "").replace("http://", "").split("/")
                        for part in path:
                            clean = part.replace("-", " ").replace("_", " ").replace("+", " ").strip()
                            if len(clean) > 4 and query.lower() in clean.lower():
                                keywords.append(clean.title())
                    if keywords:
                        return keywords
                if attempt == 0:
                    time.sleep(1)
            except Exception:
                if attempt == 0:
                    time.sleep(1)
    except ImportError:
        pass
    
    # Strategy 2: Direct API with browser-like headers
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    url = "https://suggestqueries.google.com/complete/search"
    params = {"q": query, "client": "chrome", "hl": "en"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        if resp.status_code == 200:
            text = resp.text
            if text.startswith(")]}"):
                text = text[5:] if ")]}'\n" in text[:6] else text[4:]
            import json
            data = json.loads(text)
            if isinstance(data, list) and len(data) >= 2:
                sugs = data[1]
                if isinstance(sugs, list):
                    return [str(s[0]).strip() if isinstance(s, list) else str(s).strip() for s in sugs]
    except Exception:
        pass
    
    return []


if __name__ == "__main__":
    # Test deep mining
    sugs = get_suggestions("cat", depth=2)
    print(f"Found {len(sugs)} suggestions")
    for sug in sugs[:20]:
        print(f"  {sug['suggestion']}")

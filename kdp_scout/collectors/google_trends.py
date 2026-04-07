"""Google Trends collector for KDP keyword research.

Uses pytrends (unofficial Google Trends API) when available,
falls back to Google Suggest-based trend detection.
No API key needed.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from pytrends.request import TrendReq
    _HAS_PYTRENDS = True
except ImportError:
    _HAS_PYTRENDS = False


def has_pytrends():
    return _HAS_PYTRENDS


def get_interest_over_time(keywords, timeframe="today 12-m"):
    """Get Google Trends interest over time for up to 5 keywords.

    Returns dict: {keyword: [{date, value}, ...]}
    """
    if not _HAS_PYTRENDS:
        return {}
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 20),
                            retries=2, backoff_factor=0.5)
        kw_list = keywords[:5]
        pytrends.build_payload(kw_list, cat=22, timeframe=timeframe, geo="US")
        df = pytrends.interest_over_time()
        if df.empty:
            return {}
        result = {}
        for kw in kw_list:
            if kw in df.columns:
                result[kw] = [
                    {"date": str(idx.date()), "value": int(row[kw])}
                    for idx, row in df.iterrows()
                ]
        return result
    except Exception as e:
        logger.error(f"Google Trends interest_over_time failed: {e}")
        return {}


def get_related_queries(keyword):
    """Get related queries for a keyword from Google Trends.

    Returns dict with 'top' and 'rising' lists of dicts.
    """
    if not _HAS_PYTRENDS:
        return {"top": [], "rising": []}
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 20),
                            retries=2, backoff_factor=0.5)
        pytrends.build_payload([keyword], cat=22, timeframe="today 12-m", geo="US")
        related = pytrends.related_queries()
        result = {"top": [], "rising": []}
        if keyword in related:
            top_df = related[keyword].get("top")
            if top_df is not None and not top_df.empty:
                result["top"] = top_df.to_dict("records")
            rising_df = related[keyword].get("rising")
            if rising_df is not None and not rising_df.empty:
                result["rising"] = rising_df.to_dict("records")
        return result
    except Exception as e:
        logger.error(f"Google Trends related_queries failed: {e}")
        return {"top": [], "rising": []}


def get_trending_searches(geo="US"):
    """Get today's trending searches from Google Trends RSS feed.

    Returns list of dicts: [{"query": str, "traffic": str}, ...]
    No API key or pytrends needed — uses public RSS feed.
    """
    import urllib.request
    import xml.etree.ElementTree as ET

    url = f"https://trends.google.com/trending/rss?geo={geo}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read().decode("utf-8")

        root = ET.fromstring(raw)
        ns = {"ht": "https://trends.google.com/trending/rss"}
        items = root.findall(".//item")

        results = []
        for item in items:
            title = item.findtext("title", "").strip()
            traffic = item.findtext("ht:approx_traffic", "", ns).strip()
            if title:
                results.append({"query": title, "traffic": traffic})
        logger.info(f"Google Trends RSS: fetched {len(results)} trending searches for {geo}")
        return results
    except Exception as e:
        logger.error(f"Google Trends RSS failed: {e}")
        return []


def get_trending_book_searches(geo="US", niche_keywords=None,
                                progress_callback=None, cancel_check=None):
    """Get trending searches enriched with book-related suggestions.

    Args:
        geo: Country code for trends (default "US").
        niche_keywords: Optional list of niche keywords (e.g. ["romance", "fantasy"]).
                        If provided:
                        - Filters raw trends to those containing any niche keyword.
                        - Uses niche keywords as enrichment suffixes instead of
                          the default ["book", "kindle", "novel"].
        progress_callback: Optional callable(current, total).
        cancel_check: Optional callable() -> bool. Return True to abort.
    Returns list of dicts: [{"query": str, "traffic": str, "source": str}, ...]
    """
    from kdp_scout.collectors.google_suggest import query_google_suggest

    def _cancelled():
        return cancel_check and cancel_check()

    trends = get_trending_searches(geo=geo)
    if _cancelled():
        return []
    results = []

    # Filter trends by niche keywords if provided
    if niche_keywords:
        niches_lower = [n.lower() for n in niche_keywords]
        filtered = [t for t in trends
                    if any(n in t["query"].lower() for n in niches_lower)]
        display_trends = filtered  # don't fallback — user wants niche results only
    else:
        display_trends = trends

    # Add raw trending searches
    for item in display_trends:
        results.append({
            "query": item["query"],
            "traffic": item.get("traffic", ""),
            "source": "Google Trending Now",
        })

    # Enrich top trends with book-related suggestions
    if niche_keywords:
        book_suffixes = [f" {n}" for n in niche_keywords[:5]]
    else:
        book_suffixes = [" book", " kindle", " novel"]

    # Also enrich with niche + "book" for better results when niche is set
    if niche_keywords:
        # Also enrich each niche keyword directly (not tied to a trend)
        for nk in niche_keywords[:5]:
            for bsuf in [" book", " kindle", " novel", " bestseller"]:
                seed = nk + bsuf
                if _cancelled():
                    return results
                try:
                    suggestions = query_google_suggest(seed)
                    seen = {r["query"].lower() for r in results}
                    for kw, pos in suggestions:
                        if kw.lower() not in seen:
                            seen.add(kw.lower())
                            results.append({
                                "query": kw,
                                "traffic": "",
                                "source": f"Niche Suggest: {nk}",
                            })
                except Exception:
                    pass

    seen = {r["query"].lower() for r in results}
    enrich_trends = display_trends[:10] if display_trends else trends[:10]
    total_ops = len(enrich_trends) * len(book_suffixes)
    done = 0

    for item in enrich_trends:
        for suffix in book_suffixes:
            if _cancelled():
                return results
            seed = item["query"] + suffix
            try:
                suggestions = query_google_suggest(seed)
                for kw, pos in suggestions:
                    if kw.lower() not in seen:
                        seen.add(kw.lower())
                        results.append({
                            "query": kw,
                            "traffic": item.get("traffic", ""),
                            "source": f"Suggest: {item['query']}",
                        })
            except Exception:
                pass
            done += 1
            if progress_callback:
                progress_callback(done, total_ops)

    return results


def get_related_topics(keyword):
    """Get related topics for a keyword.

    Returns dict with 'top' and 'rising' lists.
    """
    if not _HAS_PYTRENDS:
        return {"top": [], "rising": []}
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(10, 20),
                            retries=2, backoff_factor=0.5)
        pytrends.build_payload([keyword], cat=22, timeframe="today 12-m", geo="US")
        topics = pytrends.related_topics()
        result = {"top": [], "rising": []}
        if keyword in topics:
            top_df = topics[keyword].get("top")
            if top_df is not None and not top_df.empty:
                result["top"] = top_df.to_dict("records")
            rising_df = topics[keyword].get("rising")
            if rising_df is not None and not rising_df.empty:
                result["rising"] = rising_df.to_dict("records")
        return result
    except Exception as e:
        logger.error(f"Google Trends related_topics failed: {e}")
        return {"top": [], "rising": []}

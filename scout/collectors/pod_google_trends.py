"""
PodGoogleTrends - Get Google Trends data for POD keywords.
"""
try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except ImportError:
    PYTRENDS_AVAILABLE = False
    print("Warning: pytrends not installed. Google Trends will be unavailable.")


def get_trends(keyword: str, timeframe: str = "today 12-m") -> dict:
    """
    Get Google Trends data for a POD keyword.
    
    Args:
        keyword: The keyword to analyze
        timeframe: Timeframe (default: last 12 months)
    
    Returns:
        Dict with interest_over_time, related_queries_top, related_queries_rising
    """
    if not PYTRENDS_AVAILABLE:
        return {
            "interest_over_time": {},
            "related_queries_top": [],
            "related_queries_rising": [],
            "avg_interest": 0.0,
        }
    
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        pytrends.build_payload(
            kw_list=[keyword],
            cat=18,  # Shopping category (includes apparel)
            timeframe=timeframe,
            geo='US',
        )
        
        # Interest over time
        interest_df = pytrends.interest_over_time()
        interest_over_time = {}
        if not interest_df.empty:
            for date, row in interest_df.iterrows():
                interest_over_time[date.strftime('%Y-%m-%d')] = int(row[keyword])
        
        # Related queries
        related = pytrends.related_queries()
        top_queries = []
        rising_queries = []
        
        if related and keyword in related:
            if 'top' in related[keyword]:
                for item in related[keyword]['top'].iterrows():
                    top_queries.append({
                        "query": item[1]['query'],
                        "value": int(item[1]['value']),
                    })
            
            if 'rising' in related[keyword]:
                for item in related[keyword]['rising'].iterrows():
                    rising_queries.append({
                        "query": item[1]['query'],
                        "value": int(item[1]['value']),
                    })
        
        avg_interest = round(sum(interest_over_time.values()) / len(interest_over_time), 1) if interest_over_time else 0.0
        return {
            "interest_over_time": interest_over_time,
            "related_queries_top": top_queries[:10],
            "related_queries_rising": rising_queries[:10],
            "avg_interest": avg_interest,
        }
    
    except Exception:
        return {
            "interest_over_time": {},
            "related_queries_top": [],
            "related_queries_rising": [],
        }


def compare_trends(keywords: list, timeframe: str = "today 12-m") -> dict:
    """
    Compare multiple keywords on Google Trends.
    
    Returns:
        Dict with comparison data
    """
    if not PYTRENDS_AVAILABLE:
        return {"comparison": []}
    
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        pytrends.build_payload(
            kw_list=keywords[:5],  # Max 5 at a time
            cat=18,
            timeframe=timeframe,
            geo='US',
        )
        
        interest_df = pytrends.interest_over_time()
        comparison = []
        
        if not interest_df.empty:
            for keyword in keywords[:5]:
                avg = interest_df[keyword].mean()
                comparison.append({
                    "keyword": keyword,
                    "avg_interest": int(avg),
                })
        
        return {"comparison": comparison}
    
    except Exception:
        return {"comparison": []}


if __name__ == "__main__":
    # Test
    if PYTRENDS_AVAILABLE:
        result = get_trends("cat lover")
        print(f"Top queries: {len(result['related_queries_top'])}")
        print(f"Rising queries: {len(result['related_queries_rising'])}")
    else:
        print("pytrends not available")

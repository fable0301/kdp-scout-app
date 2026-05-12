from scout.gui.workers.base_worker import BaseWorker
from scout.collectors import pod_merch_autocomplete, pod_etsy_scraper, pod_redbubble_scraper
from scout.collectors import pod_pinterest_scraper, pod_google_suggest
from scout.collectors import pod_reddit_trends, pod_google_trends, pod_spreadshirt_scraper
from scout.pod_scorer import score_pod_keyword, POD_DEFAULT_WEIGHTS
from scout.db import PodKeywordRepository
from concurrent.futures import ThreadPoolExecutor, as_completed


class PodMineWorker(BaseWorker):
    """Mine POD keywords from Merch autocomplete + Google Suggest + Etsy + Pinterest."""

    def __init__(self, seed, platform="all", product_type=None, depth=2, parent=None):
        super().__init__(parent)
        self.seed = seed
        self.platform = platform
        self.product_type = product_type
        self.depth = depth

    def run_task(self):
        self.status.emit(f"Mining '{self.seed}'...")
        self.log.emit(f"Seed: {self.seed} | depth={self.depth}")
        keywords = []

        try:
            self.log.emit("Mining Merch autocomplete...")
            merch_keywords = pod_merch_autocomplete.mine_merch_autocomplete(
                self.seed, marketplace="us", depth=self.depth
            )
            for kw in merch_keywords:
                kw["source"] = "merch"
                kw["platform"] = "merch"
            keywords.extend(merch_keywords)
            self.progress.emit(25, 100)

            if self.platform in ["all", "etsy"]:
                self.log.emit("Scraping Etsy suggestions...")
                etsy_data = pod_etsy_scraper.scrape_etsy_search(self.seed)
                for sug in etsy_data.get("suggestions", []):
                    keywords.append({
                        "keyword": sug.get("suggestion", ""),
                        "source": "etsy",
                        "platform": "etsy",
                        "etsy_competition": etsy_data.get("competition_count", 0),
                        "avg_price": etsy_data.get("avg_price", 0.0),
                    })
                self.progress.emit(45, 100)

            if self.platform in ["all", "pinterest"]:
                self.log.emit("Scraping Pinterest...")
                pinterest_data = pod_pinterest_scraper.scrape_pinterest_search(self.seed)
                for sug in pinterest_data.get("suggestions", []):
                    keywords.append({
                        "keyword": sug.get("suggestion", ""),
                        "source": "pinterest",
                        "platform": "pinterest",
                        "pinterest_board_followers": (pinterest_data.get("top_boards") or [{}])[0].get("followers", 0),
                        "pinterest_pin_count": pinterest_data.get("pin_count_estimate", 0),
                    })
                self.progress.emit(65, 100)

            self.log.emit("Getting Google Suggest...")
            google_sugs = pod_google_suggest.get_suggestions(self.seed)
            for sug in google_sugs:
                keywords.append({
                    "keyword": sug.get("suggestion", ""),
                    "source": "google_suggest",
                    "platform": "google",
                })
            self.progress.emit(85, 100)

            # Deduplicate
            seen = set()
            unique = []
            for kw in keywords:
                kw_text = kw.get("keyword", "").strip().lower()
                if kw_text and kw_text not in seen:
                    seen.add(kw_text)
                    unique.append(kw)

            self.log.emit(f"Found {len(unique)} unique keywords")
            self.progress.emit(100, 100)
            return unique

        except Exception as e:
            self.log.emit(f"Error: {e}")
            raise


class PodMineAmazonWorker(BaseWorker):
    """Mine keywords from Amazon Merch autocomplete ONLY."""

    def __init__(self, seed, product_type="all", marketplace="us", depth=2, parent=None):
        super().__init__(parent)
        self.seed = seed
        self.product_type = product_type
        self.marketplace = marketplace
        self.depth = depth

    def run_task(self):
        self.status.emit(f"Mining Amazon Merch: '{self.seed}'...")
        self.log.emit(f"Marketplace: {self.marketplace.upper()} | Product: {self.product_type} | Depth: {self.depth}")
        try:
            results = pod_merch_autocomplete.mine_merch_autocomplete(
                self.seed,
                marketplace=self.marketplace,
                product_type=self.product_type,
                depth=self.depth,
            )
            self.progress.emit(100, 100)
            self.log.emit(f"Found {len(results)} keywords from Merch autocomplete")
            return results
        except Exception as e:
            self.log.emit(f"Error: {e}")
            raise


class PodScoreWorker(BaseWorker):
    """Score a list of POD keywords using pod_scorer."""

    def __init__(self, keywords, parent=None):
        super().__init__(parent)
        self.keywords = keywords

    def run_task(self):
        self.status.emit("Scoring keywords...")
        self.log.emit(f"Scoring {len(self.keywords)} keywords...")
        scored = []
        total = len(self.keywords)
        for i, kw in enumerate(self.keywords):
            score = score_pod_keyword(kw, weights=POD_DEFAULT_WEIGHTS)
            kw["score"] = score
            scored.append(kw)
            self.progress.emit(int((i + 1) / total * 100), 100)
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        if scored:
            self.log.emit(f"Top score: {scored[0]['score']:.2f} — {scored[0].get('keyword','')}")
        return scored


class PodTrendingWorker(BaseWorker):
    """Get POD trending niches from Reddit + Google Trends + Pinterest."""

    def __init__(self, period_days=30, category="all", parent=None):
        super().__init__(parent)
        self.period_days = period_days
        self.category = category

    def run_task(self):
        self.status.emit("Fetching POD trends...")
        results = []

        # Reddit trends
        self.log.emit("Mining Reddit POD subreddits...")
        try:
            reddit_data = pod_reddit_trends.mine_pod_reddit_trends()
            for item in reddit_data[:15]:
                results.append({
                    "niche": item.get("keyword", ""),
                    "score": item.get("score", 0),
                    "source": "reddit",
                    "platform": ", ".join(item.get("subreddits", [])),
                    "pinterest_pins": item.get("posts", 0),
                    "demand": item.get("demand", ""),
                })
            self.progress.emit(40, 100)
        except Exception as e:
            self.log.emit(f"Reddit error: {e}")

        # Google Trends rising queries
        self.log.emit("Checking Google Trends rising queries...")
        try:
            seeds = ["t-shirt design", "custom mug", "funny sticker", "gift idea"]
            for seed in seeds:
                try:
                    trends_data = pod_google_trends.get_trends(seed, timeframe="today 3-m")
                    for q in trends_data.get("related_queries_rising", [])[:5]:
                        results.append({
                            "niche": q.get("query", ""),
                            "score": min(1.0, q.get("value", 0) / 100.0),
                            "source": "google_trends",
                            "platform": "Google",
                            "pinterest_pins": 0,
                            "demand": "rising",
                        })
                except Exception:
                    pass
            self.progress.emit(70, 100)
        except Exception as e:
            self.log.emit(f"Google Trends error: {e}")

        # Pinterest trending
        self.log.emit("Checking Pinterest trending...")
        try:
            pinterest_data = pod_pinterest_scraper.scrape_pinterest_search("trending design")
            for item in pinterest_data.get("trending", [])[:10]:
                results.append({
                    "niche": item.get("trend", ""),
                    "score": 0.7,
                    "source": "pinterest",
                    "platform": item.get("category", "Pinterest"),
                    "pinterest_pins": 0,
                    "demand": "trending",
                })
            self.progress.emit(100, 100)
        except Exception as e:
            self.log.emit(f"Pinterest error: {e}")

        # Sort by score
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        self.log.emit(f"Found {len(results)} trending niches")
        return results


class PodNicheAnalyzerWorker(BaseWorker):
    """Full multi-source analysis pipeline for a POD niche."""

    def __init__(self, niche, platform="all", parent=None):
        super().__init__(parent)
        self.niche = niche
        self.platform = platform

    def run_task(self):
        self.status.emit(f"Analyzing: {self.niche}")
        self.log.emit("Step 1: Mining keywords...")

        miner = PodMineWorker(self.niche, self.platform, depth=2)
        keywords = miner.run_task()
        self.progress.emit(35, 100)

        self.log.emit("Step 2: Scoring keywords...")
        scorer = PodScoreWorker(keywords)
        scored = scorer.run_task()
        self.progress.emit(55, 100)

        # Aggregate scores for gauges
        demand_score = 0.0
        competition_score = 1.0
        trend_score = 0.0
        virality_score = 0.0
        avg_prices = []

        self.log.emit("Step 3: Fetching Redbubble competition...")
        try:
            rb_data = pod_redbubble_scraper.scrape_redbubble_search(self.niche)
            rb_count = rb_data.get("competition_count", 0)
            competition_score = min(1.0, max(0.0, 1.0 - rb_count / 50000))
        except Exception as e:
            self.log.emit(f"Redbubble error: {e}")
        self.progress.emit(65, 100)

        self.log.emit("Step 4: Checking Pinterest demand...")
        try:
            p_data = pod_pinterest_scraper.scrape_pinterest_search(self.niche)
            followers = (p_data.get("top_boards") or [{}])[0].get("followers", 0)
            pin_count = p_data.get("pin_count_estimate", 0)
            virality_score = min(1.0, followers / 10000) * 0.6 + min(1.0, pin_count / 10000) * 0.4
            demand_score += virality_score * 0.4
        except Exception as e:
            self.log.emit(f"Pinterest error: {e}")
        self.progress.emit(75, 100)

        self.log.emit("Step 5: Checking Google Trends...")
        try:
            trends_data = pod_google_trends.get_trends(self.niche, timeframe="today 12-m")
            avg_trend = trends_data.get("avg_interest", 0) / 100.0
            trend_score = avg_trend
            demand_score = min(1.0, demand_score + avg_trend * 0.6)
        except Exception as e:
            self.log.emit(f"Google Trends error: {e}")
        self.progress.emit(85, 100)

        # Profitability from avg price
        for kw in scored[:10]:
            p = kw.get("avg_price", 0) or 0
            if p > 0:
                avg_prices.append(p)
        avg_price = sum(avg_prices) / len(avg_prices) if avg_prices else 22.0
        profitability_score = 1.0 if 20 <= avg_price <= 35 else (0.7 if avg_price > 15 else 0.3)

        global_score = (
            demand_score * 0.30 +
            competition_score * 0.25 +
            profitability_score * 0.20 +
            trend_score * 0.15 +
            virality_score * 0.10
        )

        self.log.emit("Analysis complete!")
        self.progress.emit(100, 100)
        return {
            "niche": self.niche,
            "keywords": scored[:20],
            "demand_score": round(demand_score, 3),
            "competition_score": round(competition_score, 3),
            "profitability_score": round(profitability_score, 3),
            "trend_score": round(trend_score, 3),
            "visual_virality": round(virality_score, 3),
            "global_score": round(global_score, 3),
        }


class PodFindForMeWorker(BaseWorker):
    """Automatically discover profitable POD niches from seed categories.

    STABLE VERSION - Optimized for reliability and low CPU usage:
      - Phase 1: Multi-threaded mining with LOW concurrency (8 threads)
      - Phase 2: Simple scoring based on keyword specificity
      - No recursive explosion, no aggressive scraping
      - Only uses Google Suggest with safe parameters
    
    Key improvements:
      - Stable execution: No CPU overload, no SSL errors
      - Good volume: 50-200 keywords per seed via alphabetical expansion only
      - Specificity-based scoring: Long-tail keywords = higher opportunity score
      - Fast execution: Parallel processing with limited ThreadPoolExecutor
      - Resilient: Handles Google blocks gracefully
    """

    MINING_THREADS = 8  # Reduced from 50 to prevent CPU overload and SSL blocks

    def __init__(self, product_type="all", competition_level="medium", category="all", parent=None):
        super().__init__(parent)
        self.product_type = product_type
        self.competition_level = competition_level
        self.category = category

    def run_task(self):
        self.status.emit("Discovering profitable niches...")
        
        # ── Step 0: Get seeds ───────────
        from scout.pod_seeds import get_all_seeds
        
        base_seeds = get_all_seeds(category=self.category, limit_per_category=8)
        if not base_seeds:
            self.log.emit("No seed keywords found for this category!")
            return []
        
        # Add some evergreen POD seeds
        evergreen = ["funny", "gift", "cute", "vintage", "retro"]
        all_seeds = list(base_seeds)
        for eg in evergreen:
            if eg not in all_seeds:
                all_seeds.append(eg)
        
        self.log.emit(f"🚀 Starting mining with {len(all_seeds)} seeds...")
        self.log.emit("   Using safe Google Suggest expansion (depth=1)")

        # ── Phase 1: Mine all seeds in parallel (LOW concurrency) ───────────
        all_keywords = {}
        done = 0
        total = len(all_seeds)
        
        with ThreadPoolExecutor(max_workers=self.MINING_THREADS) as pool:
            fut_map = {pool.submit(self._mine_seed_safe, s): s for s in all_seeds}
            for f in as_completed(fut_map):
                if self.is_cancelled:
                    break
                done += 1
                pct = int(done / total * 60)  # 60% of progress for mining
                self.progress.emit(pct, 100)
                try:
                    seed_keywords = f.result()
                    seed_name = fut_map[f]
                    self.log.emit(f"  ✓ {seed_name}: {len(seed_keywords)} keywords mined")
                    for kw in seed_keywords:
                        text = kw.get("keyword", "").strip().lower()
                        if text and text not in all_keywords:
                            all_keywords[text] = kw
                except Exception as e:
                    self.log.emit(f"  ✗ Error on '{fut_map[f]}': {e}")

        if self.is_cancelled:
            return []
        
        self.log.emit(f"\n📊 Total unique keywords mined: {len(all_keywords)}")
        
        # ── Phase 2: Score all keywords ───────────
        self.status.emit("Scoring keywords by specificity...")
        self.progress.emit(65, 100)
        
        scored = []
        for text, kw in all_keywords.items():
            score_data = self._compute_specificity_score(kw)
            kw["global_score"] = score_data["global_score"]
            kw["opportunity_score"] = score_data["opportunity_score"]
            kw["specificity_score"] = score_data["specificity_score"]
            kw["depth_score"] = score_data["depth_score"]
            kw["trend_score"] = score_data["trend_score"]
            scored.append(kw)
        
        # Sort by opportunity score (descending)
        scored.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)
        
        self.progress.emit(85, 100)
        if scored:
            self.log.emit(f"✅ Top keyword: {scored[0].get('keyword', 'N/A')} (score: {scored[0].get('opportunity_score', 0):.3f})")
        else:
            self.log.emit("⚠️ No keywords found. Try different seeds.")
        
        # Apply competition filter
        filtered = self._apply_competition_filter(scored)
        
        self.progress.emit(100, 100)
        self.log.emit(f"\n🎯 Final results: {len(filtered)} keywords after filtering")
        
        return filtered[:500]  # Return top 500

    def _mine_seed_safe(self, seed):
        """Mine a single seed from Google Suggest + fallback Merch Autocomplete."""
        from scout.collectors import pod_google_suggest, pod_merch_autocomplete
        
        keywords = []
        seen = set()
        
        # Primary source: Google Suggest
        suggestions = pod_google_suggest.get_suggestions(seed, prefix_with_product=True, depth=1)
        
        for sug in suggestions:
            text = sug.get("suggestion", "").strip().lower()
            if text and len(text) >= 3 and text not in seen:
                seen.add(text)
                word_count = len(text.split())
                keywords.append(self._make_keyword_dict(text, seed, "google_suggest", word_count))
        
        # Fallback source: Merch Autocomplete (if Google returned nothing)
        if not keywords:
            try:
                merch_kws = pod_merch_autocomplete.mine_merch_autocomplete(seed, depth=1)
                for i, kw in enumerate(merch_kws):
                    text = kw.get("keyword", "").strip().lower()
                    if text and len(text) >= 3 and text not in seen:
                        seen.add(text)
                        d = self._make_keyword_dict(text, seed, "merch", len(text.split()))
                        d["merch_position"] = i + 1
                        keywords.append(d)
            except Exception:
                pass
        
        return keywords

    def _make_keyword_dict(self, text, seed, source, word_count):
        return {
            "keyword": text,
            "niche": text,
            "source": source,
            "seed": seed,
            "word_count": word_count,
            "merch_position": None,
            "etsy_competition": 0,
            "rb_competition": 0,
            "etsy_avg_price": 0.0,
            "rb_avg_price": 0.0,
            "google_trends_avg": 0,
            "google_trends_velocity": 0.0,
            "google_trends_trend": "",
            "google_trends_breakout": 0,
            "google_suggest_count": word_count,
        }

    def _compute_specificity_score(self, kw):
        """
        Compute scores based on keyword specificity, depth, and trend potential.
        Logic: Longer, more specific keywords = less competition = higher opportunity.
        Trend keywords: words that perform well on Pinterest get a score boost.
        """
        text = kw.get("keyword", "")
        word_count = len(text.split())
        char_count = len(text)
        
        # Specificity score: based on word count (long-tail = better)
        # 1 word: 0.2, 2 words: 0.5, 3 words: 0.8, 4+ words: 1.0
        if word_count >= 4:
            specificity = 1.0
        elif word_count == 3:
            specificity = 0.8
        elif word_count == 2:
            specificity = 0.5
        else:
            specificity = 0.2
        
        # Depth score: keywords with product prefixes are more actionable
        has_product_prefix = any(
            text.startswith(prefix) 
            for prefix in ["t-shirt ", "mug ", "sticker ", "gift for ", "design ", "funny "]
        )
        depth_bonus = 0.15 if has_product_prefix else 0.0
        
        # Length bonus: longer keywords (by chars) tend to be more specific
        length_bonus = min(0.1, char_count / 500)  # Max 0.1 bonus at 50 chars
        
        # Trend score: heuristic Pinterest trend potential based on keyword content
        trend_words = ["gift", "idea", "design", "decor", "wall art",
                       "style", "love", "cute", "funny", "custom",
                       "personalized", "room", "home", "aesthetic",
                       "inspiration", "minimalist", "boho", "vintage",
                       "retro", "modern", "unique", "cool", "best"]
        trend_matches = sum(1 for w in trend_words if w in text.lower())
        trend_score = round(min(1.0, trend_matches * 0.25), 2)  # Up to 1.0
        
        # Global score: combination of factors
        global_score = round(min(1.0, specificity * 0.5 + depth_bonus + length_bonus + trend_score * 0.15), 3)
        
        # Opportunity score: boost global score for long-tail keywords
        opportunity_multiplier = 1.0 + (specificity * 0.3)
        opportunity_score = round(min(1.0, global_score * opportunity_multiplier), 3)
        
        return {
            "global_score": global_score,
            "opportunity_score": opportunity_score,
            "specificity_score": round(specificity, 3),
            "depth_score": round(depth_bonus + length_bonus, 3),
            "trend_score": trend_score,
        }

    def _apply_competition_filter(self, results):
        """Filter by desired competition level based on specificity."""
        level = self.competition_level
        if level == "any":
            return results
        
        filtered = []
        for r in results:
            spec = r.get("specificity_score", 0.5)
            
            # Low competition = high specificity only (long-tail keywords)
            if level == "low" and spec < 0.7:
                continue
            
            # High competition = include broader keywords
            if level == "high" and spec > 0.8:
                continue
            
            # Medium = include almost everything except extremes
            # Keep keywords with specificity between 0.1 and 1.0 (inclusive)
            if level == "medium" and (spec < 0.1 or spec > 1.0):
                continue
            
            filtered.append(r)
        
        return filtered


class PodCompetitorsWorker(BaseWorker):
    """Scrape top POD listings for a niche on a given platform."""

    def __init__(self, niche, platform, parent=None):
        super().__init__(parent)
        self.niche = niche
        self.platform = platform

    def run_task(self):
        self.status.emit(f"Scraping {self.platform} for: {self.niche}")
        self.log.emit(f"Platform: {self.platform} | Niche: {self.niche}")
        listings = []

        try:
            if self.platform.lower() in ["etsy", "all"]:
                self.log.emit("Scraping Etsy...")
                data = pod_etsy_scraper.scrape_etsy_search(self.niche)
                for l in data.get("top_listings", []):
                    l["platform"] = "etsy"
                    listings.append(l)
                self.progress.emit(40, 100)

            if self.platform.lower() in ["redbubble", "all"]:
                self.log.emit("Scraping Redbubble...")
                data = pod_redbubble_scraper.scrape_redbubble_search(self.niche)
                for l in data.get("top_works", []):
                    l["platform"] = "redbubble"
                    listings.append(l)
                self.progress.emit(70, 100)

            if self.platform.lower() in ["spreadshirt", "all"]:
                self.log.emit("Scraping Spreadshirt...")
                data = pod_spreadshirt_scraper.scrape_spreadshirt_search(self.niche)
                for l in data.get("top_designs", []):
                    l["platform"] = "spreadshirt"
                    listings.append(l)
                self.progress.emit(90, 100)

        except Exception as e:
            self.log.emit(f"Scrape error: {e}")

        self.progress.emit(100, 100)
        self.log.emit(f"Found {len(listings)} listings")
        return listings


class PodProductLookupWorker(BaseWorker):
    """Scrape POD product data from a URL (Etsy/Redbubble/Merch/Spreadshirt)."""

    def __init__(self, url_or_id, parent=None):
        super().__init__(parent)
        self.url_or_id = url_or_id

    def run_task(self):
        self.status.emit("Looking up product...")
        self.log.emit(f"Input: {self.url_or_id}")
        import re
        import requests
        from bs4 import BeautifulSoup

        url = self.url_or_id.strip()
        result = {"title": "", "keywords": [], "price": 0.0, "reviews": 0, "seller": "", "platform": "", "url": url}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        try:
            if "etsy.com" in url:
                result["platform"] = "etsy"
                self.log.emit("Fetching Etsy listing...")
                resp = requests.get(url, headers=headers, timeout=12)
                soup = BeautifulSoup(resp.text, "html.parser")
                title_elem = soup.find("h1", {"data-buy-box-listing-title": True}) or soup.find("h1")
                if title_elem:
                    result["title"] = title_elem.get_text(strip=True)
                tags = [t.get_text(strip=True) for t in soup.find_all("a", {"href": re.compile(r"/search\?q=")})]
                result["keywords"] = list(dict.fromkeys(tags))[:20]
                price_elem = soup.find("p", {"data-buy-box-region": "price"}) or soup.find(class_=re.compile(r"price"))
                if price_elem:
                    m = re.search(r"[\d.,]+", price_elem.get_text())
                    if m:
                        result["price"] = float(m.group().replace(",", ""))

            elif "redbubble.com" in url:
                result["platform"] = "redbubble"
                self.log.emit("Fetching Redbubble work...")
                resp = requests.get(url, headers=headers, timeout=12)
                soup = BeautifulSoup(resp.text, "html.parser")
                title_elem = soup.find("h1")
                if title_elem:
                    result["title"] = title_elem.get_text(strip=True)
                tags = [a.get_text(strip=True) for a in soup.find_all("a", {"href": re.compile(r"/shop/\?query=")})]
                result["keywords"] = list(dict.fromkeys(tags))[:20]

            elif "amazon.com" in url or re.match(r"^B0[A-Z0-9]{8}$", url):
                result["platform"] = "merch"
                asin = url if re.match(r"^B0[A-Z0-9]{8}$", url) else re.search(r"/dp/([A-Z0-9]{10})", url)
                asin = asin if isinstance(asin, str) else (asin.group(1) if asin else "")
                if asin:
                    product_url = f"https://www.amazon.com/dp/{asin}"
                    self.log.emit(f"Fetching Amazon ASIN {asin}...")
                    resp = requests.get(product_url, headers=headers, timeout=12)
                    soup = BeautifulSoup(resp.text, "html.parser")
                    title_elem = soup.find(id="productTitle")
                    if title_elem:
                        result["title"] = title_elem.get_text(strip=True)
                    bullet_features = soup.find_all("span", {"class": "a-list-item"})
                    result["keywords"] = [b.get_text(strip=True)[:50] for b in bullet_features[:10] if b.get_text(strip=True)]

            elif "spreadshirt" in url:
                result["platform"] = "spreadshirt"
                self.log.emit("Fetching Spreadshirt product...")
                resp = requests.get(url, headers=headers, timeout=12)
                soup = BeautifulSoup(resp.text, "html.parser")
                title_elem = soup.find("h1")
                if title_elem:
                    result["title"] = title_elem.get_text(strip=True)

            else:
                result["keywords"] = url.lower().split()

        except Exception as e:
            self.log.emit(f"Lookup error: {e}")

        self.progress.emit(100, 100)
        return result


class PodProductLookupAmazonWorker(BaseWorker):
    """Scrape an Amazon Merch product page by ASIN or amazon.com URL."""

    def __init__(self, url_or_asin, parent=None):
        super().__init__(parent)
        self.url_or_asin = url_or_asin

    def run_task(self):
        import re
        import requests
        from bs4 import BeautifulSoup

        raw = self.url_or_asin.strip()
        result = {"title": "", "asin": "", "keywords": [], "price": 0.0, "platform": "merch", "url": raw}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        # Resolve ASIN
        asin = ""
        if re.match(r"^[Bb]0[A-Z0-9]{8}$", raw):
            asin = raw.upper()
        else:
            m = re.search(r"/dp/([A-Z0-9]{10})", raw)
            if m:
                asin = m.group(1)

        if not asin:
            self.log.emit("Could not extract a valid ASIN from input.")
            self.progress.emit(100, 100)
            return result

        result["asin"] = asin
        product_url = f"https://www.amazon.com/dp/{asin}"
        self.status.emit(f"Fetching ASIN {asin}...")
        self.log.emit(f"URL: {product_url}")

        try:
            self.progress.emit(20, 100)
            resp = requests.get(product_url, headers=headers, timeout=15)
            self.progress.emit(60, 100)
            soup = BeautifulSoup(resp.text, "html.parser")

            # Title
            title_elem = soup.find(id="productTitle")
            if title_elem:
                result["title"] = title_elem.get_text(strip=True)
            self.log.emit(f"Title: {result['title'][:60] or 'not found'}")

            # Price
            price_elem = (
                soup.find("span", {"class": "a-price-whole"}) or
                soup.find("span", {"id": "priceblock_ourprice"}) or
                soup.find("span", {"class": re.compile(r"price")})
            )
            if price_elem:
                m = re.search(r"[\d.,]+", price_elem.get_text())
                if m:
                    try:
                        result["price"] = float(m.group().replace(",", ""))
                    except ValueError:
                        pass

            # Keywords from bullet points
            bullets = soup.find_all("span", {"class": "a-list-item"})
            result["keywords"] = [
                b.get_text(strip=True)[:80]
                for b in bullets
                if len(b.get_text(strip=True)) > 4
            ][:15]
            self.log.emit(f"Extracted {len(result['keywords'])} keyword hints")

        except Exception as e:
            self.log.emit(f"Fetch error: {e}")

        self.progress.emit(100, 100)
        return result


class PodPinterestWorker(BaseWorker):
    """Explore Pinterest suggestions, boards and trending for a seed."""

    def __init__(self, seed, mode="all", parent=None):
        super().__init__(parent)
        self.seed = seed
        self.mode = mode

    def run_task(self):
        self.status.emit(f"Exploring Pinterest: {self.seed}")
        result = {"suggestions": [], "boards": [], "trending": [], "pin_count_estimate": 0}

        try:
            self.log.emit("Fetching Pinterest data...")
            data = pod_pinterest_scraper.scrape_pinterest_search(
                self.seed, mode=self.mode
            )
            result["suggestions"] = data.get("suggestions", [])
            result["boards"] = data.get("top_boards", [])
            result["pin_count_estimate"] = data.get("pin_count_estimate", 0)
            result["trending"] = data.get("trending", [])
            self.progress.emit(100, 100)

            self.log.emit(
                f"Found {len(result['suggestions'])} suggestions, "
                f"{len(result['boards'])} boards, "
                f"{len(result['trending'])} trending"
            )
        except Exception as e:
            self.log.emit(f"Pinterest error: {e}")

        return result


class PodMarketOverviewWorker(BaseWorker):
    """Load real-time POD market overview from Reddit + Google Trends + Merch + Pinterest."""

    def run_task(self):
        self.status.emit("Loading POD market overview...")
        hot_niches = []
        rising_trends = []
        opportunities = []

        # Reddit hot niches
        self.log.emit("Mining Reddit POD trends...")
        try:
            reddit_data = pod_reddit_trends.mine_pod_reddit_trends()
            for item in reddit_data[:10]:
                hot_niches.append({
                    "niche": item.get("keyword", ""),
                    "score": round(item.get("score", 0) / 100, 2),
                    "platform": "Reddit",
                    "source": "reddit",
                })
            self.progress.emit(25, 100)
        except Exception as e:
            self.log.emit(f"Reddit error: {e}")

        # Google Trends rising
        self.log.emit("Getting Google Trends rising queries...")
        try:
            for seed in ["funny shirt", "custom gift", "cute sticker"]:
                try:
                    data = pod_google_trends.get_trends(seed, timeframe="today 3-m")
                    for q in data.get("related_queries_rising", [])[:4]:
                        rising_trends.append({
                            "niche": q.get("query", ""),
                            "score": round(min(1.0, q.get("value", 0) / 100), 2),
                            "platform": "Google",
                            "source": "google_trends",
                        })
                except Exception:
                    pass
            self.progress.emit(50, 100)
        except Exception as e:
            self.log.emit(f"Google Trends error: {e}")

        # Merch autocomplete on generic seeds
        self.log.emit("Mining Merch autocomplete seeds...")
        try:
            for seed in ["funny", "cute", "gift", "vintage"]:
                kws = pod_merch_autocomplete.mine_merch_autocomplete(seed, depth=1)
                for kw in kws[:3]:
                    rising_trends.append({
                        "niche": kw.get("keyword", ""),
                        "score": 0.65,
                        "platform": "Merch",
                        "source": "merch_ac",
                    })
            self.progress.emit(75, 100)
        except Exception as e:
            self.log.emit(f"Merch error: {e}")

        # Pinterest trending
        self.log.emit("Getting Pinterest trending categories...")
        try:
            p_data = pod_pinterest_scraper.scrape_pinterest_search("design trend")
            for item in p_data.get("trending", [])[:6]:
                opportunities.append({
                    "niche": item.get("trend", ""),
                    "score": 0.70,
                    "platform": "Pinterest",
                    "source": "pinterest",
                })
            self.progress.emit(100, 100)
        except Exception as e:
            self.log.emit(f"Pinterest error: {e}")

        self.log.emit(f"Overview: {len(hot_niches)} hot, {len(rising_trends)} rising, {len(opportunities)} opportunities")
        return {
            "hot_niches": hot_niches,
            "rising_trends": rising_trends,
            "opportunities": opportunities,
        }


class PodSeedsWorker(BaseWorker):
    """Generate seeds with heuristic trend scores (no API calls)."""

    TREND_WORDS = [
        "gift", "idea", "design", "decor", "wall art",
        "style", "love", "cute", "funny", "custom",
        "personalized", "room", "home", "aesthetic",
        "inspiration", "minimalist", "boho", "vintage",
        "retro", "modern", "unique", "cool", "best",
        "gift for", "perfect", "trendy", "chic", "rustic",
        "farmhouse", "coastal", "abstract", "geometric",
    ]

    PRODUCT_PREFIXES = [
        "t-shirt", "mug", "sticker", "poster", "hoodie",
        "gift for", "design", "funny",
    ]

    def __init__(self, category="all", limit_per_category=10, parent=None):
        super().__init__(parent)
        self.category = category
        self.limit_per_category = limit_per_category

    def _score_trend(self, keyword):
        kw = keyword.lower()
        words = kw.split()
        score = 0.0

        # 1. Specificity (0-30 points): more words = more specific
        wc = len(words)
        if wc >= 5:
            score += 30
        elif wc == 4:
            score += 25
        elif wc == 3:
            score += 20
        elif wc == 2:
            score += 10
        else:
            score += 5

        # 2. Trend words (0-50 points)
        trend_hits = sum(1 for w in self.TREND_WORDS if w in kw)
        score += min(50, trend_hits * 10)

        # 3. Product prefix bonus (0-20 points)
        has_prefix = any(kw.startswith(p) or kw.endswith(p) for p in self.PRODUCT_PREFIXES)
        if has_prefix:
            score += 20

        return round(min(100, score), 1)

    def run_task(self):
        from scout.pod_seeds import get_all_seeds, expand_seed

        self.status.emit("Generating seeds...")
        seeds = get_all_seeds(category=self.category, limit_per_category=self.limit_per_category)

        if not seeds:
            self.log.emit("No seeds found for this category")
            return []

        self.log.emit(f"Got {len(seeds)} base seeds")

        # Expand seeds with product prefixes
        expanded = []
        for seed in seeds:
            for kw in expand_seed(seed, depth=2):
                expanded.append(kw)

        self.status.emit("Computing trend scores...")
        self.log.emit(f"Scoring {len(expanded)} expanded seeds")

        enriched = []
        for i, kw in enumerate(expanded):
            trend_score = self._score_trend(kw)
            enriched.append({
                "seed": kw,
                "category": self.category.capitalize() if self.category != "all" else "Mixed",
                "source": "generated",
                "pinterest_pins": 0,
                "trend_score": trend_score,
            })
            self.progress.emit(i + 1, len(expanded))

        enriched.sort(key=lambda x: x["trend_score"], reverse=True)

        self.log.emit(f"Done: {len(enriched)} seeds scored by trend potential")
        self.status.emit(f"Generated {len(enriched)} scored seeds")
        return enriched


class PodPinterestExplorerWorker(BaseWorker):
    """Unified Pinterest explorer: seed discovery + Pinterest data enrichment."""

    TREND_WORDS = [
        "gift", "idea", "design", "decor", "wall art",
        "style", "love", "cute", "funny", "custom",
        "personalized", "room", "home", "aesthetic",
        "inspiration", "minimalist", "boho", "vintage",
        "retro", "modern", "unique", "cool", "best",
        "gift for", "perfect", "trendy", "chic", "rustic",
        "farmhouse", "coastal", "abstract", "geometric",
    ]

    PRODUCT_PREFIXES = [
        "t-shirt", "mug", "sticker", "poster", "hoodie",
        "gift for", "design", "funny",
    ]

    def __init__(self, category="all", seed=None, limit_per_category=10,
                 mode="all", parent=None):
        super().__init__(parent)
        self.category = category
        self.seed = seed
        self.limit_per_category = limit_per_category
        self.mode = mode  # all, suggestions, boards, trending, seeds

    def _heuristic_trend_score(self, keyword):
        kw = keyword.lower()
        words = kw.split()
        score = 0.0

        wc = len(words)
        if wc >= 5:
            score += 30
        elif wc == 4:
            score += 25
        elif wc == 3:
            score += 20
        elif wc == 2:
            score += 10
        else:
            score += 5

        trend_hits = sum(1 for w in self.TREND_WORDS if w in kw)
        score += min(50, trend_hits * 10)

        has_prefix = any(kw.startswith(p) or kw.endswith(p) for p in self.PRODUCT_PREFIXES)
        if has_prefix:
            score += 20

        return round(min(100, score), 1)

    def run_task(self):
        from scout.pod_seeds import get_all_seeds, expand_seed

        self.status.emit("Building keyword list...")

        # ── Phase 1: Build base keywords ──────────────
        if self.seed:
            # Direct seed mode: use seed + product prefixes
            base_kws = expand_seed(self.seed, depth=2)
            self.log.emit(f"Direct seed '{self.seed}' expanded to {len(base_kws)} keywords")
            cat_label = self.seed.capitalize()
        else:
            # Category mode: get seeds from category
            seeds = get_all_seeds(category=self.category, limit_per_category=self.limit_per_category)
            if not seeds:
                self.log.emit("No seeds found for this category")
                return []
            base_kws = []
            for s in seeds:
                base_kws.extend(expand_seed(s, depth=2))
            cat_label = self.category.capitalize() if self.category != "all" else "Mixed"
            self.log.emit(f"Category '{self.category}': {len(seeds)} seeds → {len(base_kws)} keywords")

        self.status.emit("Computing trend scores...")

        # ── Phase 2: Heuristic scores ──
        enriched_rows = []
        for i, kw in enumerate(base_kws):
            enriched_rows.append({
                "keyword": kw,
                "type": "seed",
                "trend_score": self._heuristic_trend_score(kw),
                "pinterest_pins": 0,
                "followers": 0,
                "frequency": 0,
                "board_name": "",
                "category": cat_label,
                "source": "generated",
            })
            self.progress.emit(i + 1, len(base_kws))

        # ── Phase 3: Pinterest enrichment (only for seed mode) ──
        all_suggestions = []
        all_boards = []
        all_trending = []
        seen_keywords = set()

        if self.seed:
            self.status.emit("Fetching Pinterest data...")
            from scout.collectors.pod_pinterest_scraper import scrape_pinterest_search
            try:
                pdata = scrape_pinterest_search(self.seed, mode="all")
                pc = pdata.get("pin_count_estimate", 0)

                # Update seed rows with real Pinterest data
                if pc > 0:
                    for row in enriched_rows:
                        row["pinterest_pins"] = pc
                        pin_score = min(pc / 100000, 1.0) * 50
                        board_score = sum(
                            b.get("followers", 0) for b in pdata.get("top_boards", [])
                        )
                        row["followers"] = board_score
                        board_norm = min(board_score / 50000, 1.0) * 30
                        real_score = pin_score + board_norm
                        row["trend_score"] = round(
                            row["trend_score"] * 0.3 + real_score * 0.7, 1
                        )

                for sug in pdata.get("suggestions", []):
                    st = sug.get("suggestion", "")
                    if st and st not in seen_keywords:
                        seen_keywords.add(st)
                        all_suggestions.append({
                            "keyword": st,
                            "type": "suggest",
                            "trend_score": self._heuristic_trend_score(st),
                            "pinterest_pins": 0,
                            "followers": 0,
                            "frequency": sug.get("frequency", 0),
                            "board_name": "",
                            "category": cat_label,
                            "source": "pinterest_suggest",
                        })
                for board in pdata.get("top_boards", []):
                    bn = board.get("board_name", "")
                    if bn and bn not in seen_keywords:
                        seen_keywords.add(bn)
                        all_boards.append({
                            "keyword": bn,
                            "type": "board",
                            "trend_score": self._heuristic_trend_score(bn),
                            "pinterest_pins": board.get("pin_count", 0),
                            "followers": board.get("followers", 0),
                            "frequency": 0,
                            "board_name": bn,
                            "category": cat_label,
                            "source": "pinterest_board",
                        })
                for trend in pdata.get("trending", []):
                    tr = trend.get("trend", "")
                    if tr and tr not in seen_keywords:
                        seen_keywords.add(tr)
                        all_trending.append({
                            "keyword": tr,
                            "type": "trending",
                            "trend_score": self._heuristic_trend_score(tr),
                            "pinterest_pins": 0,
                            "followers": 0,
                            "frequency": 0,
                            "board_name": "",
                            "category": cat_label,
                            "source": "pinterest_trending",
                        })
                self.log.emit(
                    f"Pinterest: {len(all_suggestions)} suggests, "
                    f"{len(all_boards)} boards, {len(all_trending)} trending"
                )
            except Exception as e:
                self.log.emit(f"Pinterest enrichment skipped: {e}")

        # ── Phase 3: Combine & filter by mode ─────────
        self.status.emit("Combining results...")

        mode = self.mode.lower()
        combined = []
        if mode in ("all", "seeds"):
            combined.extend(enriched_rows)
        if mode in ("all", "suggest", "suggestions"):
            combined.extend(all_suggestions)
        if mode in ("all", "boards"):
            combined.extend(all_boards)
        if mode in ("all", "trending"):
            combined.extend(all_trending)

        combined.sort(key=lambda x: x.get("trend_score", 0), reverse=True)

        self.log.emit(
            f"Results: {len(enriched_rows)} seeds, "
            f"{len(all_suggestions)} suggestions, "
            f"{len(all_boards)} boards, "
            f"{len(all_trending)} trending"
        )
        self.status.emit(f"Found {len(combined)} results")
        return combined

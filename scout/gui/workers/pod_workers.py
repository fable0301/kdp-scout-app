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
                    "posts": item.get("posts", 0),
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
                            "posts": 0,
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
                    "posts": 0,
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

    Full rewrite with 3-phase parallel pipeline + velocity-based trend detection:
      Phase 1 (8 threads)   — Mine Merch AC + Google Suggest per seed (parallel)
      Phase 2 (12 threads)  — Enrich top 80 candidates with Etsy + Redbubble (parallel)
      Phase 3 (2 threads)   — Google Trends batch on top 30 with velocity scoring
    
    Key improvements:
      - Dynamic seed generation from TikTok + Reddit trending (24h)
      - Velocity scoring: 7d vs 30d growth rate from Google Trends
      - Breakout query detection (related_queries_rising with "Breakout" value)
      - Fixed competition filter (was inverted bug)
      - Rich output: keyword, merch_position, etsy/rb_competition, avg_prices,
        google_trends_avg, google_trends_trend (rising/stable/falling), 
        google_trends_velocity, google_suggest_count, global_score, opportunity_score
    """

    PHASE1_THREADS = 8
    PHASE2_THREADS = 12
    PHASE3_THREADS = 2

    def __init__(self, product_type="all", competition_level="medium", category="all", parent=None):
        super().__init__(parent)
        self.product_type = product_type
        self.competition_level = competition_level
        self.category = category

    def run_task(self):
        self.status.emit("Discovering profitable niches...")
        
        # ── Step 0: Enrich seeds with dynamic trends (TikTok + Reddit) ───────────
        from scout.pod_seeds import get_all_seeds
        from scout.collectors import tiktok_booktok, pod_reddit_trends
        
        base_seeds = get_all_seeds(category=self.category, limit_per_category=6)
        if not base_seeds:
            self.log.emit("No seed keywords found for this category!")
            return []
        
        self.log.emit("📈 Fetching dynamic trending seeds (TikTok + Reddit)...")
        dynamic_seeds = []
        
        # TikTok BookTok trends (top 15)
        try:
            tiktok_trends = tiktok_booktok.fetch_booktok_trends(
                cancel_check=lambda: self.is_cancelled,
                log_cb=lambda msg: self.log.emit(msg)
            )
            for t in tiktok_trends[:15]:
                kw = t.get('keyword', '').strip().lower()
                if kw and len(kw) >= 3:
                    dynamic_seeds.append(kw)
            self.log.emit(f"  ✓ TikTok: {len([s for s in dynamic_seeds])} trending seeds")
        except Exception as e:
            self.log.emit(f"  ⚠ TikTok error: {e}")
        
        # Reddit POD trends (top 10)
        try:
            reddit_trends = pod_reddit_trends.mine_pod_reddit_trends()
            for r in reddit_trends[:10]:
                kw = r.get('keyword', '').strip().lower()
                if kw and len(kw) >= 3:
                    dynamic_seeds.append(kw)
            self.log.emit(f"  ✓ Reddit: {len(reddit_trends)} trending seeds")
        except Exception as e:
            self.log.emit(f"  ⚠ Reddit error: {e}")
        
        # Combine base + dynamic, deduplicate
        all_seeds = list(base_seeds)
        for ds in dynamic_seeds:
            if ds not in all_seeds:
                all_seeds.append(ds)
        
        self.log.emit(f"Phase 1: Mining {len(all_seeds)} seeds (base + dynamic)...")

        # ── Phase 1: Mine seeds (Merch + Google Suggest) ───────────
        candidates = {}
        done = 0
        with ThreadPoolExecutor(max_workers=self.PHASE1_THREADS) as pool:
            fut_map = {pool.submit(self._mine_seed, s): s for s in all_seeds}
            for f in as_completed(fut_map):
                if self.is_cancelled:
                    break
                done += 1
                self.progress.emit(int(done / len(all_seeds) * 25), 100)
                try:
                    for kw in f.result():
                        text = kw.get("keyword", "").strip().lower()
                        if text and text not in candidates:
                            candidates[text] = kw
                except Exception as e:
                    self.log.emit(f"Mine error on '{fut_map[f]}': {e}")

        if self.is_cancelled:
            return []
        self.log.emit(f"Phase 1: {len(candidates)} unique keywords")

        # ── Phase 2: Enrich top candidates by heuristic ────────────
        kw_list = list(candidates.values())
        # Heuristic pre-score to rank candidates without network calls
        for c in kw_list:
            mp = c.get("merch_position")
            merch = max(0.0, 1.0 - (mp or 50) / 50) if mp else 0.3
            gs = min(1.0, c.get("google_suggest_count", 0) / 5.0)
            c["_heuristic"] = merch * 0.6 + gs * 0.4
        kw_list.sort(key=lambda x: x.get("_heuristic", 0), reverse=True)
        # Only enrich the top N candidates to keep total time reasonable
        top_kw = kw_list[:80]
        self.log.emit(f"Phase 2: Enriching top {len(top_kw)} keywords with Etsy + Redbubble...")

        enriched = []
        done = 0
        failed_enrich = 0
        with ThreadPoolExecutor(max_workers=self.PHASE2_THREADS) as pool:
            fut_map = {pool.submit(self._enrich, d): d.get("keyword", "") for d in top_kw}
            for f in as_completed(fut_map):
                if self.is_cancelled:
                    break
                done += 1
                pct = 25 + int(done / len(top_kw) * 40)
                self.progress.emit(min(pct, 64), 100)
                try:
                    r = f.result()
                    if r:
                        enriched.append(r)
                    else:
                        failed_enrich += 1
                except Exception as e:
                    failed_enrich += 1
                    self.log.emit(f"Enrich error on '{fut_map[f]}': {e}")

        if self.is_cancelled:
            return []
        self.log.emit(f"Phase 2: {len(enriched)} ok, {failed_enrich} failed")

        # Initial score and rank
        for r in enriched:
            r["global_score"] = self._compute_score(r)
        enriched.sort(key=lambda x: x.get("global_score", 0), reverse=True)
        top = enriched[:30]

        # ── Phase 3: Google Trends with velocity scoring (multi-thread) ───
        self.status.emit(f"Phase 3: Google Trends + velocity for top {len(top)}...")
        done = 0
        import time
        with ThreadPoolExecutor(max_workers=self.PHASE3_THREADS) as pool:
            fut_map = {pool.submit(self._add_trends_with_velocity, r): r.get("niche", "") for r in top}
            for f in as_completed(fut_map):
                if self.is_cancelled:
                    break
                done += 1
                pct = 65 + int(done / len(top) * 30)
                self.progress.emit(min(pct, 95), 100)
                f.result()

        if self.is_cancelled:
            return []

        # Re-score with trends data and filter by competition level
        for r in enriched:
            r["global_score"] = self._compute_score(r)
            r["opportunity_score"] = self._compute_opportunity_score(r)
        enriched.sort(key=lambda x: x.get("opportunity_score", 0), reverse=True)

        filtered = self._apply_competition_filter(enriched)

        self.progress.emit(100, 100)
        self.log.emit(f"Found {len(filtered)} niches — showing top 20")
        return filtered[:20]

    def _mine_seed(self, seed):
        """Mine one seed from Merch Autocomplete + Google Suggest."""
        kw_map = {}
        try:
            for i, m in enumerate(pod_merch_autocomplete.mine_merch_autocomplete(seed, depth=2)):
                text = (m.get("keyword") or "").strip().lower()
                if text:
                    kw_map[text] = {
                        "keyword": text,
                        "niche": text,
                        "merch_position": i + 1,
                        "google_suggest_count": 0,
                        "etsy_competition": 0,
                        "rb_competition": 0,
                        "etsy_avg_price": 0.0,
                        "rb_avg_price": 0.0,
                        "google_trends_avg": 0,
                        "google_trends_trend": "",
                    }
        except Exception:
            pass
        try:
            for g in pod_google_suggest.get_suggestions(seed):
                text = (g.get("suggestion") or "").strip().lower()
                if text:
                    if text in kw_map:
                        kw_map[text]["google_suggest_count"] += 1
                    else:
                        kw_map[text] = {
                            "keyword": text,
                            "niche": text,
                            "merch_position": None,
                            "google_suggest_count": 1,
                            "etsy_competition": 0,
                            "rb_competition": 0,
                            "etsy_avg_price": 0.0,
                            "rb_avg_price": 0.0,
                            "google_trends_avg": 0,
                            "google_trends_trend": "",
                        }
        except Exception:
            pass
        return list(kw_map.values())

    def _enrich(self, kw_dict):
        """Add Etsy + Redbubble competition data to a keyword dict."""
        kw = (kw_dict.get("keyword") or "").strip()
        if not kw:
            return None
        r = dict(kw_dict)
        try:
            ed = pod_etsy_scraper.scrape_etsy_search(kw)
            r["etsy_competition"] = ed.get("competition_count", 0)
            r["etsy_avg_price"] = ed.get("avg_price", 0.0)
        except Exception:
            pass
        try:
            rd = pod_redbubble_scraper.scrape_redbubble_search(kw)
            r["rb_competition"] = rd.get("competition_count", 0)
            r["rb_avg_price"] = rd.get("avg_price", 0.0)
        except Exception:
            pass
        return r

    def _add_trends_with_velocity(self, result):
        """Add Google Trends data with velocity scoring (7d vs 30d) and breakout detection."""
        kw = result.get("niche", "")
        if not kw:
            return
        import time
        
        # Fetch 30-day trends for baseline
        td_30d = pod_google_trends.get_trends(kw, timeframe="today 1-m")
        interest_30d = td_30d.get("interest_over_time", {})
        vals_30d = [v for v in interest_30d.values() if isinstance(v, (int, float))]
        
        # Fetch 7-day trends for velocity calculation
        td_7d = pod_google_trends.get_trends(kw, timeframe="today 7-d")
        interest_7d = td_7d.get("interest_over_time", {})
        vals_7d = [v for v in interest_7d.values() if isinstance(v, (int, float))]
        
        if vals_30d:
            result["google_trends_avg"] = int(sum(vals_30d) / len(vals_30d))
        
        # Calculate velocity: compare 7d avg vs 30d avg
        if vals_7d and vals_30d:
            avg_7d = sum(vals_7d) / len(vals_7d)
            avg_30d = sum(vals_30d) / len(vals_30d)
            if avg_30d > 0:
                velocity = (avg_7d - avg_30d) / avg_30d
                result["google_trends_velocity"] = round(velocity, 3)
                # Determine trend direction based on velocity
                if velocity > 0.3:
                    result["google_trends_trend"] = "rising"
                elif velocity < -0.2:
                    result["google_trends_trend"] = "falling"
                else:
                    result["google_trends_trend"] = "stable"
            else:
                result["google_trends_velocity"] = 0.0
                result["google_trends_trend"] = "stable"
        else:
            result["google_trends_velocity"] = 0.0
            rising = td_30d.get("related_queries_rising") or []
            result["google_trends_trend"] = "rising" if rising else "stable"
        
        # Detect breakout queries (related_queries_rising with "Breakout" value)
        rising_queries = td_30d.get("related_queries_rising") or []
        breakout_count = sum(1 for q in rising_queries if q.get("value") == "Breakout" or (isinstance(q.get("value"), (int, float)) and q.get("value") > 5000))
        result["google_trends_breakout"] = breakout_count
        
        # Small delay to respect rate limits (1.5s instead of 3s for faster execution)
        time.sleep(1.5)

    def _compute_score(self, r):
        """Compute global opportunity score (0-1)."""
        ec = min(1.0, r.get("etsy_competition", 0) / 50000)
        rc = min(1.0, r.get("rb_competition", 0) / 50000)
        comp = 1.0 - (ec * 0.5 + rc * 0.5)
        trend = min(1.0, r.get("google_trends_avg", 0) / 100.0)
        gs = min(1.0, r.get("google_suggest_count", 0) / 10.0)
        mp = r.get("merch_position")
        merch = max(0.0, 1.0 - (mp or 50) / 50) if mp else 0.3
        # Velocity bonus: reward rising trends
        velocity = r.get("google_trends_velocity", 0)
        velocity_bonus = max(0.0, min(0.15, velocity * 0.1)) if velocity > 0 else 0.0
        # Breakout bonus: reward keywords with breakout queries
        breakout_bonus = min(0.1, r.get("google_trends_breakout", 0) * 0.02)
        trend_direction_bonus = 0.05 if r.get("google_trends_trend") == "rising" else 0.0
        return round(min(1.0, comp * 0.30 + trend * 0.25 + gs * 0.15 + merch * 0.15 + velocity_bonus + breakout_bonus + trend_direction_bonus), 3)

    def _compute_opportunity_score(self, r):
        """Compute enhanced opportunity score with velocity and breakout detection."""
        base_score = self._compute_score(r)
        # Factor in competition inversely (lower competition = higher opportunity)
        ec = min(1.0, r.get("etsy_competition", 0) / 50000)
        rc = min(1.0, r.get("rb_competition", 0) / 50000)
        comp_factor = 1.0 - (ec * 0.5 + rc * 0.5)
        # Velocity multiplier: boost rising trends
        velocity = r.get("google_trends_velocity", 0)
        velocity_mult = 1.0 + max(0.0, min(0.5, velocity * 0.3))
        # Price factor: optimal range $20-35
        avg_price = (r.get("etsy_avg_price", 0) + r.get("rb_avg_price", 0)) / 2
        price_factor = 1.0 if 20 <= avg_price <= 35 else (0.8 if 15 <= avg_price < 20 or 35 < avg_price <= 45 else 0.6)
        
        opportunity = base_score * comp_factor * velocity_mult * price_factor
        return round(min(1.0, opportunity), 3)

    def _apply_competition_filter(self, results):
        """Filter by desired competition level (FIXED: was inverted bug)."""
        level = self.competition_level
        if level == "any":
            return results
        filtered = []
        for r in results:
            ec = min(1.0, r.get("etsy_competition", 0) / 50000)
            rc = min(1.0, r.get("rb_competition", 0) / 50000)
            comp_score = 1.0 - (ec * 0.5 + rc * 0.5)
            # FIXED: correct logic - low competition means HIGH comp_score (close to 1.0)
            if level == "low" and comp_score < 0.6:
                continue
            # FIXED: high competition means LOW comp_score (close to 0.0)
            if level == "high" and comp_score > 0.6:
                continue
            # Medium: between 0.3 and 0.7
            if level == "medium" and (comp_score < 0.3 or comp_score > 0.7):
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
            data = pod_pinterest_scraper.scrape_pinterest_search(self.seed)
            result["suggestions"] = data.get("suggestions", [])
            result["pin_count_estimate"] = data.get("pin_count_estimate", 0)
            result["trending"] = data.get("trending", [])
            self.progress.emit(50, 100)

            self.log.emit("Fetching boards...")
            boards = pod_pinterest_scraper.get_pinterest_boards(self.seed)
            result["boards"] = boards
            self.progress.emit(100, 100)

            self.log.emit(f"Found {len(result['suggestions'])} suggestions, {len(boards)} boards")
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

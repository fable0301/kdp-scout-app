from typing import Optional
from kdp_scout.gui.workers.base_worker import BaseWorker


class MineWorker(BaseWorker):
    """Worker thread for mining keywords from a seed (single marketplace)."""

    def __init__(self, seed: str, depth: int = 2, department: str = "digital-text",
                 marketplace: str = "us", parent=None):
        super().__init__(parent)
        self.seed = seed
        self.depth = depth
        self.department = department
        self.marketplace = marketplace

    def run_task(self):
        from kdp_scout.keyword_engine import mine_keywords_fast, mine_keywords

        self.status.emit(f"Mining keywords for '{self.seed}' [{self.marketplace.upper()}]...")
        self.log.emit(f"Seed: {self.seed}, Depth: {self.depth}, Dept: {self.department}, MP: {self.marketplace}")

        def on_progress(current, total, message=""):
            if self.is_cancelled:
                raise InterruptedError("Mining cancelled by user")
            self.progress.emit(current, total)
            if message:
                self.log.emit(message)
                self.status.emit(message)

        try:
            result = mine_keywords_fast(
                seed=self.seed,
                depth=self.depth,
                department=self.department,
                progress_callback=on_progress,
                marketplace=self.marketplace,
            )
        except Exception as e:
            self.log.emit(f"Fast mining failed ({e}), falling back to sync...")
            result = mine_keywords(
                seed=self.seed,
                depth=self.depth,
                department=self.department,
                progress_callback=on_progress,
                marketplace=self.marketplace,
            )

        count = result.get('total_mined', 0) if isinstance(result, dict) else len(result)
        self.log.emit(f"Mining complete: {count} keywords found")
        self.status.emit(f"Found {count} keywords")
        return result


class MultiMarketplaceMineWorker(BaseWorker):
    """Worker thread for mining keywords across multiple marketplaces."""

    def __init__(self, seed: str, depth: int = 1, department: str = "digital-text",
                 marketplaces: Optional[list] = None, parent=None):
        super().__init__(parent)
        self.seed = seed
        self.depth = depth
        self.department = department
        self.marketplaces = marketplaces or ["us", "uk", "de", "ca"]

    def run_task(self):
        from kdp_scout.keyword_engine import mine_keywords_multi_marketplace_fast, mine_keywords_multi_marketplace

        mps = ", ".join(mp.upper() for mp in self.marketplaces)
        self.status.emit(f"Mining '{self.seed}' across {mps}...")
        self.log.emit(f"Multi-marketplace mining: {mps}")

        self._last_mp = None

        def on_progress(completed, total, marketplace):
            if self.is_cancelled:
                raise InterruptedError("Mining cancelled by user")
            # completed can be a float (fractional progress within a marketplace)
            pct_int = int(completed * 100 / max(total, 1))
            self.progress.emit(pct_int, 100)
            if marketplace and marketplace != "done" and marketplace != self._last_mp:
                self._last_mp = marketplace
                self.status.emit(f"Mining {marketplace.upper()}...")
                self.log.emit(f"Mining {marketplace.upper()}...")

        try:
            result = mine_keywords_multi_marketplace_fast(
                seed=self.seed,
                depth=self.depth,
                department=self.department,
                marketplaces=self.marketplaces,
                progress_callback=on_progress,
            )
        except Exception as e:
            self.log.emit(f"Fast multi-marketplace mining failed ({e}), falling back to sync...")
            result = mine_keywords_multi_marketplace(
                seed=self.seed,
                depth=self.depth,
                department=self.department,
                marketplaces=self.marketplaces,
                progress_callback=on_progress,
            )

        total = result.get('total_unique', 0)
        self.log.emit(f"Multi-marketplace mining complete: {total} unique keywords")
        self.status.emit(f"Found {total} unique keywords across {len(self.marketplaces)} marketplaces")
        return result


class ScoreWorker(BaseWorker):
    """Worker thread for scoring keywords."""

    def __init__(self, keywords: Optional[list] = None, parent=None):
        super().__init__(parent)
        self.keywords = keywords

    def run_task(self):
        from kdp_scout.keyword_engine import KeywordScorer

        self.status.emit("Scoring all keywords...")
        self.log.emit("Using KeywordScorer.score_all_keywords(recalculate=True)...")

        scorer = KeywordScorer()
        try:
            count = scorer.score_all_keywords(recalculate=True)
        finally:
            scorer.close()

        self.log.emit(f"Scoring complete: {count} keywords scored")
        self.status.emit(f"Scored {count} keywords")
        return count


class AmazonKeywordTrendingWorker(BaseWorker):
    """Worker thread for searching Amazon Kindle trending results by keyword.

    Uses amazon_search.search_kindle() with a sort parameter to retrieve
    Bestsellers or New Releases for a given seed keyword.
    """

    SORT_LABELS = {
        'salesrank': 'Bestsellers',
        'date-rank': 'New Releases',
        'relevancerank': 'Relevance',
    }

    def __init__(self, seed: str, marketplace: str = 'us',
                 sort_by: str = 'salesrank', max_results: int = 50,
                 parent=None):
        super().__init__(parent)
        self.seed = seed
        self.marketplace = marketplace
        self.sort_by = sort_by
        self.max_results = max_results

    def run_task(self):
        from kdp_scout.collectors.amazon_search import search_kindle

        sort_label = self.SORT_LABELS.get(self.sort_by, self.sort_by)
        mp = self.marketplace.upper()
        self.status.emit(f"Searching Amazon [{mp}] — {sort_label} for '{self.seed}'...")
        self.log.emit(
            f"Keyword: '{self.seed}' | Sort: {sort_label} | "
            f"Marketplace: {mp} | Max results: {self.max_results}"
        )

        self.progress.emit(0, 100)
        result = search_kindle(
            keyword=self.seed,
            marketplace=self.marketplace,
            max_results=self.max_results,
            sort_by=self.sort_by,
        )
        self.progress.emit(100, 100)

        results = result.get('results', [])
        competition = result.get('competition_count', 'N/A')
        avg_bsr = result.get('avg_bsr_top10', 'N/A')
        self.log.emit(
            f"Found {len(results)} results | Competition: {competition} | Avg BSR top10: {avg_bsr}"
        )
        self.status.emit(f"Found {len(results)} results for '{self.seed}'")
        # Attach sort metadata for display
        result['_seed'] = self.seed
        result['_sort_label'] = sort_label
        result['_marketplace'] = mp
        return result


class CompetitionProbeWorker(BaseWorker):
    """Worker thread for probing Amazon search results for competition data.

    Fills ku_ratio, median_reviews, avg_bsr_top10, competition_count
    for each keyword by scraping live Amazon search pages.
    """

    def __init__(self, keyword_ids: Optional[list] = None, limit: int = 50,
                 marketplace: str = "us", parent=None):
        super().__init__(parent)
        self.keyword_ids = keyword_ids
        self.limit = limit
        self.marketplace = marketplace

    def run_task(self):
        from kdp_scout.keyword_engine import CompetitionProber

        mp_label = self.marketplace.upper()
        self.status.emit(f"Probing competition data [{mp_label}]...")
        self.log.emit(f"Competition probe: limit={self.limit}, marketplace={mp_label}")

        def on_progress(completed, total, keyword):
            if self.is_cancelled:
                raise InterruptedError("Probe cancelled by user")
            self.progress.emit(completed, total)
            self.status.emit(f"Probing: {keyword[:40]}...")

        prober = CompetitionProber()
        try:
            results = prober.probe_keywords(
                keyword_ids=self.keyword_ids,
                limit=self.limit,
                marketplace=self.marketplace,
                progress_callback=on_progress,
                cancel_check=lambda: self.is_cancelled,
            )
        finally:
            prober.close()

        ok = sum(1 for r in results if r.get('success'))
        self.log.emit(f"Competition probe complete: {ok}/{len(results)} keywords enriched")
        self.status.emit(f"Probed {ok} keywords")
        return results


class MergeEnrichWorker(BaseWorker):
    """Cross-source keyword fusion worker.

    Enriches mined keywords with:
      - Google Suggest cross-check  (present / absent)
      - Google Trends direction 12 months  (↗ / → / ↘)
      - Amazon BSR of #1 search result  (demand proxy)
      - Multi-source count  (how many sources confirmed this keyword)
    """

    def __init__(self, keywords, seed="", max_trends=20, max_bsr=30,
                 marketplace="us", parent=None):
        super().__init__(parent)
        self.keywords = keywords          # list of keyword strings
        self.seed = seed
        self.max_trends = min(max_trends, len(keywords))
        self.max_bsr = min(max_bsr, len(keywords))
        self.marketplace = marketplace

    # ── helpers ────────────────────────────────────────────────────────
    def _check_cancel(self):
        if self.is_cancelled:
            raise InterruptedError("Cancelled")

    # ── pipeline ──────────────────────────────────────────────────────
    def run_task(self):
        enrichment = {}
        for kw in self.keywords:
            enrichment[kw.lower().strip()] = {
                "google_suggest": False,
                "trend": "—",
                "bsr_top1": None,
                "multi_source": 1,   # 1 = Amazon autocomplete (source of these kws)
            }

        # ── Step 1: Google Suggest ────────────────────────────────────
        self.status.emit("Step 1/3 — Cross-checking Google Suggest…")
        google_set = set()

        if self.seed:
            try:
                from kdp_scout.collectors.google_suggest import mine_suggest_keywords_fast
                self.log.emit(f"Alphabet crawl on seed '{self.seed}'…")
                results = mine_suggest_keywords_fast(
                    self.seed,
                    cancel_check=lambda: self.is_cancelled,
                )
                for item in results:
                    kw = item["keyword"] if isinstance(item, dict) else item[0]
                    google_set.add(kw.lower().strip())
                self.log.emit(f"Google Suggest returned {len(google_set)} unique keywords")
            except InterruptedError:
                raise
            except Exception as e:
                self.log.emit(f"Alphabet crawl failed: {e}")

        if not google_set:
            # Fallback: query unique 2-word stems
            from kdp_scout.collectors.google_suggest import query_google_suggest
            stems = list({
                " ".join(kw.split()[:2]) if len(kw.split()) >= 2 else kw
                for kw in self.keywords
            })[:30]
            for i, stem in enumerate(stems):
                self._check_cancel()
                self.progress.emit(i, len(stems))
                self.log.emit(f"G.Suggest stem [{i+1}/{len(stems)}]: {stem}")
                try:
                    for kw, _pos in query_google_suggest(stem):
                        google_set.add(kw.lower().strip())
                except Exception:
                    pass
            self.log.emit(f"Google Suggest (stems): {len(google_set)} unique suggestions")

        gs_matches = 0
        for kw_key in enrichment:
            if kw_key in google_set:
                enrichment[kw_key]["google_suggest"] = True
                enrichment[kw_key]["multi_source"] += 1
                gs_matches += 1
        self.log.emit(f"✓ Google Suggest matches: {gs_matches}/{len(self.keywords)}")

        self._check_cancel()

        # ── Step 2: Google Trends ─────────────────────────────────────
        self.status.emit("Step 2/3 — Fetching Google Trends…")
        try:
            from kdp_scout.collectors.google_trends import get_interest_over_time, has_pytrends
            if has_pytrends() and self.max_trends > 0:
                trend_kws = self.keywords[:self.max_trends]
                batches = [trend_kws[i:i + 5] for i in range(0, len(trend_kws), 5)]
                for bi, batch in enumerate(batches):
                    self._check_cancel()
                    self.progress.emit(bi, len(batches))
                    self.log.emit(f"Trends batch [{bi+1}/{len(batches)}]: {', '.join(b[:30] for b in batch[:3])}…")
                    try:
                        batch_trends = get_interest_over_time(batch, timeframe="today 12-m")
                        for kw, series in batch_trends.items():
                            kw_key = kw.lower().strip()
                            if kw_key not in enrichment or len(series) < 6:
                                continue
                            first_q = sum(p["value"] for p in series[:13]) / 13
                            last_q = sum(p["value"] for p in series[-13:]) / 13
                            if first_q > 0:
                                ratio = last_q / first_q
                                if ratio > 1.10:
                                    enrichment[kw_key]["trend"] = "↗"
                                elif ratio < 0.90:
                                    enrichment[kw_key]["trend"] = "↘"
                                else:
                                    enrichment[kw_key]["trend"] = "→"
                                enrichment[kw_key]["multi_source"] += 1
                    except Exception as e:
                        self.log.emit(f"  Batch failed: {e}")

                trend_ct = sum(1 for e in enrichment.values() if e["trend"] != "—")
                self.log.emit(f"✓ Trends: {trend_ct} keywords with direction data")
            else:
                self.log.emit("pytrends not installed or max_trends=0 — skipping")
        except InterruptedError:
            raise
        except Exception as e:
            self.log.emit(f"Google Trends failed (non-fatal): {e}")

        self._check_cancel()

        # ── Step 3: Amazon BSR #1 ─────────────────────────────────────
        self.status.emit("Step 3/3 — Fetching Amazon BSR #1…")
        bsr_kws = self.keywords[:self.max_bsr]
        bsr_ok = 0
        for i, kw in enumerate(bsr_kws):
            self._check_cancel()
            self.progress.emit(i, len(bsr_kws))
            kw_key = kw.lower().strip()
            self.log.emit(f"BSR #1 [{i+1}/{len(bsr_kws)}]: {kw}")
            try:
                from kdp_scout.collectors.amazon_search import search_kindle
                result = search_kindle(
                    keyword=kw, marketplace=self.marketplace, max_results=3,
                )
                top = result.get("results", [])
                if top:
                    bsr = top[0].get("bsr")
                    if bsr:
                        enrichment[kw_key]["bsr_top1"] = bsr
                        enrichment[kw_key]["multi_source"] += 1
                        bsr_ok += 1
            except Exception as e:
                self.log.emit(f"  ⚠ {e}")

        self.log.emit(f"✓ Amazon BSR #1: {bsr_ok}/{len(bsr_kws)} keywords")

        # ── Summary ───────────────────────────────────────────────────
        multi_vals = [e["multi_source"] for e in enrichment.values()]
        avg_multi = sum(multi_vals) / max(len(multi_vals), 1)
        self.log.emit(f"═══ Merge & Enrich complete ═══")
        self.log.emit(f"  Keywords: {len(self.keywords)}  |  Avg sources: {avg_multi:.1f}")
        self.log.emit(f"  G.Suggest: {gs_matches}  |  BSR #1: {bsr_ok}")
        self.status.emit(f"Enrichment complete — avg {avg_multi:.1f} sources/keyword")
        return enrichment


class NicheAnalyzerWorker(BaseWorker):
    """Worker that runs the full niche analysis pipeline.

    Pipeline:
        1. Mine 50-100 keywords via autocomplete
        2. Probe competition on top 20 keywords
        3. Enrich top books with BSR from product pages
        4. Get Google Trends data for top 5 keywords
        5. Calculate aggregated Niche Score (Demand, Competition, Profitability, Trend)
    """

    def __init__(self, seed: str, marketplace: str = 'us', parent=None):
        super().__init__(parent)
        self.seed = seed
        self.marketplace = marketplace

    def run_task(self):
        import math
        import statistics
        from kdp_scout.collectors.autocomplete import mine_autocomplete
        from kdp_scout.collectors.amazon_search import probe_competition
        from kdp_scout.collectors.bsr_model import (
            estimate_daily_sales, estimate_monthly_revenue,
            estimate_total_monthly_revenue, sales_velocity_label,
        )

        results = {
            'seed': self.seed,
            'marketplace': self.marketplace,
            'keywords': [],
            'probed': [],
            'trends': {},
            'scores': {},
            'top10_books': [],
        }

        # ── Step 1: Mine keywords ─────────────────────────────────────
        self.status.emit(f"Step 1/5 — Mining keywords for '{self.seed}'...")
        self.log.emit(f"Mining autocomplete for '{self.seed}' on {self.marketplace.upper()}...")

        def mine_progress(current, total, message=""):
            if self.is_cancelled:
                raise InterruptedError("Cancelled")
            self.progress.emit(current, total)

        raw = mine_autocomplete(
            self.seed, department='digital-text', depth=1,
            marketplace=self.marketplace,
            progress_callback=mine_progress,
        )
        keywords = [(kw, pos) for kw, pos in raw]
        # Deduplicate and sort by position
        seen = set()
        unique = []
        for kw, pos in keywords:
            kl = kw.lower().strip()
            if kl not in seen:
                seen.add(kl)
                unique.append((kw, pos))
        keywords = unique[:100]
        results['keywords'] = keywords
        self.log.emit(f"Mined {len(keywords)} unique keywords")

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        # ── Step 2: Probe competition on top 20 ──────────────────────
        self.status.emit("Step 2/5 — Probing competition on top keywords...")
        probe_keywords = keywords[:20]
        probed = []
        total_probe = len(probe_keywords)

        for i, (kw, pos) in enumerate(probe_keywords):
            if self.is_cancelled:
                raise InterruptedError("Cancelled")
            self.progress.emit(i, total_probe)
            self.log.emit(f"Probing [{i+1}/{total_probe}]: {kw}")
            try:
                probe = probe_competition(kw, marketplace=self.marketplace, top_n=10)
                probe['keyword'] = kw
                probe['autocomplete_pos'] = pos
                probed.append(probe)
            except Exception as e:
                self.log.emit(f"  ⚠ Probe failed for '{kw}': {e}")

        results['probed'] = probed
        self.log.emit(f"Probed {len(probed)}/{total_probe} keywords successfully")

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        # ── Step 3: Enrich with BSR from product pages ───────────────
        self.status.emit("Step 3/5 — Fetching BSR from product pages...")
        self.log.emit("Enriching top books with BSR data from product pages...")

        # Collect unique ASINs from all probed results
        all_book_refs = {}
        for probe in probed:
            for book in probe.get('top10_results', []):
                asin = book.get('asin', '')
                if asin and asin not in all_book_refs:
                    all_book_refs[asin] = book

        # Scrape up to 20 unique product pages for BSR
        asins_to_scrape = list(all_book_refs.keys())[:20]
        bsr_map = {}  # asin -> bsr_overall

        if asins_to_scrape:
            from kdp_scout.collectors.product_scraper import ProductScraper, CaptchaDetected
            scraper = ProductScraper()
            total_scrape = len(asins_to_scrape)

            for i, asin in enumerate(asins_to_scrape):
                if self.is_cancelled:
                    raise InterruptedError("Cancelled")
                self.progress.emit(i, total_scrape)
                try:
                    product_data = scraper.scrape_product(asin)
                    if product_data and product_data.get('bsr_overall'):
                        bsr_map[asin] = product_data['bsr_overall']
                        self.log.emit(f"  BSR [{i+1}/{total_scrape}] {asin}: #{product_data['bsr_overall']:,}")
                    else:
                        self.log.emit(f"  BSR [{i+1}/{total_scrape}] {asin}: not found")
                except CaptchaDetected:
                    self.log.emit(f"  ⚠ CAPTCHA detected — stopping BSR enrichment")
                    break
                except Exception as e:
                    self.log.emit(f"  ⚠ BSR scrape failed for {asin}: {e}")

            self.progress.emit(total_scrape, total_scrape)

        # Backfill BSR into all book references
        for asin, bsr_val in bsr_map.items():
            if asin in all_book_refs:
                all_book_refs[asin]['bsr'] = bsr_val

        # Recompute avg_bsr_top10 and median_reviews for each probe
        for probe in probed:
            books = probe.get('top10_results', [])
            bsr_vals = [b.get('bsr') for b in books if b.get('bsr') and b['bsr'] > 0]
            if bsr_vals:
                probe['avg_bsr_top10'] = round(statistics.mean(bsr_vals))
            review_vals = sorted([b.get('reviews') or b.get('review_count') or 0
                                  for b in books if (b.get('reviews') or b.get('review_count') or 0) > 0])
            if review_vals:
                mid = len(review_vals) // 2
                probe['median_reviews'] = (
                    review_vals[mid] if len(review_vals) % 2 == 1
                    else (review_vals[mid - 1] + review_vals[mid]) // 2
                )

        self.log.emit(f"BSR enrichment: got BSR for {len(bsr_map)}/{len(asins_to_scrape)} books")

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        # ── Step 4: Google Trends ─────────────────────────────────────
        self.status.emit("Step 4/5 — Fetching Google Trends data...")
        self.progress.emit(0, 1)
        try:
            from kdp_scout.collectors.google_trends import get_interest_over_time, has_pytrends
            if has_pytrends():
                trend_keywords = [kw for kw, _ in keywords[:5]]
                trends = get_interest_over_time(trend_keywords, timeframe="today 12-m")
                results['trends'] = trends
                self.log.emit(f"Got trends for {len(trends)} keywords")
            else:
                self.log.emit("pytrends not installed — trend scoring will use neutral values")
        except Exception as e:
            self.log.emit(f"Google Trends failed (non-fatal): {e}")
        self.progress.emit(1, 1)

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        # ── Step 5: Calculate scores ──────────────────────────────────
        self.status.emit("Step 5/5 — Calculating niche scores...")

        # Collect all top-10 books from probes (deduplicate by ASIN)
        all_books = {}
        for probe in probed:
            for book in probe.get('top10_results', []):
                asin = book.get('asin', '')
                if asin and asin not in all_books:
                    all_books[asin] = book

        top10_books_list = sorted(
            all_books.values(),
            key=lambda b: b.get('bsr') or 999999999
        )[:10]
        results['top10_books'] = top10_books_list

        # --- Demand Score ---
        bsr_values = [b.get('bsr') for b in top10_books_list if b.get('bsr') and b['bsr'] > 0]
        if bsr_values:
            avg_bsr = statistics.mean(bsr_values)
            # Lower BSR = higher demand. BSR 1000 -> 90, BSR 10000 -> 65, BSR 100000 -> 40, BSR 500000 -> 20
            demand_raw = max(0, 100 - (math.log10(max(avg_bsr, 1)) - 2) * 25)
            demand_score = min(100, max(0, demand_raw))
            books_under_50k = sum(1 for b in bsr_values if b < 50000)
            # Bonus for many books selling well
            demand_bonus = min(15, books_under_50k * 3)
            demand_score = min(100, demand_score + demand_bonus)
        else:
            avg_bsr = None
            demand_score = 0

        # --- Competition Score (higher = LESS competition = better) ---
        comp_counts = [p.get('competition_count') for p in probed if p.get('competition_count')]
        median_reviews_list = [p.get('median_reviews') for p in probed if p.get('median_reviews') is not None]
        review_counts = [b.get('review_count') or b.get('reviews') for b in top10_books_list if (b.get('review_count') or b.get('reviews')) is not None]

        if comp_counts:
            avg_comp = statistics.mean(comp_counts)
            # Less competition = better. <1000 = 90, 10000 = 60, 100000 = 30
            comp_raw = max(0, 100 - math.log10(max(avg_comp, 1)) * 20)
            competition_score = min(100, max(0, comp_raw))
        else:
            avg_comp = None
            competition_score = 50

        if median_reviews_list:
            avg_median_reviews = statistics.mean(median_reviews_list)
            # Fewer reviews = easier entry. <50 = great, 50-200 = ok, >500 = hard
            review_barrier = max(0, 100 - avg_median_reviews * 0.15)
            competition_score = (competition_score * 0.6 + review_barrier * 0.4)
        else:
            avg_median_reviews = None

        competition_score = min(100, max(0, competition_score))

        # --- Profitability Score ---
        prices = [b.get('price_kindle') or b.get('price') for b in top10_books_list if (b.get('price_kindle') or b.get('price') or 0) > 0]
        ku_flags = [b.get('ku_eligible') if b.get('ku_eligible') is not None else b.get('ku') for b in top10_books_list if (b.get('ku_eligible') is not None or b.get('ku') is not None)]

        if prices:
            avg_price = statistics.mean(prices)
            # Sweet spot $2.99-$9.99 (70% royalty)
            if 2.99 <= avg_price <= 9.99:
                price_score = 80 + min(20, (avg_price - 2.99) * 3)
            elif avg_price > 9.99:
                price_score = 60
            else:
                price_score = 30
        else:
            avg_price = None
            price_score = 50

        ku_ratio = sum(1 for k in ku_flags if k) / max(len(ku_flags), 1) if ku_flags else None
        if ku_ratio is not None:
            # Moderate KU (0.3-0.6) = ideal
            ku_score = 100 - abs(ku_ratio - 0.45) * 150
            ku_score = max(0, min(100, ku_score))
            profitability_score = price_score * 0.6 + ku_score * 0.4
        else:
            profitability_score = price_score

        # Estimated revenue of top 10
        revenues = []
        for b in top10_books_list:
            bsr_val = b.get('bsr')
            price_val = b.get('price_kindle') or b.get('price')
            if bsr_val and price_val:
                rev = estimate_total_monthly_revenue(
                    bsr_val, price_val,
                    ku_eligible=bool(b.get('ku_eligible') or b.get('ku')),
                )
                revenues.append(rev['total'])
        avg_revenue = statistics.mean(revenues) if revenues else None
        if avg_revenue is not None and avg_revenue > 0:
            # Revenue bonus: >$500/mo avg = excellent
            rev_bonus = min(20, avg_revenue / 50)
            profitability_score = min(100, profitability_score + rev_bonus)

        profitability_score = min(100, max(0, profitability_score))

        # --- Trend Score ---
        trend_score = 50  # Neutral default
        trend_direction = "stable"
        if results['trends']:
            all_series = list(results['trends'].values())
            if all_series:
                # Average the last 3 months vs first 3 months
                combined_values = []
                for series in all_series:
                    if len(series) >= 6:
                        first_q = statistics.mean([p['value'] for p in series[:13]])
                        last_q = statistics.mean([p['value'] for p in series[-13:]])
                        if first_q > 0:
                            change_ratio = last_q / first_q
                            combined_values.append(change_ratio)

                if combined_values:
                    avg_change = statistics.mean(combined_values)
                    if avg_change > 1.2:
                        trend_direction = "rising"
                        trend_score = min(100, 60 + (avg_change - 1.0) * 100)
                    elif avg_change > 1.05:
                        trend_direction = "rising"
                        trend_score = 55 + (avg_change - 1.0) * 200
                    elif avg_change > 0.95:
                        trend_direction = "stable"
                        trend_score = 50
                    elif avg_change > 0.8:
                        trend_direction = "declining"
                        trend_score = 30 + (avg_change - 0.8) * 130
                    else:
                        trend_direction = "declining"
                        trend_score = max(0, 30 * avg_change)

        trend_score = min(100, max(0, trend_score))

        # ── Overall Niche Score ───────────────────────────────────────
        overall = (
            demand_score * 0.30 +
            competition_score * 0.30 +
            profitability_score * 0.20 +
            trend_score * 0.20
        )
        overall = min(100, max(0, overall))

        # Grade
        if overall >= 80:
            grade = "A"
        elif overall >= 65:
            grade = "B"
        elif overall >= 50:
            grade = "C"
        elif overall >= 35:
            grade = "D"
        else:
            grade = "F"

        results['scores'] = {
            'overall': round(overall, 1),
            'grade': grade,
            'demand': round(demand_score, 1),
            'competition': round(competition_score, 1),
            'profitability': round(profitability_score, 1),
            'trend': round(trend_score, 1),
            'trend_direction': trend_direction,
            'details': {
                'avg_bsr_top10': round(avg_bsr) if avg_bsr else None,
                'avg_competition_count': round(avg_comp) if avg_comp else None,
                'avg_median_reviews': round(avg_median_reviews, 1) if avg_median_reviews else None,
                'avg_price': round(avg_price, 2) if avg_price else None,
                'ku_ratio': round(ku_ratio, 2) if ku_ratio is not None else None,
                'avg_monthly_revenue': round(avg_revenue, 2) if avg_revenue else None,
                'total_keywords_mined': len(keywords),
                'keywords_probed': len(probed),
            }
        }

        self.log.emit(f"═══ Niche Score: {overall:.0f}/100 ({grade}) ═══")
        self.log.emit(f"  Demand:        {demand_score:.0f}/100")
        self.log.emit(f"  Competition:   {competition_score:.0f}/100")
        self.log.emit(f"  Profitability: {profitability_score:.0f}/100")
        self.log.emit(f"  Trend:         {trend_score:.0f}/100 ({trend_direction})")

        return results

"""Worker thread for the Find For Me v2 auto-discovery tool.

Supports three depth levels:
    ⚡ Quick  — 1 pass (fast, broad)
    🔍 Deep — 2 passes (deep, specific)
    🎯 Sniper  — 3 passes (ultra-specific, actionable)
"""

from kdp_scout.gui.workers.base_worker import BaseWorker


class DiscoveryWorker(BaseWorker):
    """Runs the full discovery pipeline in a background thread."""

    def __init__(self, marketplaces=None, max_probe=20,
                 custom_seeds=None, use_tiktok=True,
                 use_autocomplete=True, use_reddit=True,
                 depth="quick", market_type="all",
                 parent=None):
        super().__init__(parent)
        self.marketplaces = marketplaces or ['us']
        self.max_probe = max_probe
        self.custom_seeds = custom_seeds or []
        self.use_tiktok = use_tiktok
        self.use_autocomplete = use_autocomplete
        self.use_reddit = use_reddit
        self.depth = depth
        self.market_type = market_type

    def run_task(self):
        from kdp_scout.collectors.discovery import (
            harvest_all_sources, cluster_books, score_clusters,
            deep_dive_clusters, sniper_micro_expand,
            DEPTH_QUICK, DEPTH_DEEP, DEPTH_SNIPER,
        )

        mp_label = ', '.join(m.upper() for m in self.marketplaces)
        depth_icons = {DEPTH_QUICK: '⚡', DEPTH_DEEP: '🔍', DEPTH_SNIPER: '🎯'}
        depth_icon = depth_icons.get(self.depth, '⚡')

        # Phase 1: Harvest
        sources_active = []
        if self.use_autocomplete:
            sources_active.append("Autocomplete")
        if self.custom_seeds:
            sources_active.append(f"Custom Seeds ({len(self.custom_seeds)})")
        if self.use_tiktok:
            sources_active.append("TikTok/BookTok")
        if self.use_reddit:
            sources_active.append("Reddit")
        sources_active.append("Google Trends")

        total_phases = {DEPTH_QUICK: 3, DEPTH_DEEP: 5, DEPTH_SNIPER: 7}[self.depth]

        self.status.emit(f"Phase 1/{total_phases} — Harvesting [{mp_label}]...")
        self.log.emit(f"═══ {depth_icon} DEPTH: {self.depth.upper()} | MARKET: {self.market_type.upper()} ═══")
        self.log.emit(f"═══ PHASE 1: HARVEST ({' + '.join(sources_active)}) ═══")

        books = harvest_all_sources(
            marketplaces=self.marketplaces,
            progress_cb=lambda c, t: self.progress.emit(c, t),
            cancel_check=lambda: self.is_cancelled,
            log_cb=lambda msg: self.log.emit(msg),
            custom_seeds=self.custom_seeds,
            use_tiktok=self.use_tiktok,
            use_autocomplete=self.use_autocomplete,
            use_reddit=self.use_reddit,
            market_type=self.market_type,
        )

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        if not books:
            self.log.emit("⚠ No items harvested — check network / Amazon blocking")
            return {'clusters': [], 'total_harvested': 0}

        # Phase 2: Cluster (pass 1)
        self.status.emit(f"Phase 2/{total_phases} — Clustering into niches...")
        self.log.emit("═══ PHASE 2: CLUSTER (pass 1) ═══")

        max_clusters = {DEPTH_QUICK: 30, DEPTH_DEEP: 40, DEPTH_SNIPER: 50}[self.depth]
        clusters = cluster_books(
            books,
            min_cluster_size=2,
            max_clusters=max_clusters,
            log_cb=lambda msg: self.log.emit(msg),
        )

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        # ── PROFOND: Deep-dive pass ──────────────────────────────────
        if self.depth in (DEPTH_DEEP, DEPTH_SNIPER) and clusters:
            self.status.emit(f"Phase 3/{total_phases} — Deep-dive: expanding top niches...")
            self.log.emit("═══ PHASE 3: DEEP-DIVE (pass 2) ═══")

            primary_mp = self.marketplaces[0]
            deep_items = deep_dive_clusters(
                clusters,
                marketplace=primary_mp,
                top_n=15,
                harvester_depth=1,
                cancel_check=lambda: self.is_cancelled,
                log_cb=lambda msg: self.log.emit(msg),
            )

            if self.is_cancelled:
                raise InterruptedError("Cancelled")

            if deep_items:
                # Merge new items with existing and re-cluster
                all_books = books + deep_items
                self.status.emit(f"Phase 4/{total_phases} — Re-clustering with deep-dive data...")
                self.log.emit("═══ PHASE 4: RE-CLUSTER (pass 2) ═══")

                clusters = cluster_books(
                    all_books,
                    min_cluster_size=2,
                    max_clusters=max_clusters,
                    log_cb=lambda msg: self.log.emit(msg),
                )
                books = all_books

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        # ── SNIPER: Ultra-deep micro-niche expansion ─────────────────
        if self.depth == DEPTH_SNIPER and clusters:
            self.status.emit(f"Phase 5/{total_phases} — Sniper: ultra-deep micro-niche scan...")
            self.log.emit("═══ PHASE 5: SNIPER (pass 3) ═══")

            primary_mp = self.marketplaces[0]
            sniper_items = sniper_micro_expand(
                clusters,
                marketplace=primary_mp,
                top_n=10,
                cancel_check=lambda: self.is_cancelled,
                log_cb=lambda msg: self.log.emit(msg),
            )

            if self.is_cancelled:
                raise InterruptedError("Cancelled")

            if sniper_items:
                all_books = books + sniper_items
                self.status.emit(f"Phase 6/{total_phases} — Final re-clustering...")
                self.log.emit("═══ PHASE 6: FINAL CLUSTER (pass 3) ═══")

                clusters = cluster_books(
                    all_books,
                    min_cluster_size=2,
                    max_clusters=max_clusters,
                    log_cb=lambda msg: self.log.emit(msg),
                )
                books = all_books

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        # Final phase: Score & Classify
        score_phase = total_phases
        self.status.emit(f"Phase {score_phase}/{total_phases} — Probing competition [{mp_label}]...")
        self.log.emit(f"═══ PHASE {score_phase}: SCORE & CLASSIFY ═══")

        scored = score_clusters(
            clusters,
            marketplaces=self.marketplaces,
            max_probe=self.max_probe,
            progress_cb=lambda c, t: self.progress.emit(c, t),
            cancel_check=lambda: self.is_cancelled,
            log_cb=lambda msg: self.log.emit(msg),
        )

        if self.is_cancelled:
            raise InterruptedError("Cancelled")

        # Summary
        hot = sum(1 for c in scored if c.get('classification') == 'hot')
        gems = sum(1 for c in scored if c.get('classification') == 'gem')
        rising = sum(1 for c in scored if c.get('classification') == 'rising')
        go_count = sum(1 for c in scored if c.get('go_verdict') == 'GO')

        self.log.emit("═══ DISCOVERY COMPLETE ═══")
        self.log.emit(f"  Total harvested: {len(books)}")
        self.log.emit(f"  Niches found: {len(scored)}")
        self.log.emit(f"  🔥 Hot: {hot} | 💎 Gems: {gems} | 📈 Rising: {rising}")
        self.log.emit(f"  🟢 GO: {go_count} niches")
        self.log.emit(f"  Depth: {depth_icon} {self.depth.upper()}")
        self.status.emit(
            f"✅ Found {len(scored)} niches — {hot} hot, {gems} gems, {go_count} GO signals"
        )

        return {
            'clusters': scored,
            'total_harvested': len(books),
            'depth': self.depth,
            'market_type': self.market_type,
        }

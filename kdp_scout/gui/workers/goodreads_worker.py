"""Worker threads for Goodreads & Open Library operations."""

from kdp_scout.gui.workers.base_worker import BaseWorker


class GoodreadsWorker(BaseWorker):
    """Worker for Goodreads + Open Library queries.

    Modes:
        search       – Search Goodreads books
        niche        – Niche analysis with aggregated metrics
        open_library – Search Open Library
        subjects     – Open Library subject browser
        gap_analysis – Goodreads vs Amazon gap analysis
        shelves      – Goodreads list/shelf explorer
    """

    def __init__(self, mode="search", query="", max_books=10, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.query = query
        self.max_books = max_books

    def run_task(self):
        from kdp_scout.collectors.goodreads import (
            search_goodreads,
            analyze_niche_goodreads,
            search_open_library,
            get_open_library_subjects,
            gap_analysis,
            search_shelves,
        )

        results = []
        metrics = {}

        # -- Search Goodreads --------------------------------------------------
        if self.mode == "search":
            if not self.query:
                raise ValueError("Enter a search query")
            self.status.emit(f'Searching Goodreads for "{self.query}"...')
            self.log.emit(f"Query: {self.query} (up to 20 results)")
            results = search_goodreads(
                self.query,
                max_results=20,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )

        # -- Niche Analysis ----------------------------------------------------
        elif self.mode == "niche":
            if not self.query:
                raise ValueError("Enter a niche keyword to analyze")
            self.status.emit(f'Analyzing niche: "{self.query}"...')
            self.log.emit(f"Fetching top {self.max_books} books and details...")
            data = analyze_niche_goodreads(
                self.query,
                max_books=self.max_books,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )
            results = data.get("books", [])
            metrics = data.get("metrics", {})

            if metrics:
                self.log.emit("\n── Goodreads Niche Analysis ──")
                self.log.emit(f"  Books analyzed: {metrics.get('books_analyzed', 0)}")
                self.log.emit(f"  Avg rating: {metrics.get('avg_rating', '?')}")
                self.log.emit(f"  Total ratings: {metrics.get('total_ratings', '?'):,}")
                self.log.emit(f"  Avg want-to-read: {metrics.get('avg_want_to_read', '?')}")
                self.log.emit(f"  Reader demand score: {metrics.get('reader_demand_score', '?')}/100")
                cs = metrics.get("common_shelves", [])
                if cs:
                    self.log.emit(f"  Common shelves: {', '.join(cs[:8])}")
                pg = metrics.get("publication_gap_months", 0)
                if pg:
                    self.log.emit(f"  Avg publication gap: {pg} months")

        # -- Open Library Search -----------------------------------------------
        elif self.mode == "open_library":
            if not self.query:
                raise ValueError("Enter a search query")
            self.status.emit(f'Searching Open Library for "{self.query}"...')
            self.log.emit(f"Query: {self.query}")
            results = search_open_library(
                self.query,
                max_results=20,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )

        # -- Subjects ----------------------------------------------------------
        elif self.mode == "subjects":
            if not self.query:
                raise ValueError("Enter a subject name")
            self.status.emit(f'Browsing subject: "{self.query}"...')
            self.log.emit(f"Subject: {self.query}")
            data = get_open_library_subjects(self.query, limit=20)
            results = data.get("books", [])
            metrics = {"work_count": data.get("work_count", 0), "name": data.get("name", "")}
            self.log.emit(f"Total works in subject: {metrics.get('work_count', 0):,}")

        # -- Gap Analysis ------------------------------------------------------
        elif self.mode == "gap_analysis":
            if not self.query:
                raise ValueError("Enter a keyword for gap analysis")
            self.status.emit(f'Running gap analysis for "{self.query}"...')
            self.log.emit(f"Cross-referencing Goodreads data for: {self.query}")
            results = gap_analysis(
                self.query,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )

        # -- Shelves -----------------------------------------------------------
        elif self.mode == "shelves":
            if not self.query:
                raise ValueError("Enter a keyword to find shelves/lists")
            self.status.emit(f'Searching Goodreads lists for "{self.query}"...')
            self.log.emit(f"Query: {self.query}")
            results = search_shelves(
                self.query,
                progress_callback=lambda c, t: self.progress.emit(c, t),
                cancel_check=lambda: self.is_cancelled,
            )

        else:
            raise ValueError(f"Unknown mode: {self.mode}")

        self.log.emit(f"\nTotal results: {len(results)}")
        self.status.emit(f"Found {len(results)} results")
        return {"results": results, "mode": self.mode, "metrics": metrics}

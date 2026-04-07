from typing import Optional, List
from kdp_scout.gui.workers.base_worker import BaseWorker


class SnapshotWorker(BaseWorker):
    """Worker thread that takes competitor book snapshots."""

    def __init__(self, asins: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.asins = asins

    def run_task(self):
        from kdp_scout.competitor_engine import CompetitorEngine

        engine = CompetitorEngine()

        if self.asins:
            books = self.asins
        else:
            books = [b["asin"] for b in engine.list_books()]

        total = len(books)
        results = []

        for i, asin in enumerate(books):
            if self.is_cancelled:
                self.log.emit("Snapshot cancelled")
                return results

            self.progress.emit(i + 1, total)
            self.status.emit(f"Snapshotting {asin} ({i + 1}/{total})...")
            self.log.emit(f"Taking snapshot for {asin}...")

            try:
                result = engine.take_snapshot(asin)
                results.append(result)
                self.log.emit(f"  ✓ {asin}: BSR={result.get('bsr', 'N/A')}")
            except Exception as e:
                self.log.emit(f"  ✗ {asin}: {e}")

        self.status.emit(f"Snapshots complete: {len(results)}/{total}")
        self.log.emit(f"Snapshot complete: {len(results)} succeeded, {total - len(results)} failed")
        return results


class ReverseASINWorker(BaseWorker):
    """Worker thread for reverse ASIN keyword lookup."""

    def __init__(self, asin: str, method: str = "auto", parent=None):
        super().__init__(parent)
        self.asin = asin
        self.method = method

    def run_task(self):
        from kdp_scout.keyword_engine import ReverseASIN

        self.status.emit(f"Looking up keywords for {self.asin}...")
        self.log.emit(f"ASIN: {self.asin}, Method: {self.method}")

        reverse = ReverseASIN()

        def on_progress(current, total, message=""):
            if self.is_cancelled:
                raise InterruptedError("Lookup cancelled by user")
            self.progress.emit(current, total)
            if message:
                self.log.emit(message)

        if self.method == "probe":
            keywords = reverse.probe(self.asin, progress_callback=on_progress)
        elif self.method == "dataforseo":
            keywords = reverse.dataforseo(self.asin)
        else:
            keywords = reverse.lookup(self.asin, progress_callback=on_progress)

        self.log.emit(f"Found {len(keywords)} keywords for {self.asin}")
        self.status.emit(f"Found {len(keywords)} keywords")
        return keywords


class AddBookWorker(BaseWorker):
    """Worker thread for adding a competitor book."""

    def __init__(self, asin: str, parent=None):
        super().__init__(parent)
        self.asin = asin

    def run_task(self):
        from kdp_scout.competitor_engine import CompetitorEngine

        self.status.emit(f"Adding book {self.asin}...")
        self.log.emit(f"Fetching data for {self.asin}...")

        engine = CompetitorEngine()
        result = engine.add_book(self.asin)

        self.log.emit(f"Added: {result.get('title', self.asin)}")
        self.status.emit(f"Added {result.get('title', self.asin)}")
        return result


class SnapshotWorkerFast(SnapshotWorker):
    """Parallel snapshot using ThreadPoolExecutor."""

    def run_task(self):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        books = self.engine.list_books()
        total = len(books)
        if total == 0:
            return

        results = []
        done = 0

        def _fetch_one(book):
            asin = book.get("asin") or book.get("ASIN", "")
            if not asin:
                return None
            try:
                return self.engine.scraper.scrape_product(asin)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(_fetch_one, b): b for b in books}
            for fut in as_completed(futures):
                if self.is_cancelled():
                    pool.shutdown(wait=False, cancel_futures=True)
                    return
                done += 1
                self.progress.emit(int(done * 100 / total))
                res = fut.result()
                if res:
                    results.append((futures[fut], res))

        # DB writes sequentially (SQLite thread-safety)
        for book, data in results:
            if self.is_cancelled():
                return
            asin = book.get("asin") or book.get("ASIN", "")
            try:
                self.engine.update_book_data(asin, data)
            except Exception:
                pass

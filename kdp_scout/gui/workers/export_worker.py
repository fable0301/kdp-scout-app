import csv
from typing import List, Dict, Any, Optional
from kdp_scout.gui.workers.base_worker import BaseWorker


class ExportCSVWorker(BaseWorker):
    """Worker thread for exporting keywords to CSV."""

    def __init__(self, filepath: str, data: Optional[List[Dict[str, Any]]] = None,
                 parent=None):
        super().__init__(parent)
        self.filepath = filepath
        self.data = data

    def run_task(self):
        self.status.emit("Exporting keywords to CSV...")

        if self.data is None:
            from kdp_scout.db import KeywordRepository
            repo = KeywordRepository()
            self.data = repo.get_keywords_with_latest_metrics()
            repo.close()

        if not self.data:
            self.log.emit("No keywords to export")
            return self.filepath

        total = len(self.data)
        self.log.emit(f"Exporting {total} keywords to {self.filepath}")

        columns = list(self.data[0].keys())

        with open(self.filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

            for i, row in enumerate(self.data):
                if self.is_cancelled:
                    self.log.emit("Export cancelled")
                    return self.filepath

                writer.writerow(row)
                if (i + 1) % 500 == 0:
                    self.progress.emit(i + 1, total)

        self.progress.emit(total, total)
        self.log.emit(f"Export complete: {total} rows written to {self.filepath}")
        self.status.emit(f"Exported {total} keywords")
        return self.filepath


class KDPSlotsWorker(BaseWorker):
    """Worker thread for generating KDP backend keyword slots."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def run_task(self):
        from kdp_scout.reporting import ReportingEngine

        self.status.emit("Generating KDP backend keyword slots...")
        self.log.emit("Analyzing keywords for best backend slot allocation...")

        engine = ReportingEngine()
        slots = engine.export_backend_keywords()

        self.log.emit(f"Generated {len(slots)} keyword slots")
        self.status.emit("KDP slots ready")
        return slots


class ExportAdsWorker(BaseWorker):
    """Worker thread for exporting keywords for Amazon Ads campaigns."""

    def __init__(self, filepath: str, parent=None):
        super().__init__(parent)
        self.filepath = filepath

    def run_task(self):
        from kdp_scout.reporting import ReportingEngine

        self.status.emit("Generating ads export...")
        self.log.emit("Building keyword list for Amazon Ads...")

        engine = ReportingEngine()
        result = engine.export_for_ads()

        if isinstance(result, list) and result:
            columns = list(result[0].keys())
            with open(self.filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=columns)
                writer.writeheader()
                writer.writerows(result)

            self.log.emit(f"Exported {len(result)} keywords for ads to {self.filepath}")
        else:
            self.log.emit("No keywords to export for ads")

        self.status.emit("Ads export complete")
        return self.filepath

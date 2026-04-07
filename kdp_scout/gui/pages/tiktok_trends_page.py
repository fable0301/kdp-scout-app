"""TikTok BookTok Trends page — discover trending book genres and tropes on TikTok."""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QComboBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.workers.base_worker import BaseWorker
from kdp_scout.gui.search_history import SearchHistory
from kdp_scout.gui.anim import animated_toggle


COLUMNS = ["rank", "keyword", "views", "source", "category", "hashtag"]
DISPLAY = {
    "rank": "#",
    "keyword": "Keyword / Niche",
    "views": "Views",
    "source": "Source",
    "category": "Category",
    "hashtag": "Hashtag",
}


def _format_views(n):
    """Format a view count with K/M/B suffixes."""
    if not n or not isinstance(n, (int, float)):
        try:
            n = int(n)
        except (ValueError, TypeError):
            return "—"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


class TikTokTrendsWorker(BaseWorker):
    """Runs the full BookTok trends scan (all strategies)."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def run_task(self):
        self.status.emit("Scanning TikTok for BookTok trends...")
        self.log.emit("Running full TikTok BookTok scan (4 strategies)...")
        self.log.emit("This may take 1-2 minutes...\n")

        try:
            from kdp_scout.collectors.tiktok_booktok import fetch_booktok_trends
            items = fetch_booktok_trends(
                cancel_check=lambda: self.is_cancelled,
                log_cb=lambda msg: self.log.emit(msg),
            )
        except Exception as e:
            self.log.emit(f"❌ Error: {e}")
            items = []

        if self.is_cancelled:
            return {"results": [], "mode": "full"}

        items.sort(key=lambda x: x.get("views", 0), reverse=True)
        self.log.emit(f"\n✅ Found {len(items)} BookTok trends")
        return {"results": items, "mode": "full"}


class TikTokCreativeCenterWorker(BaseWorker):
    """Runs Creative Center trending hashtags scan."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def run_task(self):
        self.status.emit("Fetching TikTok Creative Center trends...")
        self.log.emit("Scraping TikTok Creative Center for trending hashtags...\n")

        try:
            from kdp_scout.collectors.tiktok_booktok import fetch_creative_center_trends
            items = fetch_creative_center_trends(
                cancel_check=lambda: self.is_cancelled,
                log_cb=lambda msg: self.log.emit(msg),
            )
        except Exception as e:
            self.log.emit(f"❌ Error: {e}")
            items = []

        if self.is_cancelled:
            return {"results": [], "mode": "creative_center"}

        items.sort(key=lambda x: x.get("views", 0), reverse=True)
        self.log.emit(f"\n✅ Found {len(items)} Creative Center trends")
        return {"results": items, "mode": "creative_center"}


class TikTokBaselineWorker(BaseWorker):
    """Returns the curated baseline for overview."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def run_task(self):
        self.status.emit("Loading curated BookTok baseline...")
        self.log.emit("Loading 120+ curated BookTok niches and tropes...\n")

        try:
            from kdp_scout.collectors.tiktok_booktok import get_baseline_trends
            items = get_baseline_trends()
        except Exception as e:
            self.log.emit(f"❌ Error: {e}")
            items = []

        items.sort(key=lambda x: x.get("views", 0), reverse=True)
        self.log.emit(f"✅ Loaded {len(items)} curated baseline trends")
        return {"results": items, "mode": "baseline"}


class TikTokTrendsPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(10)

        # Header
        header = QLabel("🎵 TikTok BookTok Trends")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(header)

        # Description
        desc = QLabel(
            "Discover trending book genres and tropes on TikTok BookTok — "
            "viral hashtags, view counts, emerging niches."
        )
        desc.setStyleSheet("color: #a6adc8; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("🔥 Trending Hashtags", "creative_center")
        self._mode_combo.addItem("📚 BookTok Genres", "full")
        self._mode_combo.addItem("📊 Baseline Overview", "baseline")
        self._mode_combo.setFixedHeight(40)
        self._mode_combo.setMinimumWidth(220)
        self._mode_combo.setStyleSheet("""
            QComboBox {
                background: #313244; color: #cdd6f4; border: 1px solid #45475a;
                border-radius: 8px; padding: 4px 12px; font-size: 14px;
            }
            QComboBox:hover { border-color: #585b70; }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: none; }
            QComboBox QAbstractItemView {
                background: #1e1e2e; color: #cdd6f4; border: 1px solid #45475a;
                selection-background-color: #313244;
            }
        """)
        ctrl.addWidget(self._mode_combo)

        self._scan_btn = QPushButton("🎵 Scan TikTok")
        self._scan_btn.setFixedHeight(44)
        self._scan_btn.setFixedWidth(180)
        self._scan_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #fe2c55, stop:1 #ff0050);
                color: white; font-weight: bold; font-size: 15px;
                border-radius: 10px; padding: 6px 20px;
            }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #ff4070, stop:1 #ff2060); }
            QPushButton:disabled { background: #45475a; color: #6c7086; }
        """)
        self._scan_btn.clicked.connect(self._on_scan)
        ctrl.addWidget(self._scan_btn)

        self._cancel_btn = QPushButton("⏹ Cancel")
        self._cancel_btn.setFixedHeight(44)
        self._cancel_btn.setFixedWidth(100)
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                background: #f38ba8; color: #1e1e2e; font-weight: bold;
                border-radius: 8px; font-size: 13px;
            }
            QPushButton:hover { background: #eba0ac; }
        """)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        ctrl.addWidget(self._cancel_btn)

        ctrl.addStretch()
        layout.addLayout(ctrl)

        # Status
        self._status = QLabel("")
        self._status.setStyleSheet("color: #a6adc8; font-size: 13px;")
        layout.addWidget(self._status)

        # Info bar
        info_bar = QFrame()
        info_bar.setStyleSheet("background: #181825; border-radius: 8px;")
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(14, 8, 14, 8)
        info_label = QLabel(
            "📡 Sources: TikTok Creative Center · BookTok Hashtags · "
            "Google Trends · Curated Baseline (120+ niches)"
        )
        info_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        info_label.setWordWrap(True)
        info_layout.addWidget(info_label)
        layout.addWidget(info_bar)

        # Table
        self._table = DataTable()
        layout.addWidget(self._table, 1)

        # Log console with toggle
        log_header = QHBoxLayout()
        log_header.setSpacing(4)
        self._toggle_log_btn = QPushButton("▼")
        self._toggle_log_btn.setFixedSize(34, 28)
        self._toggle_log_btn.setStyleSheet(
            "QPushButton { background: #313244; color: #cdd6f4; border: none; "
            "border-radius: 6px; font-size: 11px; }"
            "QPushButton:hover { background: #45475a; }"
        )
        self._toggle_log_btn.setVisible(False)
        self._toggle_log_btn.clicked.connect(self._toggle_log)
        log_header.addStretch()
        log_header.addWidget(self._toggle_log_btn)
        layout.addLayout(log_header)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setStyleSheet(
            "background: #11111b; color: #a6adc8; font-size: 11px; "
            "border: 1px solid #313244; border-radius: 4px;"
        )
        self._log.setVisible(False)
        self._log_visible = True
        layout.addWidget(self._log)

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        animated_toggle(self._log, self._log_visible)
        self._toggle_log_btn.setText("▼" if self._log_visible else "Console ▲")

    def _on_scan(self):
        mode = self._mode_combo.currentData()

        self._log.clear()
        self._log.setVisible(True)
        self._log_visible = True
        self._toggle_log_btn.setVisible(True)
        self._toggle_log_btn.setText("▼")
        self._scan_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)

        if mode == "creative_center":
            self._worker = TikTokCreativeCenterWorker()
        elif mode == "baseline":
            self._worker = TikTokBaselineWorker()
        else:
            self._worker = TikTokTrendsWorker()

        self._worker.status.connect(lambda t: self._status.setText(t))
        self._worker.log.connect(self._on_log)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def _on_log(self, text):
        self._log.append(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, payload):
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)

        if not payload:
            self._status.setText("Cancelled.")
            return

        results = payload.get("results", [])
        mode = payload.get("mode", "full")

        if not results:
            self._status.setText("⚠ No results found.")
            return

        rows = []
        for i, r in enumerate(results):
            rows.append({
                "rank": i + 1,
                "keyword": r.get("keyword", ""),
                "views": _format_views(r.get("views", 0)),
                "source": r.get("source", "—"),
                "category": r.get("category", "general"),
                "hashtag": r.get("hashtag", "—"),
            })

        self._table.load_data(rows, COLUMNS, DISPLAY)

        mode_labels = {
            "creative_center": "Creative Center",
            "full": "BookTok full scan",
            "baseline": "Curated baseline",
        }
        label = mode_labels.get(mode, mode)
        self._status.setText(f"✅ {len(rows)} trends from {label}")

        try:
            SearchHistory.instance().log(
                tool="TikTok Trends",
                action=mode,
                query=f"TikTok {label}",
                results=[{"keyword": r.get("keyword", "")} for r in results[:20]],
                result_count=len(results),
            )
        except Exception:
            pass

    def _on_error(self, msg):
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)
        self._status.setText(f"❌ {msg}")
        self._log.append(f"❌ ERROR: {msg}")

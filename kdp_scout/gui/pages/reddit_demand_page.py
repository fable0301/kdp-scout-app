"""Reddit Demand page — mine book subreddits for reader demand signals."""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QComboBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.base_worker import BaseWorker
from kdp_scout.gui.search_history import SearchHistory
from kdp_scout.gui.anim import animated_toggle


COLUMNS = ["rank", "keyword", "score", "genres", "subreddits", "demand", "posts"]
DISPLAY = {
    "rank": "#",
    "keyword": "Keyword / Niche",
    "score": "Score",
    "genres": "Genres",
    "subreddits": "Subreddits",
    "demand": "Demand Signal",
    "posts": "Posts",
}


class RedditDemandWorker(BaseWorker):
    """Runs the Reddit demand collector."""

    def __init__(self, mode="demand", parent=None):
        super().__init__(parent)
        self.mode = mode

    def run_task(self):
        self.status.emit("Mining Reddit for book demand signals...")
        self.log.emit("Scanning book subreddits (r/suggestmeabook, r/romancebooks, etc.)")
        self.log.emit("This may take 1-2 minutes...\n")

        try:
            from kdp_scout.collectors.reddit_demand import harvest_reddit_demand
            items = harvest_reddit_demand(
                progress_cb=lambda msg: self.log.emit(msg),
            )
        except Exception as e:
            self.log.emit(f"❌ Error: {e}")
            items = []

        if self.is_cancelled:
            return {"results": [], "mode": self.mode}

        items.sort(key=lambda x: x.get("engagement_score", 0), reverse=True)

        self.log.emit(f"\n✅ Found {len(items)} demand signals from Reddit")
        return {"results": items, "mode": self.mode}


class RedditTrendingWorker(BaseWorker):
    """Runs Reddit trending topics scan."""

    def __init__(self, parent=None):
        super().__init__(parent)

    def run_task(self):
        self.status.emit("Scanning Reddit for trending book topics...")
        self.log.emit("Fetching top/week from book subreddits...")

        try:
            from kdp_scout.collectors.reddit_demand import (
                SUBREDDITS, _fetch_subreddit_json,
            )
            import re

            results = []
            for sub_info in SUBREDDITS:
                if self.is_cancelled:
                    break
                name = sub_info["name"]
                self.log.emit(f"  📡 r/{name} top/week...")
                posts = _fetch_subreddit_json(name, sort="top", time_filter="week", limit=10)
                for p in posts:
                    title = p.get("data", {}).get("title", "")
                    ups = p.get("data", {}).get("ups", 0)
                    comments = p.get("data", {}).get("num_comments", 0)
                    permalink = p.get("data", {}).get("permalink", "")
                    results.append({
                        "subreddit": f"r/{name}",
                        "title": title[:100],
                        "upvotes": ups,
                        "comments": comments,
                        "engagement": ups + comments * 2,
                        "url": f"https://reddit.com{permalink}" if permalink else "",
                    })

            results.sort(key=lambda x: x["engagement"], reverse=True)
            self.log.emit(f"\n✅ Found {len(results)} trending posts")
            return {"results": results, "mode": "trending"}

        except Exception as e:
            self.log.emit(f"❌ Error: {e}")
            return {"results": [], "mode": "trending"}


TRENDING_COLUMNS = ["rank", "subreddit", "title", "upvotes", "comments", "engagement"]
TRENDING_DISPLAY = {
    "rank": "#",
    "subreddit": "Subreddit",
    "title": "Post Title",
    "upvotes": "⬆ Upvotes",
    "comments": "💬 Comments",
    "engagement": "📊 Engagement",
}


class RedditDemandPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(10)

        header = QLabel("🤖 Reddit Demand Mining")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(header)

        desc = QLabel(
            "Mine book subreddits for real reader demand — "
            "'looking for', 'suggest me', 'recommend me' posts. "
            "No API key needed."
        )
        desc.setStyleSheet("color: #a6adc8; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("📊 Demand Signals", "demand")
        self._mode_combo.addItem("🔥 Trending Posts", "trending")
        self._mode_combo.setFixedHeight(40)
        self._mode_combo.setMinimumWidth(200)
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

        self._scan_btn = QPushButton("🤖 Scan Reddit")
        self._scan_btn.setFixedHeight(44)
        self._scan_btn.setFixedWidth(180)
        self._scan_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #ff4500, stop:1 #ff8717);
                color: white; font-weight: bold; font-size: 15px;
                border-radius: 10px; padding: 6px 20px;
            }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #ff5722, stop:1 #ffa040); }
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

        # Subreddit info bar
        subs_bar = QFrame()
        subs_bar.setStyleSheet("background: #181825; border-radius: 8px;")
        subs_layout = QHBoxLayout(subs_bar)
        subs_layout.setContentsMargins(14, 8, 14, 8)
        subs_info = QLabel(
            "📡 Subreddits: r/suggestmeabook · r/romancebooks · r/Fantasy · "
            "r/horrorlit · r/cozymysteries · r/selfpublish · r/kdp · "
            "r/litrpg · r/eroticauthors · r/booktok · r/books · r/BookRecommendations"
        )
        subs_info.setStyleSheet("color: #6c7086; font-size: 11px;")
        subs_info.setWordWrap(True)
        subs_layout.addWidget(subs_info)
        layout.addWidget(subs_bar)

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

        if mode == "demand":
            self._worker = RedditDemandWorker(mode="demand")
        else:
            self._worker = RedditTrendingWorker()

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
        mode = payload.get("mode", "demand")

        if not results:
            self._status.setText("⚠ No results found.")
            return

        if mode == "trending":
            rows = []
            for i, r in enumerate(results):
                rows.append({
                    "rank": i + 1,
                    "subreddit": r.get("subreddit", ""),
                    "title": r.get("title", ""),
                    "upvotes": f"{r.get('upvotes', 0):,}",
                    "comments": f"{r.get('comments', 0):,}",
                    "engagement": f"{r.get('engagement', 0):,}",
                })
            self._table.load_data(rows, TRENDING_COLUMNS, TRENDING_DISPLAY)
            self._status.setText(f"✅ {len(rows)} trending posts from Reddit")
        else:
            rows = []
            for i, r in enumerate(results):
                genres = r.get("genres", [])
                subs = r.get("subreddits", [])
                rows.append({
                    "rank": i + 1,
                    "keyword": r.get("keyword", ""),
                    "score": f"{r.get('engagement_score', 0):.0f}",
                    "genres": ", ".join(genres[:3]) if genres else "—",
                    "subreddits": ", ".join(f"r/{s}" for s in subs[:3]) if subs else "—",
                    "demand": "✅" if r.get("is_demand_post") else "—",
                    "posts": str(r.get("post_count", 1)),
                })
            self._table.load_data(rows, COLUMNS, DISPLAY)
            self._status.setText(f"✅ {len(rows)} demand signals from Reddit")

        try:
            SearchHistory.instance().log(
                tool="Reddit Demand",
                action=mode,
                query=f"Reddit {mode} scan",
                results=[{"keyword": r.get("keyword", r.get("title", ""))} for r in results[:20]],
                result_count=len(results),
            )
        except Exception:
            pass

    def _on_error(self, msg):
        self._scan_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)
        self._status.setText(f"❌ {msg}")
        self._log.append(f"❌ ERROR: {msg}")

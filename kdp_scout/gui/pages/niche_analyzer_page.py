"""Niche Analyzer page — the 'Holy Grail' feature.

Given a seed keyword (e.g. "coloring book for adults"), runs a full
pipeline: mine keywords → probe competition → Google Trends → aggregate
into a Niche Score with demand/competition/profitability/trend sub-scores.

Displays a visual dashboard with gauge cards, trend chart, and keyword table.
"""

import logging
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QFrame, QSplitter, QTextEdit, QSizePolicy, QGridLayout,
    QProgressBar, QApplication,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QColor, QPainter, QPen, QBrush

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.workers.mine_worker import NicheAnalyzerWorker
from kdp_scout.gui.search_history import SearchHistory

logger = logging.getLogger(__name__)

# ── Marketplace options ───────────────────────────────────────────────────────
MARKETPLACES = [
    ("us", "🇺🇸 US"), ("uk", "🇬🇧 UK"), ("de", "🇩🇪 DE"),
    ("fr", "🇫🇷 FR"), ("ca", "🇨🇦 CA"), ("au", "🇦🇺 AU"),
]


# ── Score Gauge Widget ────────────────────────────────────────────────────────

class ScoreGauge(QFrame):
    """Circular gauge showing a score 0-100 with label and color."""

    def __init__(self, title="Score", parent=None):
        super().__init__(parent)
        self._title = title
        self._score = 0
        self._detail = ""
        self._grade = ""
        self.setMinimumSize(140, 170)
        self.setMaximumSize(180, 200)
        self.setStyleSheet("background: transparent; border: none;")

    def set_score(self, score, detail="", grade=""):
        self._score = max(0, min(100, score))
        self._detail = detail
        self._grade = grade
        self.update()

    def _score_color(self):
        s = self._score
        if s >= 75:
            return QColor("#a6e3a1")  # Green
        elif s >= 55:
            return QColor("#f9e2af")  # Yellow
        elif s >= 35:
            return QColor("#fab387")  # Orange
        else:
            return QColor("#f38ba8")  # Red

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()

        # ── Draw circular arc ─────────────────────────────────────────
        diameter = min(w - 20, h - 60)
        x = (w - diameter) // 2
        y = 10

        # Background arc
        pen = QPen(QColor("#45475a"), 8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(x, y, diameter, diameter, 225 * 16, -270 * 16)

        # Score arc
        color = self._score_color()
        pen = QPen(color, 8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        span = int(-270 * 16 * self._score / 100)
        painter.drawArc(x, y, diameter, diameter, 225 * 16, span)

        # Score text in center
        painter.setPen(QPen(QColor("#cdd6f4")))
        score_font = QFont()
        score_font.setPixelSize(diameter // 3)
        score_font.setBold(True)
        painter.setFont(score_font)
        center_y = y + diameter // 2
        painter.drawText(x, center_y - diameter // 6, diameter, diameter // 3,
                         Qt.AlignmentFlag.AlignCenter, f"{self._score:.0f}")

        # Grade below score number
        if self._grade:
            grade_font = QFont()
            grade_font.setPixelSize(diameter // 5)
            painter.setFont(grade_font)
            painter.setPen(QPen(color))
            painter.drawText(x, center_y + diameter // 6 + 4, diameter, diameter // 4,
                             Qt.AlignmentFlag.AlignCenter, self._grade)

        # Title below arc
        painter.setPen(QPen(QColor("#bac2de")))
        title_font = QFont()
        title_font.setPixelSize(13)
        title_font.setBold(True)
        painter.setFont(title_font)
        title_y = y + diameter + 6
        painter.drawText(0, title_y, w, 20, Qt.AlignmentFlag.AlignCenter, self._title)

        # Detail text
        if self._detail:
            painter.setPen(QPen(QColor("#6c7086")))
            detail_font = QFont()
            detail_font.setPixelSize(10)
            painter.setFont(detail_font)
            painter.drawText(0, title_y + 18, w, 16, Qt.AlignmentFlag.AlignCenter, self._detail)

        painter.end()


# ── Trend Mini Chart ──────────────────────────────────────────────────────────

class TrendMiniChart(QFrame):
    """Small inline trend chart using QPainter (no matplotlib dependency)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._series = {}  # keyword -> [(date, value), ...]
        self.setMinimumHeight(140)
        self.setStyleSheet("background: #1e1e2e; border: 1px solid #313244; border-radius: 8px;")

    def set_data(self, trends_dict):
        """trends_dict: {keyword: [{date, value}, ...]}"""
        self._series = {}
        for kw, points in trends_dict.items():
            if points:
                self._series[kw] = [(p['date'], p['value']) for p in points]
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._series:
            painter = QPainter(self)
            painter.setPen(QPen(QColor("#6c7086")))
            f = QFont()
            f.setPixelSize(12)
            painter.setFont(f)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "No trend data (pytrends required)")
            painter.end()
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        margin_l, margin_r, margin_t, margin_b = 50, 20, 15, 30

        chart_w = w - margin_l - margin_r
        chart_h = h - margin_t - margin_b

        # Find global max
        all_vals = [v for pts in self._series.values() for _, v in pts]
        max_val = max(all_vals) if all_vals else 100
        if max_val == 0:
            max_val = 1

        colors = [
            QColor("#89b4fa"), QColor("#a6e3a1"), QColor("#f9e2af"),
            QColor("#f38ba8"), QColor("#cba6f7"),
        ]

        # Draw grid lines
        painter.setPen(QPen(QColor("#313244"), 1))
        for i in range(5):
            y = margin_t + int(chart_h * i / 4)
            painter.drawLine(margin_l, y, w - margin_r, y)
            # Y-axis labels
            painter.setPen(QPen(QColor("#6c7086")))
            f = QFont()
            f.setPixelSize(9)
            painter.setFont(f)
            val = max_val * (4 - i) / 4
            painter.drawText(0, y - 6, margin_l - 5, 12,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{val:.0f}")
            painter.setPen(QPen(QColor("#313244"), 1))

        # Draw each series
        for idx, (kw, points) in enumerate(self._series.items()):
            color = colors[idx % len(colors)]
            pen = QPen(color, 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)

            n = len(points)
            if n < 2:
                continue

            prev = None
            for i, (date, val) in enumerate(points):
                x = margin_l + int(chart_w * i / (n - 1))
                y = margin_t + int(chart_h * (1 - val / max_val))
                if prev:
                    painter.drawLine(prev[0], prev[1], x, y)
                prev = (x, y)

        # Legend
        painter.setPen(QPen(QColor("#6c7086")))
        f = QFont()
        f.setPixelSize(9)
        painter.setFont(f)
        legend_x = margin_l
        for idx, kw in enumerate(self._series.keys()):
            color = colors[idx % len(colors)]
            painter.setPen(QPen(color, 2))
            lx = legend_x + idx * (chart_w // min(len(self._series), 5))
            ly = h - 12
            painter.drawLine(lx, ly, lx + 15, ly)
            painter.setPen(QPen(QColor("#a6adc8")))
            painter.drawText(lx + 20, ly - 4, 120, 12,
                             Qt.AlignmentFlag.AlignLeft, kw[:20])

        painter.end()


# ── Main Page ─────────────────────────────────────────────────────────────────

# Columns for the keywords table
KW_COLUMNS = ['keyword', 'position', 'comp_count', 'avg_bsr', 'median_reviews',
              'ku_ratio', 'est_revenue']
KW_DISPLAY = {
    'keyword': 'Keyword', 'position': 'AC Pos', 'comp_count': 'Competition',
    'avg_bsr': 'Avg BSR Top10', 'median_reviews': 'Med. Reviews',
    'ku_ratio': 'KU %', 'est_revenue': 'Est. $/mo',
}

BOOK_COLUMNS = ['position', 'asin', 'title', 'author', 'bsr', 'reviews',
                'rating', 'price', 'ku']
BOOK_DISPLAY = {
    'position': '#', 'asin': 'ASIN', 'title': 'Title', 'author': 'Author',
    'bsr': 'BSR', 'reviews': 'Reviews', 'rating': 'Rating',
    'price': 'Price', 'ku': 'KU',
}


class NicheAnalyzerPage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._last_results = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(8)

        # ── Header ────────────────────────────────────────────────────
        header = QLabel("🔬 Niche Analyzer")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(header)

        desc = QLabel("Enter a niche keyword → full automated analysis: keyword mining, "
                       "competition probing, trend analysis, and aggregated scoring.")
        desc.setStyleSheet("color: #a6adc8; font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── Input bar ─────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        lbl = QLabel("Niche Keyword:")
        lbl.setStyleSheet("color: #bac2de; font-weight: bold;")
        input_row.addWidget(lbl)

        self._seed_input = QLineEdit()
        self._seed_input.setPlaceholderText("e.g. coloring book for adults, dark romance, self help...")
        self._seed_input.setMinimumWidth(350)
        self._seed_input.setFixedHeight(36)
        self._seed_input.returnPressed.connect(self._on_analyze)
        input_row.addWidget(self._seed_input, 1)

        lbl2 = QLabel("MP:")
        lbl2.setStyleSheet("color: #bac2de;")
        input_row.addWidget(lbl2)

        self._mp_combo = QComboBox()
        for code, display in MARKETPLACES:
            self._mp_combo.addItem(display, code)
        self._mp_combo.setFixedHeight(36)
        self._mp_combo.setFixedWidth(100)
        input_row.addWidget(self._mp_combo)

        self._analyze_btn = QPushButton("🔬 Analyze Niche")
        self._analyze_btn.setFixedHeight(40)
        self._analyze_btn.setFixedWidth(180)
        self._analyze_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #cba6f7, stop:1 #89b4fa);
                color: #1e1e2e; font-weight: bold; font-size: 14px;
                border-radius: 8px; padding: 6px 16px;
            }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #b4befe, stop:1 #74c7ec); }
            QPushButton:disabled { background: #45475a; color: #6c7086; }
        """)
        self._analyze_btn.clicked.connect(self._on_analyze)
        input_row.addWidget(self._analyze_btn)

        self._cancel_btn = QPushButton("⏹ Cancel")
        self._cancel_btn.setFixedHeight(40)
        self._cancel_btn.setFixedWidth(100)
        self._cancel_btn.setStyleSheet("""
            QPushButton {
                background: #f38ba8; color: #1e1e2e; font-weight: bold;
                border-radius: 8px; font-size: 12px;
            }
            QPushButton:hover { background: #eba0ac; }
        """)
        self._cancel_btn.setVisible(False)
        self._cancel_btn.clicked.connect(self._on_cancel)
        input_row.addWidget(self._cancel_btn)

        layout.addLayout(input_row)

        # ── Progress bar ──────────────────────────────────────────────
        self._progress_bar = QProgressBar()
        self._progress_bar.setProperty("class", "slim-progress")
        self._progress_bar.setFixedHeight(4)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(self._status_label)

        # ── Dashboard area (hidden until results) ─────────────────────
        self._dashboard = QWidget()
        dash_layout = QVBoxLayout(self._dashboard)
        dash_layout.setContentsMargins(0, 0, 0, 0)
        dash_layout.setSpacing(8)

        # Score gauges row
        gauges_frame = QFrame()
        gauges_frame.setStyleSheet("background: #181825; border-radius: 12px; padding: 8px;")
        gauges_layout = QHBoxLayout(gauges_frame)
        gauges_layout.setSpacing(4)

        self._overall_gauge = ScoreGauge("NICHE SCORE")
        self._demand_gauge = ScoreGauge("Demand")
        self._competition_gauge = ScoreGauge("Competition")
        self._profitability_gauge = ScoreGauge("Profitability")
        self._trend_gauge = ScoreGauge("Trend")

        gauges_layout.addStretch()
        gauges_layout.addWidget(self._overall_gauge)
        gauges_layout.addWidget(self._demand_gauge)
        gauges_layout.addWidget(self._competition_gauge)
        gauges_layout.addWidget(self._profitability_gauge)
        gauges_layout.addWidget(self._trend_gauge)
        gauges_layout.addStretch()

        dash_layout.addWidget(gauges_frame)

        # Details + Trend chart row
        mid_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Details card
        self._details_card = QFrame()
        self._details_card.setStyleSheet("background: #181825; border-radius: 8px; padding: 12px;")
        details_layout = QVBoxLayout(self._details_card)
        details_layout.setContentsMargins(12, 8, 12, 8)
        self._details_label = QLabel("")
        self._details_label.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        self._details_label.setWordWrap(True)
        details_layout.addWidget(self._details_label)

        # Trend chart
        self._trend_chart = TrendMiniChart()
        self._trend_chart.setMinimumWidth(300)

        mid_splitter.addWidget(self._details_card)
        mid_splitter.addWidget(self._trend_chart)
        mid_splitter.setSizes([300, 500])

        dash_layout.addWidget(mid_splitter)

        self._dashboard.setVisible(False)
        layout.addWidget(self._dashboard)

        # ── Tabs for keywords table vs books table ────────────────────
        self._tables_widget = QWidget()
        tables_layout = QVBoxLayout(self._tables_widget)
        tables_layout.setContentsMargins(0, 0, 0, 0)

        tab_row = QHBoxLayout()
        self._tab_kw_btn = QPushButton(f"📊 Keywords (0)")
        self._tab_kw_btn.setCheckable(True)
        self._tab_kw_btn.setChecked(True)
        self._tab_kw_btn.clicked.connect(lambda: self._switch_table('keywords'))
        tab_row.addWidget(self._tab_kw_btn)

        self._tab_books_btn = QPushButton(f"📚 Top Books (0)")
        self._tab_books_btn.setCheckable(True)
        self._tab_books_btn.clicked.connect(lambda: self._switch_table('books'))
        tab_row.addWidget(self._tab_books_btn)

        tab_row.addStretch()
        tables_layout.addLayout(tab_row)

        self._kw_table = DataTable()
        self._books_table = DataTable()
        self._books_table.setVisible(False)

        tables_layout.addWidget(self._kw_table, 1)
        tables_layout.addWidget(self._books_table, 1)

        self._tables_widget.setVisible(False)
        layout.addWidget(self._tables_widget, 1)

        # ── Log panel with toggle ────────────────────────────────────
        log_header = QHBoxLayout()
        log_header.setSpacing(4)

        self._toggle_log_btn = QPushButton("▲")
        self._toggle_log_btn.setToolTip("Show / Hide console")
        self._toggle_log_btn.setFixedSize(28, 28)
        self._toggle_log_btn.setStyleSheet(
            "QPushButton { background: #313244; color: #cdd6f4; border: none; "
            "border-radius: 4px; font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background: #45475a; }"
        )
        self._toggle_log_btn.setVisible(False)
        self._toggle_log_btn.clicked.connect(self._toggle_log)
        log_header.addStretch()
        log_header.addWidget(self._toggle_log_btn)
        layout.addLayout(log_header)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(100)
        self._log.setStyleSheet("background: #11111b; color: #a6adc8; font-size: 10px; "
                                "border: 1px solid #313244; border-radius: 4px;")
        self._log.setVisible(False)
        self._log_collapsed = False
        layout.addWidget(self._log)

        # Push everything to the top when dashboard/tables are hidden
        self._bottom_spacer = QWidget()
        self._bottom_spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._bottom_spacer)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_analyze(self):
        seed = self._seed_input.text().strip()
        if not seed:
            self._status_label.setText("⚠ Please enter a niche keyword.")
            return

        mp = self._mp_combo.currentData() or 'us'

        self._log.clear()
        self._log.setVisible(True)
        self._log_collapsed = False
        self._toggle_log_btn.setVisible(True)
        self._toggle_log_btn.setText("▲")
        self._log.append(f"Starting niche analysis for: '{seed}' [{mp.upper()}]")
        self._log.append(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        self._log.append("─" * 60)

        self._analyze_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(0)
        self._dashboard.setVisible(False)
        self._tables_widget.setVisible(False)
        self._bottom_spacer.setVisible(True)

        self._worker = NicheAnalyzerWorker(seed=seed, marketplace=mp)
        self._worker.progress.connect(self._on_progress)
        self._worker.status.connect(self._on_status)
        self._worker.log.connect(self._on_log)
        self._worker.finished_with_result.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()
            self._log.append("⏹ Cancelling...")

    def _on_progress(self, current, total):
        if total > 0:
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(current)

    def _on_status(self, text):
        self._status_label.setText(text)

    def _on_log(self, text):
        self._log.append(text)
        # Auto-scroll
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, payload):
        self._analyze_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)
        self._progress_bar.setVisible(False)

        if payload is None:
            self._status_label.setText("Cancelled.")
            self._log.append("Analysis cancelled by user.")
            return

        self._last_results = payload
        scores = payload.get('scores', {})
        details = scores.get('details', {})

        # ── Update gauges ─────────────────────────────────────────────
        self._overall_gauge.set_score(
            scores.get('overall', 0),
            grade=scores.get('grade', '')
        )
        self._demand_gauge.set_score(
            scores.get('demand', 0),
            detail=f"Avg BSR: {details.get('avg_bsr_top10', 'N/A'):,}" if details.get('avg_bsr_top10') else ""
        )
        self._competition_gauge.set_score(
            scores.get('competition', 0),
            detail=f"Med. Reviews: {details.get('avg_median_reviews', 'N/A')}" if details.get('avg_median_reviews') else ""
        )
        self._profitability_gauge.set_score(
            scores.get('profitability', 0),
            detail=f"Avg Price: ${details.get('avg_price', 0):.2f}" if details.get('avg_price') else ""
        )
        trend_dir = scores.get('trend_direction', 'stable')
        trend_icon = {"rising": "↗", "stable": "→", "declining": "↘"}.get(trend_dir, "→")
        self._trend_gauge.set_score(
            scores.get('trend', 0),
            detail=f"{trend_icon} {trend_dir.title()}"
        )

        # ── Details card ──────────────────────────────────────────────
        lines = [f"<b>Niche:</b> {payload.get('seed', '')}"]
        if details.get('total_keywords_mined'):
            lines.append(f"<b>Keywords mined:</b> {details['total_keywords_mined']}")
        if details.get('keywords_probed'):
            lines.append(f"<b>Keywords probed:</b> {details['keywords_probed']}")
        if details.get('avg_competition_count'):
            lines.append(f"<b>Avg competition:</b> {details['avg_competition_count']:,} results")
        if details.get('ku_ratio') is not None:
            lines.append(f"<b>KU ratio:</b> {details['ku_ratio']*100:.0f}%")
        if details.get('avg_monthly_revenue'):
            lines.append(f"<b>Avg top-10 revenue:</b> ${details['avg_monthly_revenue']:,.0f}/mo")

        grade = scores.get('grade', '?')
        overall = scores.get('overall', 0)
        if overall >= 65:
            verdict = "✅ <span style='color:#a6e3a1;'>Good opportunity — worth pursuing</span>"
        elif overall >= 45:
            verdict = "⚠️ <span style='color:#f9e2af;'>Moderate — needs niche-down or differentiation</span>"
        else:
            verdict = "❌ <span style='color:#f38ba8;'>Tough market — high competition or low demand</span>"
        lines.append(f"<br/><b>Verdict:</b> {verdict}")

        self._details_label.setText("<br/>".join(lines))

        # ── Trend chart ───────────────────────────────────────────────
        self._trend_chart.set_data(payload.get('trends', {}))

        # ── Keywords table ────────────────────────────────────────────
        probed = payload.get('probed', [])
        keywords = payload.get('keywords', [])

        # Build keyword rows — merge mined + probed
        probed_map = {}
        for p in probed:
            probed_map[p.get('keyword', '').lower()] = p

        kw_rows = []
        from kdp_scout.collectors.bsr_model import estimate_total_monthly_revenue
        for kw, pos in keywords:
            row = {
                'keyword': kw,
                'position': pos,
                'comp_count': '',
                'avg_bsr': '',
                'median_reviews': '',
                'ku_ratio': '',
                'est_revenue': '',
            }
            probe = probed_map.get(kw.lower())
            if probe:
                row['comp_count'] = f"{probe.get('competition_count', ''):,}" if probe.get('competition_count') else ''
                if probe.get('avg_bsr_top10'):
                    row['avg_bsr'] = f"{probe['avg_bsr_top10']:,.0f}"
                    # Estimate revenue for avg BSR at avg price
                    avg_p = details.get('avg_price') or 4.99
                    rev = estimate_total_monthly_revenue(probe['avg_bsr_top10'], avg_p)
                    row['est_revenue'] = f"${rev['total']:,.0f}"
                if probe.get('median_reviews') is not None:
                    row['median_reviews'] = str(int(probe['median_reviews']))
                if probe.get('ku_ratio') is not None:
                    row['ku_ratio'] = f"{probe['ku_ratio']*100:.0f}%"
            kw_rows.append(row)

        self._kw_table.load_data(kw_rows, KW_COLUMNS, KW_DISPLAY)
        self._tab_kw_btn.setText(f"📊 Keywords ({len(kw_rows)})")

        # ── Books table ───────────────────────────────────────────────
        top_books = payload.get('top10_books', [])
        book_rows = []
        for i, b in enumerate(top_books):
            book_rows.append({
                'position': i + 1,
                'asin': b.get('asin', ''),
                'title': (b.get('title') or '')[:60],
                'author': (b.get('author') or '')[:30],
                'bsr': f"{b['bsr']:,}" if b.get('bsr') else '',
                'reviews': b.get('review_count') or b.get('reviews', ''),
                'rating': f"{(b.get('avg_rating') or b.get('rating')):.1f}" if (b.get('avg_rating') or b.get('rating')) else '',
                'price': f"${(b.get('price_kindle') or b.get('price')):.2f}" if (b.get('price_kindle') or b.get('price')) else '',
                'ku': '✓' if (b.get('ku_eligible') or b.get('ku')) else '',
            })
        self._books_table.load_data(book_rows, BOOK_COLUMNS, BOOK_DISPLAY)
        self._tab_books_btn.setText(f"📚 Top Books ({len(book_rows)})")

        # ── Show dashboard ────────────────────────────────────────────
        self._dashboard.setVisible(True)
        self._tables_widget.setVisible(True)
        self._bottom_spacer.setVisible(False)
        self._switch_table('keywords')

        self._status_label.setText(
            f"✅ Analysis complete — Niche Score: {overall:.0f}/100 ({grade})"
        )

        # ── Save to history ───────────────────────────────────────────
        try:
            history = SearchHistory.instance()
            history.log(
                tool="Niche Analyzer",
                action="analyze",
                query=payload.get('seed', ''),
                results=kw_rows[:50],
                result_count=len(kw_rows),
                notes=f"Score: {overall:.0f}/100 ({grade}) | "
                      f"Demand: {scores.get('demand',0):.0f} | "
                      f"Competition: {scores.get('competition',0):.0f} | "
                      f"Profitability: {scores.get('profitability',0):.0f} | "
                      f"Trend: {scores.get('trend',0):.0f} ({trend_dir})",
            )
        except Exception as e:
            logger.error(f"Failed to log niche analysis to history: {e}")

    def _on_error(self, message):
        self._analyze_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)
        self._progress_bar.setVisible(False)
        self._status_label.setText(f"❌ Error: {message}")
        self._log.append(f"❌ ERROR: {message}")
        self._worker = None

    def _switch_table(self, which):
        is_kw = which == 'keywords'
        self._kw_table.setVisible(is_kw)
        self._books_table.setVisible(not is_kw)
        self._tab_kw_btn.setChecked(is_kw)
        self._tab_books_btn.setChecked(not is_kw)

    def _toggle_log(self):
        self._log_collapsed = not self._log_collapsed
        self._log.setVisible(not self._log_collapsed)
        self._toggle_log_btn.setText("▼" if self._log_collapsed else "▲")

    def focus_search(self):
        self._seed_input.setFocus()
        self._seed_input.selectAll()

"""Find For Me v2 — "Niche Sniper" auto-discovery tool.

Features:
    ⚡ Depth slider: Quick / Deep / Sniper
    📚 Market type filter: All / Low Content / Medium Content / High Content
    🎯 GO/NO-GO actionable niche cards with composite scoring
    📥 Export: JSON + CSV
    Multi-marketplace, parallel execution, full-width card view.
"""

import csv
import json
import logging
import webbrowser
import urllib.parse
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextEdit, QSizePolicy, QScrollArea, QMenu,
    QGridLayout, QWidgetAction, QApplication, QCheckBox,
    QLineEdit, QFileDialog, QComboBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.workers.discovery_worker import DiscoveryWorker
from kdp_scout.gui.search_history import SearchHistory
from kdp_scout.gui.anim import animated_toggle, fade_in

logger = logging.getLogger(__name__)

MARKETPLACES = [
    ("us", "🇺🇸 US"), ("uk", "🇬🇧 UK"), ("de", "🇩🇪 DE"),
    ("fr", "🇫🇷 FR"), ("ca", "🇨🇦 CA"), ("au", "🇦🇺 AU"),
]

BADGE_STYLES = {
    'hot':      ('🔥 Hot Niche',  '#a6e3a1', '#1e1e2e'),
    'gem':      ('💎 Hidden Gem', '#89b4fa', '#1e1e2e'),
    'rising':   ('📈 Rising',     '#f9e2af', '#1e1e2e'),
    'moderate': ('➡️ Moderate',    '#6c7086', '#cdd6f4'),
    'avoid':    ('⚠️ Saturated',   '#f38ba8', '#1e1e2e'),
}

GO_COLORS = {
    'GO':    '#a6e3a1',
    'MAYBE': '#f9e2af',
    'PASS':  '#f38ba8',
}

_MENU_STYLE = """
    QMenu {
        background: #1e1e2e; border: 1px solid #45475a;
        border-radius: 8px; padding: 4px;
    }
    QMenu::item { color: #cdd6f4; padding: 8px 18px; font-size: 13px; }
    QMenu::item:selected { background: #313244; border-radius: 4px; }
    QMenu::separator { height: 1px; background: #313244; margin: 4px 8px; }
"""

_COMBO_STYLE = """
    QComboBox {
        background: #313244; color: #cdd6f4; font-size: 13px;
        font-weight: bold; border-radius: 8px; padding: 6px 12px;
        border: 1px solid #45475a; min-width: 160px;
    }
    QComboBox:hover { background: #45475a; border-color: #585b70; }
    QComboBox::drop-down {
        border: none; padding-right: 8px;
    }
    QComboBox::down-arrow { image: none; }
    QComboBox QAbstractItemView {
        background: #1e1e2e; color: #cdd6f4; border: 1px solid #45475a;
        border-radius: 6px; selection-background-color: #313244;
        font-size: 13px; padding: 4px;
    }
"""


def _sel_label(text, style="", word_wrap=False):
    lbl = QLabel(text)
    if style:
        lbl.setStyleSheet(style)
    if word_wrap:
        lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse |
        Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    return lbl


class BookRow(QFrame):
    """Single competitor book row with right-click → Search Google / Amazon."""

    def __init__(self, book, index, parent=None):
        super().__init__(parent)
        self._book = book
        self._title = book.get('title', '?')[:60]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.setStyleSheet(
            "BookRow { background: transparent; border-radius: 4px; }"
            "BookRow:hover { background: #313244; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(2)

        title_lbl = QLabel(f"  {index}. {self._title}")
        title_lbl.setStyleSheet("color: #cdd6f4; font-size: 13px; font-weight: bold;")
        title_lbl.setWordWrap(True)
        title_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(title_lbl)

        price = book.get('price', 0)
        revs = book.get('reviews', 0)
        rating = book.get('rating', 0)
        bsr_b = book.get('bsr', 0)
        details = []
        if price > 0:
            details.append(f"${price:.2f}")
        if revs > 0:
            details.append(f"{revs} reviews")
        if rating > 0:
            details.append(f"{'★' * int(rating)}{'☆' * (5 - int(rating))}")
        if bsr_b > 0:
            details.append(f"BSR {bsr_b:,}")
        if details:
            det_lbl = QLabel(f"     {' · '.join(details)}")
            det_lbl.setStyleSheet("color: #a6adc8; font-size: 12px;")
            det_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            layout.addWidget(det_lbl)

    def _show_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)

        copy_act = menu.addAction("📋  Copy title")
        copy_act.triggered.connect(lambda: QApplication.clipboard().setText(self._title))

        menu.addSeparator()

        q_g = urllib.parse.quote(f"{self._title} KDP")
        google_act = menu.addAction("🔍  Search on Google")
        google_act.triggered.connect(
            lambda: webbrowser.open(f"https://www.google.com/search?q={q_g}")
        )

        q_a = urllib.parse.quote(self._title)
        amazon_act = menu.addAction("🛒  Search on Amazon")
        amazon_act.triggered.connect(
            lambda: webbrowser.open(f"https://www.amazon.com/s?k={q_a}")
        )

        asin = self._book.get('asin', '')
        if asin:
            menu.addSeparator()
            asin_act = menu.addAction(f"📦  Open ASIN ({asin})")
            asin_act.triggered.connect(
                lambda: webbrowser.open(f"https://www.amazon.com/dp/{asin}")
            )

        menu.exec(self.mapToGlobal(pos))


class CompetitorSlider(QFrame):
    """Paginated top-competitors widget — 3 books per page, right-click each."""

    PAGE_SIZE = 3

    def __init__(self, books, search_query="", parent=None):
        super().__init__(parent)
        self._books = books[:12]
        self._page = 0
        self._max_page = max(0, (len(self._books) - 1) // self.PAGE_SIZE)
        self._search_query = search_query
        self._setup_ui()
        self._render_page()

    def _setup_ui(self):
        self.setStyleSheet("background: #1e1e2e; border-radius: 8px; padding: 8px;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(6)

        hdr = QHBoxLayout()
        hdr.setSpacing(6)
        title = _sel_label("📚 Top Competitors", "color: #89b4fa; font-size: 14px; font-weight: bold;")
        hdr.addWidget(title)

        hdr.addStretch()

        self._page_lbl = QLabel()
        self._page_lbl.setStyleSheet("color: #6c7086; font-size: 12px;")
        hdr.addWidget(self._page_lbl)

        arrow_style = (
            "QPushButton { background: #313244; color: #cdd6f4; border: none; "
            "border-radius: 4px; padding: 2px 8px; font-size: 16px; font-weight: bold; }"
            "QPushButton:hover { background: #45475a; }"
            "QPushButton:disabled { color: #585b70; background: #1e1e2e; }"
        )
        self._left = QPushButton("‹")
        self._left.setFixedSize(28, 24)
        self._left.setStyleSheet(arrow_style)
        self._left.clicked.connect(self._prev)
        hdr.addWidget(self._left)

        self._right = QPushButton("›")
        self._right.setFixedSize(28, 24)
        self._right.setStyleSheet(arrow_style)
        self._right.clicked.connect(self._next)
        hdr.addWidget(self._right)

        outer.addLayout(hdr)

        self._container = QVBoxLayout()
        self._container.setSpacing(4)
        outer.addLayout(self._container)
        outer.addStretch()

    def _prev(self):
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def _next(self):
        if self._page < self._max_page:
            self._page += 1
            self._render_page()

    def _render_page(self):
        while self._container.count():
            item = self._container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        start = self._page * self.PAGE_SIZE
        end = start + self.PAGE_SIZE
        page_books = self._books[start:end]

        for i, book in enumerate(page_books):
            idx = start + i + 1
            row = BookRow(book, idx)
            self._container.addWidget(row)

        self._left.setEnabled(self._page > 0)
        self._right.setEnabled(self._page < self._max_page)
        self._page_lbl.setText(f"{self._page + 1}/{self._max_page + 1}")


class ContextFrame(QFrame):
    def __init__(self, search_query="", parent=None):
        super().__init__(parent)
        self._search_query = search_query

    def _collect_text(self):
        lines = []
        for child in self.findChildren(QLabel):
            t = child.text().strip()
            if t:
                lines.append(t)
        return "\n".join(lines)

    def contextMenuEvent(self, event):
        text = self._collect_text()
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE)
        copy_act = menu.addAction("📋  Copy all")
        copy_act.triggered.connect(lambda: QApplication.clipboard().setText(text))
        menu.addSeparator()
        q_g = urllib.parse.quote(f"{self._search_query} KDP books")
        search_google = menu.addAction("🔍  Search on Google")
        search_google.triggered.connect(
            lambda: webbrowser.open(f"https://www.google.com/search?q={q_g}")
        )
        q_a = urllib.parse.quote(self._search_query)
        search_amazon = menu.addAction("🛒  Search on Amazon")
        search_amazon.triggered.connect(
            lambda: webbrowser.open(f"https://www.amazon.com/s?k={q_a}")
        )
        menu.exec(event.globalPos())


class MarketplaceDropdown(QPushButton):
    def __init__(self, parent=None):
        super().__init__("🌍 Marketplaces ▾", parent)
        self._selected = {'us'}
        self._menu = QMenu(self)
        self._menu.setStyleSheet("""
            QMenu {
                background: #1e1e2e; border: 1px solid #45475a;
                border-radius: 6px; padding: 4px;
            }
            QMenu::item { color: #cdd6f4; padding: 8px 16px; font-size: 14px; }
            QMenu::item:selected { background: #313244; }
        """)
        self._actions = {}
        for code, display in MARKETPLACES:
            action = QAction(display, self._menu)
            action.setCheckable(True)
            action.setChecked(code == 'us')
            action.toggled.connect(lambda checked, c=code: self._on_toggle(c, checked))
            self._menu.addAction(action)
            self._actions[code] = action
        self.setMenu(self._menu)
        self.setFixedHeight(44)
        self.setMinimumWidth(180)
        self.setStyleSheet("""
            QPushButton {
                background: #313244; color: #cdd6f4; font-size: 14px;
                font-weight: bold; border-radius: 10px; padding: 6px 16px;
                border: 1px solid #45475a;
            }
            QPushButton:hover { background: #45475a; border-color: #585b70; }
            QPushButton::menu-indicator { width: 0; height: 0; }
        """)
        self._update_label()

    def _on_toggle(self, code, checked):
        if checked:
            self._selected.add(code)
        else:
            self._selected.discard(code)
            if not self._selected:
                self._selected.add('us')
                self._actions['us'].setChecked(True)
        self._update_label()

    def _update_label(self):
        mp_flags = {'us': '🇺🇸', 'uk': '🇬🇧', 'de': '🇩🇪', 'fr': '🇫🇷', 'ca': '🇨🇦', 'au': '🇦🇺'}
        flags = " ".join(mp_flags.get(c, c) for c in sorted(self._selected))
        self.setText(f"🌍 {flags} ▾")

    def get_selected(self):
        return list(self._selected) if self._selected else ['us']


class SeedChip(QFrame):
    """Clickable chip — click to remove."""

    def __init__(self, text, on_remove, parent=None):
        super().__init__(parent)
        self._text = text
        self._on_remove = on_remove
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Click to remove \"{text}\"")
        self.setStyleSheet("""
            SeedChip {
                background: #313244; border-radius: 5px;
                border: 1px solid #45475a;
            }
            SeedChip:hover {
                background: #45475a; border-color: #f38ba8;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(6)

        lbl = QLabel(text)
        lbl.setStyleSheet("color: #cdd6f4; font-size: 12px;")
        layout.addWidget(lbl)

        x_lbl = QLabel("✕")
        x_lbl.setStyleSheet("color: #f38ba8; font-size: 11px; font-weight: bold;")
        layout.addWidget(x_lbl)

    def mousePressEvent(self, event):
        self._on_remove(self._text, self)


class SourcesPanel(QFrame):
    """Collapsible panel: Sources + Custom Seed + Depth + Market Type."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            SourcesPanel {
                background: #181825;
                border: 1px solid #313244;
                border-radius: 10px;
            }
        """)
        self._expanded = True
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)

        # Header row
        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        title = QLabel("⚙️  Sources & Settings")
        title.setStyleSheet("color: #cdd6f4; font-size: 13px; font-weight: bold;")
        header_row.addWidget(title)
        header_row.addStretch()

        self._toggle_btn = QPushButton("▲")
        self._toggle_btn.setToolTip("Toggle panel")
        self._toggle_btn.setFixedSize(34, 28)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background: #313244; color: #cdd6f4; border: none;
                border-radius: 6px; font-size: 16px;
            }
            QPushButton:hover { background: #45475a; color: #cdd6f4; }
        """)
        self._toggle_btn.clicked.connect(self._toggle)
        header_row.addWidget(self._toggle_btn)
        outer.addLayout(header_row)

        # Body
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(10)

        # ── Row 1: Depth + Market Type dropdowns ─────────────────────
        settings_row = QHBoxLayout()
        settings_row.setSpacing(12)

        # Depth selector
        depth_label = QLabel("🎚 Depth:")
        depth_label.setStyleSheet("color: #a6adc8; font-size: 13px;")
        settings_row.addWidget(depth_label)

        self._depth_combo = QComboBox()
        self._depth_combo.addItem("⚡ Quick — broad scan, fast", "quick")
        self._depth_combo.addItem("🔍 Deep — deeper long-tails", "deep")
        self._depth_combo.addItem("🎯 Sniper — ultra-specific, GO/NO-GO", "sniper")
        self._depth_combo.setCurrentIndex(0)
        self._depth_combo.setFixedHeight(40)
        self._depth_combo.setStyleSheet(_COMBO_STYLE)
        self._depth_combo.setToolTip(
            "⚡ Quick: 1 pass — fast broad scan (~2 min)\n"
            "🔍 Deep: 2 passes — re-injects top niches as seeds for long-tail discovery (~5 min)\n"
            "🎯 Sniper: 3 passes — ultra-deep micro-niche expansion with GO/NO-GO cards (~10 min)"
        )
        settings_row.addWidget(self._depth_combo)

        settings_row.addSpacing(16)

        # Market type selector
        market_label = QLabel("📚 Market:")
        market_label.setStyleSheet("color: #a6adc8; font-size: 13px;")
        settings_row.addWidget(market_label)

        self._market_combo = QComboBox()
        self._market_combo.addItem("🌐 All Markets", "all")
        self._market_combo.addItem("🎨 Low Content (coloring, puzzles, journals)", "low_content")
        self._market_combo.addItem("📖 Medium Content (non-fiction, self-help)", "medium_content")
        self._market_combo.addItem("📕 High Content (fiction, romance, fantasy)", "high_content")
        self._market_combo.setCurrentIndex(0)
        self._market_combo.setFixedHeight(40)
        self._market_combo.setStyleSheet(_COMBO_STYLE)
        self._market_combo.setToolTip(
            "Filters the seed keywords used for autocomplete harvest.\n"
            "🌐 All: all seed categories (~80 seeds)\n"
            "🎨 Low Content: coloring books, puzzles, journals (~20 seeds)\n"
            "📖 Medium Content: non-fiction, self-help, business (~24 seeds)\n"
            "📕 High Content: fiction genres, romance, fantasy (~33 seeds)"
        )
        settings_row.addWidget(self._market_combo)

        settings_row.addStretch()
        body_layout.addLayout(settings_row)

        # ── Row 2: Source checkboxes ─────────────────────────────────
        cb_row = QHBoxLayout()
        cb_row.setSpacing(20)

        cb_style = """
            QCheckBox {
                color: #cdd6f4; font-size: 13px; spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px; height: 16px;
                border: 1px solid #585b70; border-radius: 3px;
                background: #1e1e2e;
            }
            QCheckBox::indicator:checked {
                background: #89b4fa; border-color: #89b4fa;
            }
        """

        self._cb_autocomplete = QCheckBox("🔤 Amazon Autocomplete")
        self._cb_autocomplete.setChecked(True)
        self._cb_autocomplete.setStyleSheet(cb_style)
        self._cb_autocomplete.setToolTip(
            "Queries Amazon's built-in autocomplete with genre/keyword seeds.\n"
            "Produces real search suggestions Amazon users type."
        )
        cb_row.addWidget(self._cb_autocomplete)

        self._cb_tiktok = QCheckBox("🎵 TikTok / BookTok")
        self._cb_tiktok.setChecked(True)
        self._cb_tiktok.setStyleSheet(cb_style)
        self._cb_tiktok.setToolTip(
            "Harvests trending genres from TikTok BookTok hashtags.\n"
            "Surfaces trends before they peak on Amazon."
        )
        cb_row.addWidget(self._cb_tiktok)

        self._cb_reddit = QCheckBox("🤖 Reddit Demand")
        self._cb_reddit.setChecked(True)
        self._cb_reddit.setStyleSheet(cb_style)
        self._cb_reddit.setToolTip(
            "Mines book subreddits for real reader demand signals.\n"
            "Extracts genres/tropes + engagement scoring."
        )
        cb_row.addWidget(self._cb_reddit)

        cb_row.addStretch()
        body_layout.addLayout(cb_row)

        # ── Row 3: Custom seed input ─────────────────────────────────
        seed_label = QLabel("🔎 Custom Autocomplete Seed:")
        seed_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        body_layout.addWidget(seed_label)

        seed_row = QHBoxLayout()
        seed_row.setSpacing(8)

        self._seed_input = QLineEdit()
        self._seed_input.setPlaceholderText(
            'e.g. "coloring book for"  or  "journal for"  (press Enter or + to add)'
        )
        self._seed_input.setFixedHeight(36)
        self._seed_input.setStyleSheet("""
            QLineEdit {
                background: #11111b; color: #cdd6f4;
                border: 1px solid #45475a; border-radius: 6px;
                padding: 4px 10px; font-size: 13px;
            }
            QLineEdit:focus { border-color: #89b4fa; }
        """)
        self._seed_input.returnPressed.connect(self._add_seed)
        seed_row.addWidget(self._seed_input, 1)

        add_btn = QPushButton("+")
        add_btn.setFixedSize(36, 36)
        add_btn.setStyleSheet("""
            QPushButton {
                background: #313244; color: #89b4fa; font-size: 18px;
                font-weight: bold; border-radius: 6px; border: 1px solid #45475a;
            }
            QPushButton:hover { background: #45475a; }
        """)
        add_btn.clicked.connect(self._add_seed)
        seed_row.addWidget(add_btn)
        body_layout.addLayout(seed_row)

        # Seed chips container
        self._chips_frame = QWidget()
        self._chips_layout = QHBoxLayout(self._chips_frame)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(6)
        self._chips_layout.addStretch()
        body_layout.addWidget(self._chips_frame)

        self._seeds = []

        outer.addWidget(self._body)

    def _add_seed(self):
        text = self._seed_input.text().strip()
        if not text or text in self._seeds:
            self._seed_input.clear()
            return
        self._seeds.append(text)
        self._seed_input.clear()

        chip = SeedChip(text, on_remove=self._remove_seed)
        idx = self._chips_layout.count() - 1
        self._chips_layout.insertWidget(idx, chip)

    def _remove_seed(self, text, chip_widget):
        if text in self._seeds:
            self._seeds.remove(text)
        chip_widget.deleteLater()

    def _toggle(self):
        self._expanded = not self._expanded
        self._toggle_btn.setText("▲" if self._expanded else "▼")
        animated_toggle(self._body, self._expanded)

    def get_settings(self):
        return {
            'use_autocomplete': self._cb_autocomplete.isChecked(),
            'use_tiktok': self._cb_tiktok.isChecked(),
            'use_reddit': self._cb_reddit.isChecked(),
            'custom_seeds': list(self._seeds),
            'depth': self._depth_combo.currentData(),
            'market_type': self._market_combo.currentData(),
        }


class NicheCard(QFrame):

    def __init__(self, cluster, rank, parent=None):
        super().__init__(parent)
        self._cluster = cluster
        self._rank = rank
        self._setup_ui()

    def _setup_ui(self):
        c = self._cluster
        cls = c.get('classification', 'moderate')
        badge_text, badge_bg, badge_fg = BADGE_STYLES.get(cls, BADGE_STYLES['moderate'])
        niche_name = c.get('name', '???').title()

        go_score = c.get('go_score', 0)
        go_verdict = c.get('go_verdict', '')
        go_emoji = c.get('go_emoji', '')
        go_color = GO_COLORS.get(go_verdict, '#6c7086')

        self.setStyleSheet(f"""
            NicheCard {{
                background: #181825;
                border: 1px solid #313244;
                border-radius: 12px;
            }}
            NicheCard:hover {{
                border-color: {badge_bg};
                border-width: 2px;
            }}
        """)

        main = QVBoxLayout(self)
        main.setContentsMargins(20, 16, 20, 16)
        main.setSpacing(12)

        # Row 1: Badge + GO Score + Rank + Name + Marketplaces
        top = QHBoxLayout()
        top.setSpacing(12)

        badge = QLabel(f" {badge_text} ")
        badge.setStyleSheet(
            f"background: {badge_bg}; color: {badge_fg}; "
            f"border-radius: 6px; padding: 5px 14px; font-size: 14px; font-weight: bold;"
        )
        badge.setFixedHeight(30)
        top.addWidget(badge)

        # GO score badge
        if go_verdict:
            go_badge = QLabel(f" {go_emoji} {go_score:.0f} ")
            go_badge.setStyleSheet(
                f"background: {go_color}; color: #1e1e2e; "
                f"border-radius: 6px; padding: 5px 12px; font-size: 14px; font-weight: bold;"
            )
            go_badge.setFixedHeight(30)
            go_badge.setToolTip(f"GO Score: {go_score:.0f}/100 — {go_verdict}")
            top.addWidget(go_badge)

        rank_lbl = QLabel(f"#{self._rank}")
        rank_lbl.setStyleSheet("color: #585b70; font-size: 24px; font-weight: bold;")
        rank_lbl.setFixedWidth(48)
        top.addWidget(rank_lbl)

        name = _sel_label(niche_name, "color: #cdd6f4; font-size: 20px; font-weight: bold;", word_wrap=True)
        top.addWidget(name, 1)

        # Pass level indicator
        pass_level = c.get('pass_level', 1)
        if pass_level >= 3:
            depth_lbl = QLabel("🎯")
            depth_lbl.setToolTip("Sniper pass — ultra-specific niche")
        elif pass_level >= 2:
            depth_lbl = QLabel("🔍")
            depth_lbl.setToolTip("Deep-dive pass — specific niche")
        else:
            depth_lbl = QLabel("⚡")
            depth_lbl.setToolTip("Standard pass")
        depth_lbl.setStyleSheet("font-size: 18px;")
        top.addWidget(depth_lbl)

        mps = c.get('marketplaces', [])
        if mps:
            mp_flags = {'us': '🇺🇸', 'uk': '🇬🇧', 'de': '🇩🇪', 'fr': '🇫🇷', 'ca': '🇨🇦', 'au': '🇦🇺'}
            for m in mps:
                flag = QLabel(mp_flags.get(m, m.upper()))
                flag.setStyleSheet("font-size: 20px; padding: 0 3px;")
                top.addWidget(flag)

        main.addLayout(top)

        # Row 2: Metrics grid
        metrics = QFrame()
        metrics.setStyleSheet("background: #11111b; border-radius: 8px; padding: 10px;")
        mg = QGridLayout(metrics)
        mg.setContentsMargins(14, 10, 14, 10)
        mg.setSpacing(0)
        mg.setHorizontalSpacing(24)
        mg.setVerticalSpacing(4)

        col = 0
        def _add_metric(label, value, color="#cdd6f4"):
            nonlocal col
            v = _sel_label(str(value), f"color: {color}; font-size: 18px; font-weight: bold;")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mg.addWidget(v, 0, col)
            l = QLabel(label)
            l.setStyleSheet("color: #6c7086; font-size: 12px;")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            mg.addWidget(l, 1, col)
            col += 1

        # GO Score metric (first)
        go_metric_color = go_color if go_verdict else "#6c7086"
        _add_metric("GO Score", f"{go_score:.0f}", go_metric_color)

        bsr = c.get('avg_bsr')
        bsr_str = f"{bsr:,.0f}" if bsr else "—"
        bsr_color = "#a6e3a1" if bsr and bsr < 50000 else "#f9e2af" if bsr and bsr < 200000 else "#cdd6f4"
        _add_metric("Avg BSR", bsr_str, bsr_color)

        comp = c.get('competition_count')
        comp_str = f"{comp:,}" if comp else "—"
        comp_color = "#a6e3a1" if comp and comp < 10000 else "#f9e2af" if comp and comp < 50000 else "#f38ba8" if comp else "#cdd6f4"
        _add_metric("Competition", comp_str, comp_color)

        reviews = c.get('median_reviews')
        rev_str = str(int(reviews)) if reviews is not None else "—"
        rev_color = "#a6e3a1" if reviews is not None and reviews < 50 else "#f9e2af" if reviews is not None and reviews < 200 else "#cdd6f4"
        _add_metric("Med. Reviews", rev_str, rev_color)

        revenue = c.get('est_revenue', 0)
        rev_money_color = "#a6e3a1" if revenue >= 300 else "#f9e2af" if revenue >= 50 else "#f38ba8" if revenue > 0 else "#6c7086"
        _add_metric("Est. $/mo", f"${revenue:,.0f}", rev_money_color)

        ku = c.get('ku_ratio', 0)
        _add_metric("KU %", f"{ku*100:.0f}%")

        opp = c.get('opportunity', 0)
        opp_color = "#a6e3a1" if opp >= 50 else "#f9e2af" if opp >= 25 else "#f38ba8" if opp > 0 else "#6c7086"
        _add_metric("Opportunity", f"{opp:.0f}", opp_color)

        pmin = c.get('price_min')
        pmax = c.get('price_max')
        if pmin is not None and pmax is not None:
            price_str = f"${pmin:.2f}–${pmax:.2f}"
        elif c.get('price_avg'):
            price_str = f"~${c['price_avg']:.2f}"
        else:
            price_str = "—"
        _add_metric("Price Range", price_str)

        ds = c.get('daily_sales', 0)
        ds_color = "#a6e3a1" if ds >= 5 else "#f9e2af" if ds >= 1 else "#6c7086"
        _add_metric("Daily Sales", f"{ds:.1f}" if ds > 0 else "—", ds_color)

        main.addWidget(metrics)

        # Row 3: Keywords
        kws = c.get('keywords', [])[:8]
        if kws:
            kw_frame = QFrame()
            kw_layout = QHBoxLayout(kw_frame)
            kw_layout.setContentsMargins(0, 0, 0, 0)
            kw_layout.setSpacing(8)
            kw_icon = QLabel("🏷")
            kw_icon.setStyleSheet("font-size: 14px;")
            kw_layout.addWidget(kw_icon)
            for kw in kws:
                chip = _sel_label(
                    kw,
                    "background: #313244; color: #bac2de; border-radius: 5px; "
                    "padding: 4px 10px; font-size: 13px;"
                )
                kw_layout.addWidget(chip)
            kw_layout.addStretch()
            main.addWidget(kw_frame)

        # Row 4: Top Competitors + Recommendations
        top_books = c.get('top_books', [])
        recs = c.get('recommendations', [])

        if top_books or recs or True:  # Always show section
            inline_row = QHBoxLayout()
            inline_row.setSpacing(12)

            if top_books:
                slider = CompetitorSlider(top_books, search_query=niche_name)
                inline_row.addWidget(slider)
            else:
                no_data = QFrame()
                no_data.setStyleSheet("background: #1e1e2e; border-radius: 8px; padding: 8px;")
                no_data.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                nd_layout = QVBoxLayout(no_data)
                nd_layout.setContentsMargins(14, 10, 14, 10)
                nd_lbl = QLabel("📚 Top Competitors — no data (probe may have failed)")
                nd_lbl.setStyleSheet("color: #585b70; font-size: 13px; font-style: italic;")
                nd_layout.addWidget(nd_lbl)
                inline_row.addWidget(no_data)

            if recs:
                rec_frame = ContextFrame(search_query=niche_name)
                rec_frame.setStyleSheet("background: #1e1e2e; border-radius: 8px; padding: 8px;")
                rec_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                rl = QVBoxLayout(rec_frame)
                rl.setContentsMargins(14, 10, 14, 10)
                rl.setSpacing(6)
                rh = _sel_label("💡 Recommendations", "color: #f9e2af; font-size: 14px; font-weight: bold;")
                rl.addWidget(rh)
                for rec in recs[:4]:
                    rec_lbl = _sel_label(
                        f"  {rec}",
                        "color: #cdd6f4; font-size: 13px;",
                        word_wrap=True,
                    )
                    rl.addWidget(rec_lbl)
                rl.addStretch()
                inline_row.addWidget(rec_frame)

            main.addLayout(inline_row)

        # Row 5: Categories + Sources + Deep info
        cats = c.get('categories', [])[:4]
        sources = c.get('sources', {})
        info_parts = []
        if cats:
            info_parts.append("📂 " + ", ".join(
                cat.replace('_', ' ').title() for cat in cats
            ))
        src_icons = {
            'movers': '📈', 'new_release': '🆕', 'wished': '💫',
            'bestseller_kw': '🏆', 'google_trend': '🔥', 'autocomplete': '🔤',
            'autocomplete_custom': '🔎', 'tiktok_booktok': '🎵',
            'reddit_demand': '🤖', 'autocomplete_deep': '🔬',
            'autocomplete_sniper': '🎯',
        }
        src_parts = [
            f"{src_icons.get(s, '•')}{cnt}"
            for s, cnt in sources.items() if cnt > 0
        ]
        if src_parts:
            info_parts.append("Sources: " + " ".join(src_parts))
        if c.get('has_custom_seed'):
            seed_names = c.get('custom_seed_names', [])
            seed_str = ', '.join(seed_names[:3]) if seed_names else 'custom'
            info_parts.append(f"🔎 Seed: {seed_str}")
        if c.get('has_deep'):
            deep_names = c.get('deep_seed_names', [])
            if deep_names:
                info_parts.append(f"🔬 From: {', '.join(deep_names[:2])}")
        info_parts.append(f"Cluster size: {c.get('size', 0)}")
        info_parts.append(f"Multi-score: {c.get('multi_source_score', 0)}")

        info_lbl = _sel_label(" │ ".join(info_parts), "color: #45475a; font-size: 11px;", word_wrap=True)
        main.addWidget(info_lbl)


class FindForMePage(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._last_results = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 8)
        layout.setSpacing(10)

        # Header
        header = QLabel("🎯 Find For Me — Niche Sniper")
        header.setStyleSheet("font-size: 24px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(header)

        desc = QLabel(
            "Auto-discovers the hottest KDP niches. Choose your depth, market type, and sources below."
        )
        desc.setStyleSheet("color: #a6adc8; font-size: 13px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Sources panel
        self._sources_panel = SourcesPanel()
        layout.addWidget(self._sources_panel)

        # Button row
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)

        self._find_btn = QPushButton("🎯 Find For Me")
        self._find_btn.setFixedHeight(44)
        self._find_btn.setFixedWidth(200)
        self._find_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #f38ba8, stop:1 #fab387);
                color: #1e1e2e; font-weight: bold; font-size: 15px;
                border-radius: 10px; padding: 6px 20px;
            }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #eba0ac, stop:1 #f9e2af); }
            QPushButton:disabled { background: #45475a; color: #6c7086; }
        """)
        self._find_btn.clicked.connect(self._on_find)
        ctrl_row.addWidget(self._find_btn)

        self._mp_dropdown = MarketplaceDropdown()
        ctrl_row.addWidget(self._mp_dropdown)

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
        ctrl_row.addWidget(self._cancel_btn)

        self._export_json_btn = QPushButton("📥 JSON")
        self._export_json_btn.setFixedHeight(44)
        self._export_json_btn.setFixedWidth(100)
        self._export_json_btn.setEnabled(False)
        self._export_json_btn.setStyleSheet("""
            QPushButton {
                background: #313244; color: #a6e3a1; font-weight: bold;
                border-radius: 8px; font-size: 13px; border: 1px solid #45475a;
            }
            QPushButton:hover { background: #45475a; }
            QPushButton:disabled { background: #1e1e2e; color: #45475a; border-color: #313244; }
        """)
        self._export_json_btn.clicked.connect(self._on_export_json)
        ctrl_row.addWidget(self._export_json_btn)

        self._export_csv_btn = QPushButton("📊 CSV")
        self._export_csv_btn.setFixedHeight(44)
        self._export_csv_btn.setFixedWidth(100)
        self._export_csv_btn.setEnabled(False)
        self._export_csv_btn.setStyleSheet("""
            QPushButton {
                background: #313244; color: #89b4fa; font-weight: bold;
                border-radius: 8px; font-size: 13px; border: 1px solid #45475a;
            }
            QPushButton:hover { background: #45475a; }
            QPushButton:disabled { background: #1e1e2e; color: #45475a; border-color: #313244; }
        """)
        self._export_csv_btn.clicked.connect(self._on_export_csv)
        ctrl_row.addWidget(self._export_csv_btn)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # Status
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #a6adc8; font-size: 13px;")
        layout.addWidget(self._status_label)

        # Summary bar
        self._summary_bar = QFrame()
        self._summary_bar.setStyleSheet(
            "background: #181825; border-radius: 8px; padding: 10px;"
        )
        summary_layout = QHBoxLayout(self._summary_bar)
        summary_layout.setContentsMargins(14, 8, 14, 8)
        self._summary_labels = {}
        for key, icon in [('total', '📊'), ('hot', '🔥'), ('gem', '💎'),
                          ('rising', '📈'), ('avoid', '⚠️'), ('go', '🟢')]:
            lbl = QLabel(f"{icon} 0")
            lbl.setStyleSheet("color: #cdd6f4; font-size: 15px; font-weight: bold;")
            summary_layout.addWidget(lbl)
            self._summary_labels[key] = lbl
            if key != 'go':
                sep = QLabel("|")
                sep.setStyleSheet("color: #313244; font-size: 15px;")
                summary_layout.addWidget(sep)
        summary_layout.addStretch()
        self._summary_bar.setVisible(False)
        layout.addWidget(self._summary_bar)

        # Tab bar + filters
        self._tabs_widget = QWidget()
        tabs_layout = QVBoxLayout(self._tabs_widget)
        tabs_layout.setContentsMargins(0, 0, 0, 0)
        tabs_layout.setSpacing(6)

        tab_row = QHBoxLayout()
        self._tab_cards_btn = QPushButton("🃏 Cards")
        self._tab_cards_btn.setCheckable(True)
        self._tab_cards_btn.setChecked(True)
        self._tab_cards_btn.setFixedHeight(32)
        self._tab_cards_btn.setStyleSheet("""
            QPushButton { background: #313244; color: #cdd6f4; border: none;
                border-radius: 4px; padding: 2px 14px; font-size: 13px; }
            QPushButton:hover { background: #45475a; }
            QPushButton:checked { background: #585b70; }
        """)
        self._tab_cards_btn.clicked.connect(lambda: self._switch_view('cards'))
        tab_row.addWidget(self._tab_cards_btn)

        self._tab_table_btn = QPushButton("📋 Table")
        self._tab_table_btn.setCheckable(True)
        self._tab_table_btn.setFixedHeight(32)
        self._tab_table_btn.setStyleSheet("""
            QPushButton { background: #313244; color: #cdd6f4; border: none;
                border-radius: 4px; padding: 2px 14px; font-size: 13px; }
            QPushButton:hover { background: #45475a; }
            QPushButton:checked { background: #585b70; }
        """)
        self._tab_table_btn.clicked.connect(lambda: self._switch_view('table'))
        tab_row.addWidget(self._tab_table_btn)

        tab_row.addSpacing(16)
        self._filter_btns = {}
        for key, label in [('all', '🌐 All'), ('hot', '🔥 Hot'), ('gem', '💎 Gems'),
                           ('rising', '📈 Rising'), ('avoid', '⚠️ Avoid'),
                           ('go_only', '🟢 GO Only')]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == 'all')
            btn.setFixedHeight(32)
            btn.setStyleSheet("""
                QPushButton { background: #313244; color: #cdd6f4; border: none;
                    border-radius: 4px; padding: 2px 12px; font-size: 13px; }
                QPushButton:hover { background: #45475a; }
                QPushButton:checked { background: #585b70; color: #cdd6f4; }
            """)
            btn.clicked.connect(lambda checked, k=key: self._on_filter(k))
            tab_row.addWidget(btn)
            self._filter_btns[key] = btn

        tab_row.addStretch()
        tabs_layout.addLayout(tab_row)

        # Cards scroll area
        self._cards_scroll = QScrollArea()
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._cards_scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
        )
        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 8, 0)
        self._cards_layout.setSpacing(12)
        self._cards_scroll.setWidget(self._cards_container)
        tabs_layout.addWidget(self._cards_scroll, 1)

        # Table view
        self._table = DataTable()
        self._table.setVisible(False)
        tabs_layout.addWidget(self._table, 1)

        self._tabs_widget.setVisible(False)
        layout.addWidget(self._tabs_widget, 1)

        # Log panel
        log_header = QHBoxLayout()
        log_header.setSpacing(4)
        self._toggle_log_btn = QPushButton("▼")
        self._toggle_log_btn.setToolTip("Toggle console")
        self._toggle_log_btn.setFixedSize(34, 28)
        self._toggle_log_btn.setStyleSheet(
            "QPushButton { background: #313244; color: #cdd6f4; border: none; "
            "border-radius: 6px; font-size: 16px; }"
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

        self._bottom_spacer = QWidget()
        self._bottom_spacer.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._bottom_spacer)

        self._current_filter = 'all'

    # ── Actions ──────────────────────────────────────────────────────

    def _on_find(self):
        mps = self._mp_dropdown.get_selected()
        mp_label = ', '.join(m.upper() for m in mps)
        settings = self._sources_panel.get_settings()

        use_ac = settings['use_autocomplete']
        use_tt = settings['use_tiktok']
        use_rd = settings['use_reddit']
        custom = settings['custom_seeds']
        depth = settings['depth']
        market_type = settings['market_type']

        depth_icons = {'quick': '⚡', 'deep': '🔍', 'sniper': '🎯'}
        depth_icon = depth_icons.get(depth, '⚡')

        self._log.clear()
        self._log.setVisible(True)
        self._log_visible = True
        self._toggle_log_btn.setVisible(True)
        self._toggle_log_btn.setText("▼")
        self._toggle_log_btn.setToolTip("Hide console")
        self._log.append(f"🎯 Starting auto-discovery [{mp_label}]")
        self._log.append(f"Depth: {depth_icon} {depth.upper()} | Market: {market_type.upper()}")
        self._log.append(
            f"Sources: Autocomplete={'✅' if use_ac else '❌'} | "
            f"TikTok={'✅' if use_tt else '❌'} | "
            f"Reddit={'✅' if use_rd else '❌'} | "
            f"Custom seeds: {len(custom)}"
        )
        if custom:
            self._log.append(f"  Seeds: {', '.join(custom)}")
        self._log.append(f"Time: {datetime.now().strftime('%H:%M:%S')}")
        self._log.append("─" * 60)

        self._find_btn.setEnabled(False)
        self._export_json_btn.setEnabled(False)
        self._export_csv_btn.setEnabled(False)
        self._cancel_btn.setVisible(True)
        self._summary_bar.setVisible(False)
        self._tabs_widget.setVisible(False)
        self._bottom_spacer.setVisible(True)

        self._worker = DiscoveryWorker(
            marketplaces=mps,
            max_probe=20,
            custom_seeds=custom,
            use_tiktok=use_tt,
            use_autocomplete=use_ac,
            use_reddit=use_rd,
            depth=depth,
            market_type=market_type,
        )
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
        pass

    def _on_status(self, text):
        self._status_label.setText(text)

    def _on_log(self, text):
        self._log.append(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, payload):
        self._find_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)

        if payload is None:
            self._status_label.setText("Cancelled.")
            self._log.append("Discovery cancelled.")
            return

        self._last_results = payload
        clusters = payload.get('clusters', [])

        if not clusters:
            self._status_label.setText("⚠ No niches discovered — try again later.")
            return

        counts = {'total': len(clusters), 'hot': 0, 'gem': 0, 'rising': 0, 'avoid': 0, 'go': 0}
        for c in clusters:
            cls = c.get('classification', 'moderate')
            if cls in counts:
                counts[cls] += 1
            if c.get('go_verdict') == 'GO':
                counts['go'] += 1

        self._summary_labels['total'].setText(f"📊 {counts['total']} niches")
        self._summary_labels['hot'].setText(f"🔥 {counts['hot']} hot")
        self._summary_labels['gem'].setText(f"💎 {counts['gem']} gems")
        self._summary_labels['rising'].setText(f"📈 {counts['rising']} rising")
        self._summary_labels['avoid'].setText(f"⚠️ {counts['avoid']} avoid")
        self._summary_labels['go'].setText(f"🟢 {counts['go']} GO")

        animated_toggle(self._summary_bar, True)
        animated_toggle(self._tabs_widget, True)
        self._bottom_spacer.setVisible(False)
        self._export_json_btn.setEnabled(True)
        self._export_csv_btn.setEnabled(True)

        self._build_cards(clusters)
        self._build_table(clusters)
        self._switch_view('cards')

        try:
            mps = self._mp_dropdown.get_selected()
            history = SearchHistory.instance()
            history.log(
                tool="Find For Me",
                action="discover",
                query=f"Auto-discovery [{', '.join(m.upper() for m in mps)}] depth={payload.get('depth', 'quick')}",
                results=[{'name': c['name'], 'badge': c.get('badge', ''), 'go_score': c.get('go_score', 0)} for c in clusters[:20]],
                result_count=len(clusters),
                notes=f"Hot: {counts['hot']} | Gems: {counts['gem']} | GO: {counts['go']}",
            )
        except Exception as e:
            logger.error(f"Failed to log discovery to history: {e}")

    def _on_error(self, message):
        self._find_btn.setEnabled(True)
        self._cancel_btn.setVisible(False)
        self._status_label.setText(f"❌ Error: {message}")
        self._log.append(f"❌ ERROR: {message}")

    def _on_export_json(self):
        if not self._last_results:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export niches to JSON",
            f"kdp_niches_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            "JSON files (*.json)",
        )
        if not path:
            return

        try:
            export_data = {
                'exported_at': datetime.now().isoformat(),
                'total_harvested': self._last_results.get('total_harvested', 0),
                'depth': self._last_results.get('depth', 'quick'),
                'market_type': self._last_results.get('market_type', 'all'),
                'niches': [],
            }

            for c in self._last_results.get('clusters', []):
                export_data['niches'].append({
                    'name': c.get('name'),
                    'classification': c.get('classification'),
                    'badge': c.get('badge'),
                    'go_score': c.get('go_score', 0),
                    'go_verdict': c.get('go_verdict', ''),
                    'pass_level': c.get('pass_level', 1),
                    'marketplaces': c.get('marketplaces', []),
                    'categories': c.get('categories', []),
                    'keywords': c.get('keywords', []),
                    'seeds': c.get('seeds', []),
                    'sources': c.get('sources', {}),
                    'metrics': {
                        'avg_bsr': c.get('avg_bsr'),
                        'competition_count': c.get('competition_count'),
                        'median_reviews': c.get('median_reviews'),
                        'ku_ratio': c.get('ku_ratio'),
                        'est_revenue': c.get('est_revenue'),
                        'daily_sales': c.get('daily_sales'),
                        'opportunity': c.get('opportunity'),
                        'price_min': c.get('price_min'),
                        'price_max': c.get('price_max'),
                        'price_avg': c.get('price_avg'),
                        'multi_source_score': c.get('multi_source_score'),
                        'size': c.get('size'),
                    },
                    'top_competitors': c.get('top_books', []),
                    'recommendations': c.get('recommendations', []),
                })

            with open(path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)

            self._status_label.setText(f"✅ Exported {len(export_data['niches'])} niches → {path}")
        except Exception as e:
            self._status_label.setText(f"❌ Export failed: {e}")

    def _on_export_csv(self):
        if not self._last_results:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export niches to CSV",
            f"kdp_niches_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV files (*.csv)",
        )
        if not path:
            return

        try:
            from kdp_scout.collectors.discovery import export_clusters_csv
            csv_str = export_clusters_csv(self._last_results.get('clusters', []))
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(csv_str)
            n = len(self._last_results.get('clusters', []))
            self._status_label.setText(f"✅ Exported {n} niches → {path}")
        except Exception as e:
            self._status_label.setText(f"❌ CSV export failed: {e}")

    def _build_cards(self, clusters):
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, cluster in enumerate(clusters):
            card = NicheCard(cluster, rank=i + 1)
            card.setProperty('classification', cluster.get('classification', 'moderate'))
            card.setProperty('go_verdict', cluster.get('go_verdict', ''))
            self._cards_layout.addWidget(card)
            # Staggered fade-in animation
            fade_in(card, duration=250 + i * 40)
        self._cards_layout.addStretch()

    def _build_table(self, clusters):
        columns = ['rank', 'go_score', 'verdict', 'badge', 'name', 'marketplaces',
                    'avg_bsr', 'competition', 'med_reviews', 'ku_pct',
                    'est_revenue', 'daily_sales', 'opportunity',
                    'price_range', 'keywords']
        display = {
            'rank': '#', 'go_score': 'GO', 'verdict': 'Verdict',
            'badge': 'Status', 'name': 'Niche',
            'marketplaces': 'MP', 'avg_bsr': 'Avg BSR',
            'competition': 'Competition', 'med_reviews': 'Med. Reviews',
            'ku_pct': 'KU %', 'est_revenue': 'Est. $/mo',
            'daily_sales': 'Daily Sales',
            'opportunity': 'Opp.', 'price_range': 'Price Range',
            'keywords': 'Keywords',
        }
        mp_flags = {'us': '🇺🇸', 'uk': '🇬🇧', 'de': '🇩🇪', 'fr': '🇫🇷', 'ca': '🇨🇦', 'au': '🇦🇺'}
        rows = []
        for i, c in enumerate(clusters):
            bsr = c.get('avg_bsr')
            comp = c.get('competition_count')
            reviews = c.get('median_reviews')
            mps = c.get('marketplaces', [])
            pmin = c.get('price_min')
            pmax = c.get('price_max')
            if pmin is not None and pmax is not None:
                price_str = f"${pmin:.2f}–${pmax:.2f}"
            elif c.get('price_avg'):
                price_str = f"~${c['price_avg']:.2f}"
            else:
                price_str = "—"
            ds = c.get('daily_sales', 0)
            rows.append({
                'rank': i + 1,
                'go_score': f"{c.get('go_score', 0):.0f}",
                'verdict': f"{c.get('go_emoji', '')} {c.get('go_verdict', '')}",
                'badge': c.get('badge', ''),
                'name': c.get('name', '').title(),
                'marketplaces': " ".join(mp_flags.get(m, m) for m in mps),
                'avg_bsr': f"{bsr:,.0f}" if bsr else '—',
                'competition': f"{comp:,}" if comp else '—',
                'med_reviews': str(int(reviews)) if reviews is not None else '—',
                'ku_pct': f"{c.get('ku_ratio', 0)*100:.0f}%",
                'est_revenue': f"${c.get('est_revenue', 0):,.0f}",
                'daily_sales': f"{ds:.1f}" if ds > 0 else "—",
                'opportunity': f"{c.get('opportunity', 0):.0f}",
                'price_range': price_str,
                'keywords': ' · '.join(c.get('keywords', [])[:4]),
            })
        self._table.load_data(rows, columns, display)

    def _switch_view(self, which):
        is_cards = which == 'cards'
        self._cards_scroll.setVisible(is_cards)
        self._table.setVisible(not is_cards)
        self._tab_cards_btn.setChecked(is_cards)
        self._tab_table_btn.setChecked(not is_cards)

    def _on_filter(self, key):
        self._current_filter = key
        for k, btn in self._filter_btns.items():
            btn.setChecked(k == key)
        for i in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(i)
            w = item.widget()
            if w and isinstance(w, NicheCard):
                if key == 'all':
                    w.setVisible(True)
                elif key == 'go_only':
                    w.setVisible(w.property('go_verdict') == 'GO')
                else:
                    w.setVisible(w.property('classification') == key)

    def _toggle_log(self):
        self._log_visible = not self._log_visible
        if self._log_visible:
            self._toggle_log_btn.setText("▼")
            self._toggle_log_btn.setToolTip("Hide console")
        else:
            self._toggle_log_btn.setText("▲")
            self._toggle_log_btn.setToolTip("Show console")
        animated_toggle(self._log, self._log_visible)

import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QStackedWidget, QLabel, QStatusBar, QFrame, QSizePolicy,
    QSystemTrayIcon, QMenu, QApplication, QComboBox,
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QSize
from PyQt6.QtGui import QAction, QIcon, QShortcut, QKeySequence, QPixmap

if getattr(sys, '_MEIPASS', None):
    _RESOURCES = Path(sys._MEIPASS) / "kdp_scout" / "gui" / "resources"
else:
    _RESOURCES = Path(__file__).parent / "resources"
_LOGO_ICO = _RESOURCES / "kdpsy.ico"
_LOGO_PATH = _LOGO_ICO if _LOGO_ICO.exists() else _RESOURCES / "kdpsy.svg"


def _load_logo_icon() -> QIcon:
    if _LOGO_PATH.exists():
        return QIcon(str(_LOGO_PATH))
    return QIcon()


class SidebarButton(QPushButton):
    def __init__(self, icon_text, label, parent=None):
        super().__init__(parent)
        self.setText(f"  {icon_text}  {label}")
        self.setCheckable(True)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("class", "sidebar-btn")


# Menu definitions per source
AMAZON_NAV = [
    ("\U0001f50d", "Keywords"),
    ("📈", "Trending"),
    ("🔬", "Niche Analyzer"),
    ("🎯", "Find For Me"),
    ("🏷", "Competitors"),
    ("📊", "Ads"),
    ("🌱", "Seeds"),
    ("🔎", "ASIN Lookup"),
]

GOOGLE_NAV = [
    ("\U0001f50d", "G-Keywords"),
    ("📈", "G-Trending"),
    ("📚", "G-Books"),
]

TIKTOK_NAV = [
    ("🎵", "T-Trends"),
]

REDDIT_NAV = [
    ("🤖", "R-Demand"),
]

GOODREADS_NAV = [
    ("📚", "GR-Explorer"),
]

COMMON_NAV = [
    ("📜", "History"),
    ("🤖", "Automation"),
    ("⚙", "Settings"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KDP Scout App")
        self.setMinimumSize(960, 600)

        self._app_icon = _load_logo_icon()
        if not self._app_icon.isNull():
            self.setWindowIcon(self._app_icon)
            QApplication.instance().setWindowIcon(self._app_icon)

        self._pages = {}
        self._page_factories = {}
        self._nav_buttons = []
        self._source_buttons = {
            "amazon": [], "google": [], "tiktok": [],
            "reddit": [], "goodreads": [], "common": [],
        }
        self._setup_ui()
        self._setup_shortcuts()
        self._restore_last_page()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Sidebar
        sidebar = QFrame()
        sidebar.setProperty("class", "sidebar")
        sidebar.setFixedWidth(200)
        self._sidebar_layout = QVBoxLayout(sidebar)
        self._sidebar_layout.setContentsMargins(8, 16, 8, 16)
        self._sidebar_layout.setSpacing(4)

        # Logo
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap(str(_LOGO_PATH)) if _LOGO_PATH.exists() else QPixmap()
        if not pixmap.isNull():
            logo_label.setPixmap(
                pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            )
            self._sidebar_layout.addWidget(logo_label)
            self._sidebar_layout.addSpacing(4)

        title = QLabel("KDP Scout App")
        title.setProperty("class", "sidebar-title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sidebar_layout.addWidget(title)
        self._sidebar_layout.addSpacing(12)

        # Source selector
        source_label = QLabel("  Data Source")
        source_label.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
        self._sidebar_layout.addWidget(source_label)

        self._source_combo = QComboBox()
        self._source_combo.addItem("🛒  Amazon", "amazon")
        self._source_combo.addItem("🔍  Google", "google")
        self._source_combo.addItem("🎵  TikTok", "tiktok")
        self._source_combo.addItem("🤖  Reddit", "reddit")
        self._source_combo.addItem("📚  Goodreads", "goodreads")
        self._source_combo.setFixedHeight(36)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        self._sidebar_layout.addWidget(self._source_combo)
        self._sidebar_layout.addSpacing(12)

        # Amazon nav buttons
        self._amazon_section_label = QLabel("  AMAZON TOOLS")
        self._amazon_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        self._sidebar_layout.addWidget(self._amazon_section_label)

        for icon, label in AMAZON_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            self._sidebar_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._source_buttons["amazon"].append(btn)

        # Google nav buttons
        self._sidebar_layout.addSpacing(4)
        self._google_section_label = QLabel("  GOOGLE TOOLS")
        self._google_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        self._sidebar_layout.addWidget(self._google_section_label)

        for icon, label in GOOGLE_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            self._sidebar_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._source_buttons["google"].append(btn)

        # TikTok nav buttons
        self._sidebar_layout.addSpacing(4)
        self._tiktok_section_label = QLabel("  TIKTOK TOOLS")
        self._tiktok_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        self._sidebar_layout.addWidget(self._tiktok_section_label)

        for icon, label in TIKTOK_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            self._sidebar_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._source_buttons["tiktok"].append(btn)

        # Reddit nav buttons
        self._sidebar_layout.addSpacing(4)
        self._reddit_section_label = QLabel("  REDDIT TOOLS")
        self._reddit_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        self._sidebar_layout.addWidget(self._reddit_section_label)

        for icon, label in REDDIT_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            self._sidebar_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._source_buttons["reddit"].append(btn)

        # Goodreads nav buttons  ← NEW
        self._sidebar_layout.addSpacing(4)
        self._goodreads_section_label = QLabel("  GOODREADS TOOLS")
        self._goodreads_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        self._sidebar_layout.addWidget(self._goodreads_section_label)

        for icon, label in GOODREADS_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            self._sidebar_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._source_buttons["goodreads"].append(btn)

        # Separator
        self._sidebar_layout.addSpacing(8)
        sep_line = QFrame()
        sep_line.setFrameShape(QFrame.Shape.HLine)
        sep_line.setStyleSheet("color: #313244;")
        self._sidebar_layout.addWidget(sep_line)
        self._sidebar_layout.addSpacing(4)

        # Common nav buttons
        for icon, label in COMMON_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            self._sidebar_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._source_buttons["common"].append(btn)

        self._sidebar_layout.addStretch()

        # Version
        try:
            from kdp_scout import __version__
            ver_label = QLabel(f"v{__version__}")
        except Exception:
            ver_label = QLabel("v3.0.0")
        ver_label.setProperty("class", "sidebar-version")
        ver_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sidebar_layout.addWidget(ver_label)

        layout.addWidget(sidebar)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setProperty("class", "sidebar-sep")
        layout.addWidget(sep)

        # Stacked pages
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)

        self._register_page_factories()

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._update_status_bar()

        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start(30000)

        # Apply initial source visibility
        self._on_source_changed()

    def _register_page_factories(self):
        from kdp_scout.gui.pages.keywords_page import KeywordsPage
        from kdp_scout.gui.pages.trending_page import TrendingPage
        from kdp_scout.gui.pages.competitors_page import CompetitorsPage
        from kdp_scout.gui.pages.ads_page import AdsPage
        from kdp_scout.gui.pages.seeds_page import SeedsPage
        from kdp_scout.gui.pages.asin_lookup_page import ASINLookupPage
        from kdp_scout.gui.pages.automation_page import AutomationPage
        from kdp_scout.gui.pages.settings_page import SettingsPage
        from kdp_scout.gui.pages.history_page import HistoryPage
        from kdp_scout.gui.pages.niche_analyzer_page import NicheAnalyzerPage
        from kdp_scout.gui.pages.google_trending_page import GoogleTrendingPage
        from kdp_scout.gui.pages.google_keywords_page import GoogleKeywordsPage
        from kdp_scout.gui.pages.google_books_page import GoogleBooksPage
        from kdp_scout.gui.pages.find_for_me_page import FindForMePage
        from kdp_scout.gui.pages.reddit_demand_page import RedditDemandPage
        from kdp_scout.gui.pages.tiktok_trends_page import TikTokTrendsPage
        from kdp_scout.gui.pages.goodreads_explorer_page import GoodreadsExplorerPage

        self._page_factories = {
            "Keywords": KeywordsPage,
            "Trending": TrendingPage,
            "Niche Analyzer": NicheAnalyzerPage,
            "Find For Me": FindForMePage,
            "Competitors": CompetitorsPage,
            "Ads": AdsPage,
            "Seeds": SeedsPage,
            "ASIN Lookup": ASINLookupPage,
            "History": HistoryPage,
            "Automation": AutomationPage,
            "Settings": SettingsPage,
            "G-Keywords": GoogleKeywordsPage,
            "G-Trending": GoogleTrendingPage,
            "G-Books": GoogleBooksPage,
            "T-Trends": TikTokTrendsPage,
            "R-Demand": RedditDemandPage,
            "GR-Explorer": GoodreadsExplorerPage,
        }

    def _on_source_changed(self, _=None):
        source = self._source_combo.currentData() or "amazon"

        show_amazon = source == "amazon"
        show_google = source == "google"
        show_tiktok = source == "tiktok"
        show_reddit = source == "reddit"
        show_goodreads = source == "goodreads"

        self._amazon_section_label.setVisible(show_amazon)
        for btn in self._source_buttons["amazon"]:
            btn.setVisible(show_amazon)

        self._google_section_label.setVisible(show_google)
        for btn in self._source_buttons["google"]:
            btn.setVisible(show_google)

        self._tiktok_section_label.setVisible(show_tiktok)
        for btn in self._source_buttons["tiktok"]:
            btn.setVisible(show_tiktok)

        self._reddit_section_label.setVisible(show_reddit)
        for btn in self._source_buttons["reddit"]:
            btn.setVisible(show_reddit)

        self._goodreads_section_label.setVisible(show_goodreads)
        for btn in self._source_buttons["goodreads"]:
            btn.setVisible(show_goodreads)

        if show_amazon:
            self._switch_page("Keywords")
        elif show_google:
            self._switch_page("G-Keywords")
        elif show_tiktok:
            self._switch_page("T-Trends")
        elif show_reddit:
            self._switch_page("R-Demand")
        elif show_goodreads:
            self._switch_page("GR-Explorer")

    def _switch_page(self, label):
        if label not in self._pages:
            factory = self._page_factories.get(label)
            if factory:
                try:
                    page = factory()
                except Exception as e:
                    import traceback, logging
                    logging.getLogger(__name__).error(
                        f"Failed to create page '{label}': {e}\n{traceback.format_exc()}"
                    )
                    from PyQt6.QtWidgets import QLabel
                    page = QLabel(f"⚠ Error loading '{label}':\n{e}")
                    page.setWordWrap(True)
                    page.setStyleSheet("color: #f38ba8; padding: 20px; font-size: 13px;")
                idx = self._stack.addWidget(page)
                self._pages[label] = idx
            else:
                return

        self._stack.setCurrentIndex(self._pages[label])

        for name, btn in self._nav_buttons:
            btn.setChecked(name == label)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self._focus_search())
        QShortcut(QKeySequence("Ctrl+1"), self, lambda: self._switch_page("Keywords"))
        QShortcut(QKeySequence("Ctrl+2"), self, lambda: self._switch_page("Trending"))
        QShortcut(QKeySequence("Ctrl+3"), self, lambda: self._switch_page("Competitors"))
        QShortcut(QKeySequence("Ctrl+4"), self, lambda: self._switch_page("Ads"))
        QShortcut(QKeySequence("Ctrl+5"), self, lambda: self._switch_page("Seeds"))
        QShortcut(QKeySequence("Ctrl+6"), self, lambda: self._switch_page("ASIN Lookup"))

    def _focus_search(self):
        current = self._stack.currentWidget()
        if hasattr(current, 'focus_search'):
            current.focus_search()

    def _restore_last_page(self):
        settings = QSettings()
        last_page = settings.value("window/last_page", "Keywords")
        if last_page in self._page_factories:
            # Also restore source
            if last_page.startswith("GR-"):
                self._source_combo.setCurrentIndex(4)
            elif last_page.startswith("R-"):
                self._source_combo.setCurrentIndex(3)
            elif last_page.startswith("T-"):
                self._source_combo.setCurrentIndex(2)
            elif last_page.startswith("G-"):
                self._source_combo.setCurrentIndex(1)
            else:
                self._source_combo.setCurrentIndex(0)
            self._switch_page(last_page)
        else:
            self._switch_page("Keywords")

    def _update_status_bar(self):
        try:
            from kdp_scout.db import KeywordRepository, BookRepository
            kw_repo = KeywordRepository()
            book_repo = BookRepository()
            kw_count = kw_repo.get_keyword_count()
            books = book_repo.get_all_books()
            kw_repo.close()
            book_repo.close()
            from kdp_scout.config import Config
            self._status_bar.showMessage(
                f"  📊 {kw_count} keywords  |  📚 {len(books)} books tracked  |  DB: {Config.get_db_path()}"
            )
        except Exception:
            self._status_bar.showMessage("  KDP Scout App Ready")

    def current_page_index(self):
        idx = self._stack.currentIndex()
        for name, page_idx in self._pages.items():
            if page_idx == idx:
                return name
        return "Keywords"

    def notify(self, title, message):
        tray = QSystemTrayIcon(self)
        if tray.isSystemTrayAvailable():
            tray.show()
            tray.showMessage(title, message)

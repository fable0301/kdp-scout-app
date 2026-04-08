import sys
import os
import re
import shutil
import tempfile
import zipfile
import subprocess
import webbrowser
from pathlib import Path

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton,
    QStackedWidget, QLabel, QStatusBar, QFrame, QSizePolicy,
    QSystemTrayIcon, QMenu, QApplication, QComboBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QShortcut, QKeySequence, QPixmap

if getattr(sys, '_MEIPASS', None):
    _RESOURCES = Path(sys._MEIPASS) / "kdp_scout" / "gui" / "resources"
else:
    _RESOURCES = Path(__file__).parent / "resources"
_LOGO_ICO = _RESOURCES / "kdpsy.ico"
_LOGO_PATH = _LOGO_ICO if _LOGO_ICO.exists() else _RESOURCES / "kdpsy.svg"

GITHUB_RAW_VERSION_URL = (
    "https://raw.githubusercontent.com/hulyx/kdp-scout-app/main/kdp_scout/__init__.py"
)
GITHUB_ZIP_URL = (
    "https://github.com/hulyx/kdp-scout-app/archive/refs/heads/main.zip"
)
GITHUB_REPO_URL = "https://github.com/hulyx/kdp-scout-app"
GITHUB_RELEASES_API_URL = "https://api.github.com/repos/hulyx/kdp-scout-app/releases/latest"


def _load_logo_icon() -> QIcon:
    if _LOGO_PATH.exists():
        return QIcon(str(_LOGO_PATH))
    return QIcon()


class UpdateCheckerThread(QThread):
    update_available = pyqtSignal(str, str)
    up_to_date = pyqtSignal()
    check_failed = pyqtSignal()

    def run(self):
        try:
            import urllib.request
            import json
            from kdp_scout import __version__ as current_version
            req = urllib.request.Request(
                GITHUB_RELEASES_API_URL,
                headers={"User-Agent": "KDP-Scout-App/update-checker"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            remote_version = data.get("tag_name", "").lstrip("v")
            if not remote_version:
                self.check_failed.emit()
                return
            exe_url = ""
            for asset in data.get("assets", []):
                if asset.get("name", "").endswith(".exe"):
                    exe_url = asset.get("browser_download_url", "")
                    break
            if remote_version != current_version:
                self.update_available.emit(remote_version, exe_url)
            else:
                self.up_to_date.emit()
        except Exception:
            self.check_failed.emit()


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
        self._update_thread = None
        self._pending_version = None
        self._pending_exe_url = ""
        self._setup_ui()
        self._setup_shortcuts()
        self._restore_last_page()
        self._start_update_check()

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

        # Goodreads nav buttons
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

        # ── Update checker ──────────────────────────────────────────
        # "Check for Update" button — always visible by default
        self._check_update_btn = QPushButton("🔄 Checking...")
        self._check_update_btn.setFixedHeight(28)
        self._check_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check_update_btn.setProperty("class", "update-check-btn")
        self._check_update_btn.setEnabled(False)
        self._check_update_btn.clicked.connect(self._on_check_update_clicked)
        self._sidebar_layout.addWidget(self._check_update_btn)

        # Temporary "Up to date!" label (hidden by default)
        self._update_ok_label = QLabel("✅ Up to date!")
        self._update_ok_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_ok_label.setStyleSheet(
            "color: #a6e3a1; font-size: 11px; font-weight: bold; padding: 2px 0;"
        )
        self._update_ok_label.hide()
        self._sidebar_layout.addWidget(self._update_ok_label)
        # ────────────────────────────────────────────────────────────

        # Version
        try:
            from kdp_scout import __version__
            ver_label = QLabel(f"v{__version__}")
        except Exception:
            ver_label = QLabel("v0.4.0")
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

    # ------------------------------------------------------------------
    # Update checker
    # ------------------------------------------------------------------

    def _on_check_update_clicked(self):
        self._start_update_check()

    def _start_update_check(self):
        # Reset button to "Checking…" state
        self._pending_version = None
        self._check_update_btn.setText("🔄 Checking...")
        self._check_update_btn.setEnabled(False)
        self._set_update_btn_class("update-check-btn")
        self._update_ok_label.hide()
        self._check_update_btn.show()

        # Disconnect any old click handler and restore default
        try:
            self._check_update_btn.clicked.disconnect()
        except Exception:
            pass
        self._check_update_btn.clicked.connect(self._on_check_update_clicked)

        self._update_thread = UpdateCheckerThread()
        self._update_thread.update_available.connect(self._on_update_available)
        self._update_thread.up_to_date.connect(self._on_up_to_date)
        self._update_thread.check_failed.connect(self._on_check_failed)
        self._update_thread.start()

    def _set_update_btn_class(self, cls: str):
        self._check_update_btn.setProperty("class", cls)
        self._check_update_btn.style().unpolish(self._check_update_btn)
        self._check_update_btn.style().polish(self._check_update_btn)

    def _on_update_available(self, new_version: str, exe_url: str):
        self._pending_version = new_version
        self._pending_exe_url = exe_url
        self._check_update_btn.setText(f"⬆ v{new_version} available!")
        self._set_update_btn_class("update-check-btn-available")
        self._check_update_btn.setEnabled(True)
        try:
            self._check_update_btn.clicked.disconnect()
        except Exception:
            pass
        self._check_update_btn.clicked.connect(
            lambda: self._do_update(new_version, exe_url)
        )

    def _on_up_to_date(self):
        # Hide button, show "✅ Up to date!" for 15 seconds then restore
        self._check_update_btn.hide()
        self._update_ok_label.show()
        QTimer.singleShot(15000, self._restore_check_update_btn)

    def _restore_check_update_btn(self):
        self._update_ok_label.hide()
        self._check_update_btn.setText("🔄 Check for Update")
        self._set_update_btn_class("update-check-btn")
        self._check_update_btn.setEnabled(True)
        try:
            self._check_update_btn.clicked.disconnect()
        except Exception:
            pass
        self._check_update_btn.clicked.connect(self._on_check_update_clicked)
        self._check_update_btn.show()

    def _on_check_failed(self):
        self._check_update_btn.setText("🔄 Check for Update")
        self._set_update_btn_class("update-check-btn")
        self._check_update_btn.setEnabled(True)

    def _do_update(self, new_version: str, exe_url: str = ""):
        reply = QMessageBox.question(
            self,
            "Update Available",
            f"Version {new_version} is available.\n\n"
            "Download and apply the update now?\n"
            "The app will restart automatically.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if getattr(sys, "frozen", False):
            if not exe_url:
                webbrowser.open(GITHUB_REPO_URL)
                return
            self._apply_frozen_update(new_version, exe_url)
        else:
            self._apply_update(new_version)

    def _apply_frozen_update(self, new_version: str, exe_url: str):
        import urllib.request

        current_exe = Path(sys.executable)
        self._check_update_btn.setText("⬇ Downloading...")
        self._check_update_btn.setEnabled(False)
        QApplication.processEvents()

        try:
            tmp_exe = Path(tempfile.mktemp(suffix=".exe"))
            req = urllib.request.Request(
                exe_url,
                headers={"User-Agent": "KDP-Scout-App/updater"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(tmp_exe, "wb") as f:
                    f.write(resp.read())

            bat_path = Path(tempfile.mktemp(suffix=".bat"))
            bat_content = (
                "@echo off\n"
                f"title KDP Scout - Updating to v{new_version}...\n"
                "timeout /t 2 /nobreak > NUL\n"
                "echo Applying update...\n"
                f'copy /y "{tmp_exe}" "{current_exe}"\n'
                "if errorlevel 1 (\n"
                "    echo Update failed - could not replace executable.\n"
                "    pause\n"
                "    del \"%~f0\"\n"
                "    exit /b 1\n"
                ")\n"
                "echo Done! Restarting KDP Scout...\n"
                f'start \"\" "{current_exe}"\n'
                f'del "{tmp_exe}"\n'
                "del \"%~f0\"\n"
            )
            bat_path.write_text(bat_content, encoding="utf-8")

            CREATE_NEW_CONSOLE = 0x00000010
            subprocess.Popen(
                ["cmd", "/c", str(bat_path)],
                creationflags=CREATE_NEW_CONSOLE,
            )
            QApplication.instance().quit()

        except Exception as exc:
            QMessageBox.critical(
                self, "Update Failed", f"Could not download update:\n{exc}"
            )
            self._check_update_btn.setText(f"⬆ v{new_version} available!")
            self._set_update_btn_class("update-check-btn-available")
            self._check_update_btn.setEnabled(True)

    def _apply_update(self, new_version: str):
        import urllib.request

        app_dir = Path(__file__).parent.parent.parent

        self._check_update_btn.setText("⬇ Downloading...")
        self._check_update_btn.setEnabled(False)
        QApplication.processEvents()

        try:
            tmp_zip = tempfile.mktemp(suffix=".zip")
            req = urllib.request.Request(
                GITHUB_ZIP_URL,
                headers={"User-Agent": "KDP-Scout-App/update-checker"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                with open(tmp_zip, "wb") as f:
                    f.write(resp.read())

            self._check_update_btn.setText("📦 Extracting...")
            QApplication.processEvents()

            tmp_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                zf.extractall(tmp_dir)

            extracted = Path(tmp_dir) / "kdp-scout-app-main"
            for item in extracted.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(extracted)
                    dest = app_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(item), str(dest))

            os.unlink(tmp_zip)
            shutil.rmtree(tmp_dir)

            QMessageBox.information(
                self,
                "Update Complete",
                f"Successfully updated to v{new_version}!\nThe app will now restart.",
            )

            script = str(app_dir / "kdp_scout_gui.py")
            subprocess.Popen([sys.executable, script], cwd=str(app_dir))
            QApplication.instance().quit()

        except Exception as exc:
            QMessageBox.critical(
                self, "Update Failed", f"Could not apply update:\n{exc}"
            )
            self._check_update_btn.setText(f"⬆ v{new_version} available!")
            self._set_update_btn_class("update-check-btn-available")
            self._check_update_btn.setEnabled(True)

    # ------------------------------------------------------------------

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

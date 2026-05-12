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
    QDialog, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QSettings, QTimer, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QShortcut, QKeySequence, QPixmap

if getattr(sys, '_MEIPASS', None):
    _RESOURCES = Path(sys._MEIPASS) / "scout" / "gui" / "resources"
else:
    _RESOURCES = Path(__file__).parent / "resources"
_LOGO_ICO = _RESOURCES / "kdpsy.ico"
_LOGO_PATH = _RESOURCES / "kdpsy.svg"
_POD_LOGO_PATH = _RESOURCES / "kdpsy_pod.svg"

GITHUB_RAW_VERSION_URL = (
    "https://raw.githubusercontent.com/hulyx/kdp-scout-app/main/scout/__init__.py"
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
            from scout import __version__ as current_version
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
    ("🔍", "Keywords"),
    ("📈", "Trending"),
    ("🔬", "Niche Analyzer"),
    ("🎯", "Find For Me"),
    ("🏷", "Competitors"),
    ("📊", "Ads"),
    ("🌱", "Seeds"),
    ("🔎", "ASIN Lookup"),
]

GOOGLE_NAV = [
    ("🔍", "G-Keywords"),
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
    ("⚙", "Settings"),
]

POD_NAV = [
    ("🔍", "Keywords"),
    ("📈", "Trending"),
    ("🔬", "Niche Analyzer"),
    ("🎯", "Find For Me"),
    ("🏷", "Competitors"),
    ("🌱", "Seeds"),
    ("📌", "Pinterest"),
    ("🔎", "Product Lookup"),
    ("📊", "Market Overview"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Scout")
        self.setMinimumSize(960, 600)
        self._mode = 'kdp'

        self._app_icon = _load_logo_icon()
        if not self._app_icon.isNull():
            self.setWindowIcon(self._app_icon)
            QApplication.instance().setWindowIcon(self._app_icon)

        self._pages = {}
        self._page_factories = {}
        self._pod_pages = {}
        self._pod_page_factories = {}
        self._nav_buttons = []
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

        # Sidebar container
        self._sidebar = QFrame()
        self._sidebar.setProperty("class", "sidebar")
        self._sidebar.setFixedWidth(200)
        self._sidebar_layout = QVBoxLayout(self._sidebar)
        self._sidebar_layout.setContentsMargins(8, 16, 8, 16)
        self._sidebar_layout.setSpacing(4)

        # Store reference to sidebar for later use
        self._sidebar_container = self._sidebar

        # Logo (clickable to toggle mode)
        self._logo_label = QLabel()
        self._logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo_label.setCursor(Qt.CursorShape.PointingHandCursor)
        pixmap = QPixmap(str(_LOGO_PATH)) if _LOGO_PATH.exists() else QPixmap()
        if not pixmap.isNull():
            self._logo_label.setPixmap(
                pixmap.scaled(68, 68, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
            )
            self._sidebar_layout.addWidget(self._logo_label)
            self._sidebar_layout.addSpacing(4)

        self._title = QLabel("Scout")
        self._title.setProperty("class", "sidebar-title")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sidebar_layout.addWidget(self._title)

        # Mode label
        self._mode_label = QLabel("KDP MODE")
        self._mode_label.setProperty("class", "sidebar-mode")
        self._mode_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sidebar_layout.addWidget(self._mode_label)

        self._sidebar_layout.addSpacing(8)

        self._logo_label.mousePressEvent = lambda e: self._toggle_mode()

        # KDP container
        self._kdp_container = QWidget()
        kdp_layout = QVBoxLayout(self._kdp_container)
        kdp_layout.setContentsMargins(0, 0, 0, 0)
        kdp_layout.setSpacing(4)

        # KDP source selector
        source_label = QLabel("  Data Source")
        source_label.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
        kdp_layout.addWidget(source_label)

        self._source_combo = QComboBox()
        self._source_combo.addItem("🛒  Amazon", "amazon")
        self._source_combo.addItem("🔍  Google", "google")
        self._source_combo.addItem("🎵  TikTok", "tiktok")
        self._source_combo.addItem("🤖  Reddit", "reddit")
        self._source_combo.addItem("📚  Goodreads", "goodreads")
        self._source_combo.setFixedHeight(36)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        kdp_layout.addWidget(self._source_combo)
        kdp_layout.addSpacing(12)

        # Amazon section
        self._amazon_section_label = QLabel("  AMAZON TOOLS")
        self._amazon_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        kdp_layout.addWidget(self._amazon_section_label)

        self._amazon_buttons = []
        for icon, label in AMAZON_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            kdp_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._amazon_buttons.append(btn)

        # Google section
        kdp_layout.addSpacing(4)
        self._google_section_label = QLabel("  GOOGLE TOOLS")
        self._google_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        kdp_layout.addWidget(self._google_section_label)

        self._google_buttons = []
        for icon, label in GOOGLE_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            kdp_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._google_buttons.append(btn)

        # TikTok section
        kdp_layout.addSpacing(4)
        self._tiktok_section_label = QLabel("  TIKTOK TOOLS")
        self._tiktok_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        kdp_layout.addWidget(self._tiktok_section_label)

        self._tiktok_buttons = []
        for icon, label in TIKTOK_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            kdp_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._tiktok_buttons.append(btn)

        # Reddit section
        kdp_layout.addSpacing(4)
        self._reddit_section_label = QLabel("  REDDIT TOOLS")
        self._reddit_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        kdp_layout.addWidget(self._reddit_section_label)

        self._reddit_buttons = []
        for icon, label in REDDIT_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            kdp_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._reddit_buttons.append(btn)

        # Goodreads section
        kdp_layout.addSpacing(4)
        self._goodreads_section_label = QLabel("  GOODREADS TOOLS")
        self._goodreads_section_label.setStyleSheet("color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
        kdp_layout.addWidget(self._goodreads_section_label)

        self._goodreads_buttons = []
        for icon, label in GOODREADS_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l))
            kdp_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._goodreads_buttons.append(btn)

        kdp_layout.addStretch()
        self._kdp_container.setLayout(kdp_layout)

        # POD container
        self._pod_container = QWidget()
        pod_layout = QVBoxLayout(self._pod_container)
        pod_layout.setContentsMargins(0, 0, 0, 0)
        pod_layout.setSpacing(4)

        # POD source selector
        pod_source_label = QLabel("  Data Sources")
        pod_source_label.setStyleSheet("color: #6c7086; font-size: 11px; font-weight: bold;")
        pod_layout.addWidget(pod_source_label)

        self._pod_source_combo = QComboBox()
        self._pod_source_combo.addItem("🛒  Amazon", "amazon")
        self._pod_source_combo.addItem("🔍  Google", "google")
        self._pod_source_combo.addItem("📌  Pinterest", "pinterest")
        self._pod_source_combo.addItem("🎨  Etsy", "etsy")
        self._pod_source_combo.setFixedHeight(36)
        self._pod_source_combo.currentIndexChanged.connect(self._on_pod_source_changed)
        pod_layout.addWidget(self._pod_source_combo)
        pod_layout.addSpacing(12)

        # ── POD sections per source ─────────────────────────────────────────────
        POD_SOURCE_SECTIONS = {
            "amazon": {
                "label": "  AMAZON TOOLS",
                "pages": [("🔍", "Keywords"), ("🔬", "Niche Analyzer"),
                          ("🎯", "Find For Me"), ("🔎", "Product Lookup")],
            },
            "google": {
                "label": "  GOOGLE TOOLS",
                "pages": [("📈", "Trending"), ("📊", "Market Overview")],
            },
            "pinterest": {
                "label": "  PINTEREST TOOLS",
                "pages": [("📌", "Pinterest"), ("🌱", "Seeds")],
            },
            "etsy": {
                "label": "  ETSY TOOLS",
                "pages": [("🏷", "Competitors"), ("🔎", "Product Lookup")],
            },
        }

        self._pod_buttons = []
        self._pod_section_widgets = {}   # source → (QWidget container)

        for source, info in POD_SOURCE_SECTIONS.items():
            sec_widget = QWidget()
            sec_layout = QVBoxLayout(sec_widget)
            sec_layout.setContentsMargins(0, 0, 0, 0)
            sec_layout.setSpacing(2)

            sec_lbl = QLabel(info["label"])
            sec_lbl.setStyleSheet(
                "color: #6c7086; font-size: 10px; font-weight: bold; letter-spacing: 1px;"
            )
            sec_layout.addWidget(sec_lbl)

            for icon, label in info["pages"]:
                btn = SidebarButton(icon, label)
                btn.clicked.connect(lambda checked, l=label: self._switch_pod_page(l))
                sec_layout.addWidget(btn)
                self._nav_buttons.append((label, btn))
                self._pod_buttons.append(btn)

            pod_layout.addWidget(sec_widget)
            self._pod_section_widgets[source] = sec_widget

        # Show only amazon section by default
        for src, w in self._pod_section_widgets.items():
            w.setVisible(src == "amazon")

        pod_layout.addStretch()
        self._pod_container.setLayout(pod_layout)
        self._pod_container.hide()

        # Add containers to sidebar
        self._sidebar_layout.addWidget(self._kdp_container)
        self._sidebar_layout.addWidget(self._pod_container)
        self._sidebar_layout.addSpacing(8)

        # Separator
        sep_line = QFrame()
        sep_line.setFrameShape(QFrame.Shape.HLine)
        sep_line.setStyleSheet("color: #313244;")
        self._sidebar_layout.addWidget(sep_line)
        self._sidebar_layout.addSpacing(4)

        # Common nav buttons
        self._common_buttons = []
        for icon, label in COMMON_NAV:
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, l=label: self._switch_page(l) if self._mode == 'kdp' else self._switch_pod_page(l))
            self._sidebar_layout.addWidget(btn)
            self._nav_buttons.append((label, btn))
            self._common_buttons.append(btn)

        self._sidebar_layout.addStretch()

        # Update checker button
        self._check_update_btn = QPushButton("🔄 Checking...")
        self._check_update_btn.setFixedHeight(28)
        self._check_update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._check_update_btn.setProperty("class", "update-check-btn")
        self._check_update_btn.setEnabled(False)
        self._check_update_btn.clicked.connect(self._on_check_update_clicked)
        self._sidebar_layout.addWidget(self._check_update_btn)

        # Version (clickable to open GitHub)
        try:
            from scout import __version__
            version_text = f"v{__version__}"
        except Exception:
            version_text = "v1.0"
        ver_label = QLabel(f'<a href="https://github.com/hulyx/scout-app">{version_text}</a>')
        ver_label.setOpenExternalLinks(True)
        ver_label.setProperty("class", "sidebar-version")
        ver_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_label.setToolTip("Open GitHub repository")
        ver_label.setStyleSheet("color: #6c7086; text-decoration: none;")
        self._sidebar_layout.addWidget(ver_label)

        layout.addWidget(self._sidebar)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setProperty("class", "sidebar-sep")
        layout.addWidget(sep)

        # Stacked pages
        self._stack = QStackedWidget()
        self._pod_stack = QStackedWidget()
        self._pod_stack.hide()
        layout.addWidget(self._stack, 1)
        layout.addWidget(self._pod_stack, 1)

        self._register_page_factories()
        self._register_pod_page_factories()

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
        self._pending_version = None
        self._check_update_btn.setText("🔄 Checking...")
        self._check_update_btn.setEnabled(False)
        self._set_update_btn_class("update-check-btn")
        self._check_update_btn.show()

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
        self._check_update_btn.setText("✅ Up to date!")
        self._set_update_btn_class("update-check-btn")
        self._check_update_btn.setEnabled(False)
        QTimer.singleShot(10000, self._restore_check_update_btn)

    def _restore_check_update_btn(self):
        self._check_update_btn.setText("🔄 Check for Update")
        self._set_update_btn_class("update-check-btn")
        self._check_update_btn.setEnabled(True)
        try:
            self._check_update_btn.clicked.disconnect()
        except Exception:
            pass
        self._check_update_btn.clicked.connect(self._on_check_update_clicked)

    def _on_check_failed(self):
        self._check_update_btn.setText("🔄 Check for Update")
        self._set_update_btn_class("update-check-btn")
        self._check_update_btn.setEnabled(True)

    def _do_update(self, new_version: str, exe_url: str = ""):
        dialog = QDialog(self)
        dialog.setWindowTitle("Update Available")
        dialog.setMinimumWidth(380)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 16)

        msg = QLabel(
            f"<b>Version {new_version} is available.</b><br><br>"
            "Download and apply the update now?<br>"
            "<span style='color:#888;font-size:11px;'>The app will restart automatically.</span>"
        )
        msg.setWordWrap(True)
        msg.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(msg)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        link = QLabel(f'<a href="{GITHUB_REPO_URL}/releases/latest" style="font-size:11px;color:#89b4fa;">Check on GitHub</a>')
        link.setTextFormat(Qt.TextFormat.RichText)
        link.setOpenExternalLinks(True)
        link.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(link)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if getattr(sys, "frozen", False):
            if not exe_url:
                webbrowser.open(f"{GITHUB_REPO_URL}/releases/latest")
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
                f'start "" "{current_exe}"\n'
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

            script = str(app_dir / "scout_gui.py")
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
        from scout.gui.pages.keywords_page import KeywordsPage
        from scout.gui.pages.trending_page import TrendingPage
        from scout.gui.pages.competitors_page import CompetitorsPage
        from scout.gui.pages.ads_page import AdsPage
        from scout.gui.pages.seeds_page import SeedsPage
        from scout.gui.pages.asin_lookup_page import ASINLookupPage
        from scout.gui.pages.settings_page import SettingsPage
        from scout.gui.pages.history_page import HistoryPage
        from scout.gui.pages.niche_analyzer_page import NicheAnalyzerPage
        from scout.gui.pages.google_trending_page import GoogleTrendingPage
        from scout.gui.pages.google_keywords_page import GoogleKeywordsPage
        from scout.gui.pages.google_books_page import GoogleBooksPage
        from scout.gui.pages.find_for_me_page import FindForMePage
        from scout.gui.pages.reddit_demand_page import RedditDemandPage
        from scout.gui.pages.tiktok_trends_page import TikTokTrendsPage
        from scout.gui.pages.goodreads_explorer_page import GoodreadsExplorerPage

        self._page_factories = {
            "Keywords": KeywordsPage,
            "Trending": TrendingPage,
            "Niche Analyzer": NicheAnalyzerPage,
            "Find For Me": FindForMePage,
            "Competitors": CompetitorsPage,
            "Ads": AdsPage,
            "Seeds": SeedsPage,
            "ASIN Lookup": ASINLookupPage,
            "G-Keywords": GoogleKeywordsPage,
            "G-Trending": GoogleTrendingPage,
            "G-Books": GoogleBooksPage,
            "T-Trends": TikTokTrendsPage,
            "R-Demand": RedditDemandPage,
            "GR-Explorer": GoodreadsExplorerPage,
        }
        
        # Create History and Settings for KDP stack
        self._kdp_history = HistoryPage()
        self._kdp_settings = SettingsPage()
        self._pages["History"] = self._stack.addWidget(self._kdp_history)
        self._pages["Settings"] = self._stack.addWidget(self._kdp_settings)
        
        # Create History and Settings for POD stack
        self._pod_history = HistoryPage()
        self._pod_settings = SettingsPage()
        self._pod_pages["History"] = self._pod_stack.addWidget(self._pod_history)
        self._pod_pages["Settings"] = self._pod_stack.addWidget(self._pod_settings)

    def _register_pod_page_factories(self):
        try:
            from scout.gui.pages.pod_keywords_page import PodKeywordsPage
            from scout.gui.pages.pod_trending_page import PodTrendingPage
            from scout.gui.pages.pod_niche_analyzer_page import PodNicheAnalyzerPage
            from scout.gui.pages.pod_find_for_me_page import PodFindForMePage
            from scout.gui.pages.pod_competitors_page import PodCompetitorsPage
            from scout.gui.pages.pod_seeds_page import PodSeedsPage
            from scout.gui.pages.pod_pinterest_page import PodPinterestPage
            from scout.gui.pages.pod_product_lookup_page import PodProductLookupPage
            from scout.gui.pages.pod_market_overview_page import PodMarketOverviewPage

            self._pod_page_factories = {
                "Keywords": PodKeywordsPage,
                "Trending": PodTrendingPage,
                "Niche Analyzer": PodNicheAnalyzerPage,
                "Find For Me": PodFindForMePage,
                "Competitors": PodCompetitorsPage,
                "Seeds": PodSeedsPage,
                "Pinterest": PodPinterestPage,
                "Product Lookup": PodProductLookupPage,
                "Market Overview": PodMarketOverviewPage,
            }
        except Exception as e:
            print(f'Failed to register POD pages: {e}')

    def _toggle_mode(self):
        if self._mode == 'kdp':
            # Switch to POD mode
            self._mode = 'pod'
            self._mode_label.setText('POD MODE')
            self._mode_label.setStyleSheet("color: #cba6f7; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
            self._apply_pod_style()
            self._kdp_container.hide()
            self._pod_container.show()
            self._stack.hide()
            self._pod_stack.show()
            # Change logo to POD logo (same size as KDP: 68x68)
            if _POD_LOGO_PATH.exists():
                pixmap = QPixmap(str(_POD_LOGO_PATH))
                if not pixmap.isNull():
                    self._logo_label.setPixmap(
                        pixmap.scaled(68, 68, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
                    )
            self._on_pod_source_changed(0)
        else:
            # Switch to KDP mode
            self._mode = 'kdp'
            self._mode_label.setText('KDP MODE')
            self._mode_label.setStyleSheet("color: #89b4fa; font-size: 10px; font-weight: bold; letter-spacing: 1px;")
            self._apply_kdp_style()
            self._pod_container.hide()
            self._kdp_container.show()
            self._pod_stack.hide()
            self._stack.show()
            # Change logo to KDP logo (68x68)
            if _LOGO_PATH.exists():
                pixmap = QPixmap(str(_LOGO_PATH))
                if not pixmap.isNull():
                    self._logo_label.setPixmap(
                        pixmap.scaled(68, 68, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
                    )
            self._on_source_changed()

    def _apply_pod_style(self):
        try:
            style_path = _RESOURCES / "style.qss"
            if style_path.exists():
                with open(style_path, 'r') as f:
                    style = f.read()
                style = style.replace('#89b4fa', '#cba6f7').replace('#b4befe', '#cba6f7').replace('#74c7ec', '#cba6f7')
                self.setStyleSheet(style)
        except Exception:
            pass

    def _apply_kdp_style(self):
        try:
            style_path = _RESOURCES / "style.qss"
            if style_path.exists():
                with open(style_path, 'r') as f:
                    self.setStyleSheet(f.read())
        except Exception:
            pass

    def _on_source_changed(self, _=None):
        if self._mode == 'pod':
            return

        source = self._source_combo.currentData() or "amazon"

        show_amazon = source == "amazon"
        show_google = source == "google"
        show_tiktok = source == "tiktok"
        show_reddit = source == "reddit"
        show_goodreads = source == "goodreads"

        self._amazon_section_label.setVisible(show_amazon)
        for btn in self._amazon_buttons:
            btn.setVisible(show_amazon)

        self._google_section_label.setVisible(show_google)
        for btn in self._google_buttons:
            btn.setVisible(show_google)

        self._tiktok_section_label.setVisible(show_tiktok)
        for btn in self._tiktok_buttons:
            btn.setVisible(show_tiktok)

        self._reddit_section_label.setVisible(show_reddit)
        for btn in self._reddit_buttons:
            btn.setVisible(show_reddit)

        self._goodreads_section_label.setVisible(show_goodreads)
        for btn in self._goodreads_buttons:
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

    def _on_pod_source_changed(self, _=None):
        source = self._pod_source_combo.currentData() or "amazon"
        # Show only the section for the selected source
        for src, widget in self._pod_section_widgets.items():
            widget.setVisible(src == source)
        # Default page per source
        first_page = {
            "amazon":    "Keywords",
            "google":    "Trending",
            "pinterest": "Pinterest",
            "etsy":      "Competitors",
        }.get(source, "Keywords")
        self._switch_pod_page(first_page)

    def _switch_page(self, label):
        if label not in self._pages:
            factory = self._page_factories.get(label)
            if factory:
                try:
                    page = factory()
                except Exception as e:
                    from PyQt6.QtWidgets import QLabel
                    page = QLabel(f"⚠ Error loading '{label}': {e}")
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
            from scout.db import KeywordRepository, BookRepository
            kw_repo = KeywordRepository()
            book_repo = BookRepository()
            kw_count = kw_repo.get_keyword_count()
            books = book_repo.get_all_books()
            kw_repo.close()
            book_repo.close()
            from scout.config import Config
            self._status_bar.showMessage(
                f"  📊 {kw_count} keywords  |  📚 {len(books)} books tracked  |  DB: {Config.get_db_path()}"
            )
        except Exception:
            self._status_bar.showMessage("  Scout Ready")

    def current_page_index(self):
        idx = self._stack.currentIndex()
        for name, page_idx in self._pages.items():
            if page_idx == idx:
                return name
        return "Keywords"

    def _switch_pod_page(self, label):
        """Lazy-load POD pages into pod_stack."""
        if label not in self._pod_pages:
            factory = self._pod_page_factories.get(label)
            if factory:
                try:
                    page = factory()
                except Exception as e:
                    from PyQt6.QtWidgets import QLabel
                    page = QLabel(f"⚠ Error loading '{label}': {e}")
                    page.setWordWrap(True)
                    page.setStyleSheet("color: #f38ba8; padding: 20px; font-size: 13px;")
                idx = self._pod_stack.addWidget(page)
                self._pod_pages[label] = idx
            else:
                return

        self._pod_stack.setCurrentIndex(self._pod_pages[label])

        # Update button states
        for name, btn in self._nav_buttons:
            if label in ["History", "Settings"]:
                # Handle shared pages
                if name == label:
                    btn.setChecked(True)
            else:
                btn.setChecked(name == label)

    def notify(self, title, message):
        tray = QSystemTrayIcon(self)
        if tray.isSystemTrayAvailable():
            tray.show()
            tray.showMessage(title, message)

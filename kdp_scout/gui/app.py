import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QIcon, QFont


def main():
    # Set app metadata before creating QApplication
    QApplication.setOrganizationName("KDP Scout App")
    QApplication.setApplicationName("KDP Scout App")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Set app icon (prefer .ico for best compatibility)
    # PyInstaller bundles resources under sys._MEIPASS; fall back to __file__ for dev
    if getattr(sys, '_MEIPASS', None):
        res_dir = Path(sys._MEIPASS) / "kdp_scout" / "gui" / "resources"
    else:
        res_dir = Path(__file__).parent / "resources"
    logo_ico = res_dir / "kdpsy.ico"
    logo_svg = res_dir / "kdpsy.svg"
    logo_path = logo_ico if logo_ico.exists() else logo_svg
    if logo_path.exists():
        app.setWindowIcon(QIcon(str(logo_path)))

    # Load QSS (use same res_dir resolved above for PyInstaller compat)
    qss_path = res_dir / "style.qss"
    if qss_path.exists():
        with open(qss_path, 'r') as f:
            app.setStyleSheet(f.read())

    # Initialize database
    from kdp_scout.db import init_db
    from kdp_scout.config import Config
    Config.setup_logging()
    init_db()

    from kdp_scout.gui.main_window import MainWindow
    window = MainWindow()

    # Restore window geometry
    settings = QSettings()
    geometry = settings.value("window/geometry")
    if geometry:
        window.restoreGeometry(geometry)
    else:
        window.resize(1280, 800)

    window.show()

    ret = app.exec()

    # Save window geometry
    settings.setValue("window/geometry", window.saveGeometry())
    settings.setValue("window/last_page", window.current_page_index())

    sys.exit(ret)


if __name__ == "__main__":
    main()

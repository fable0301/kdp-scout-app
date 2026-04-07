import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QComboBox, QSpinBox, QFormLayout, QGroupBox,
    QMessageBox, QScrollArea, QFileDialog, QDoubleSpinBox
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.workers.base_worker import BaseWorker


class TestConnectionWorker(BaseWorker):
    """Worker to test DataForSEO API connection."""

    def __init__(self, login: str, api_key: str, parent=None):
        super().__init__(parent)
        self.login = login
        self.api_key = api_key

    def run_task(self):
        from kdp_scout.collectors.dataforseo import DataForSEOCollector

        self.status.emit("Testing DataForSEO connection...")
        self.log.emit(f"Connecting with login: {self.login[:4]}***")

        collector = DataForSEOCollector(login=self.login, api_key=self.api_key)
        result = collector.test_connection()

        if result:
            self.log.emit("Connection successful!")
            self.status.emit("Connection OK")
        else:
            self.log.emit("Connection failed")
            raise Exception("DataForSEO connection test failed")

        return result


class SettingsPage(QWidget):
    """Page for configuring application settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._setup_ui()
        self._load_settings()

    def _setup_ui(self):
        # Use scroll area for many settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Header
        header = QLabel("<h2>⚙ Settings</h2>")
        layout.addWidget(header)

        # Database settings
        db_group = QGroupBox("Database")
        db_form = QFormLayout(db_group)

        self._db_path_input = QLineEdit()
        self._db_path_input.setPlaceholderText("Path to SQLite database")
        db_path_row = QHBoxLayout()
        db_path_row.addWidget(self._db_path_input)
        db_browse_btn = QPushButton("Browse...")
        db_browse_btn.setFixedWidth(80)
        db_browse_btn.clicked.connect(self._browse_db_path)
        db_path_row.addWidget(db_browse_btn)
        db_form.addRow("DB Path:", db_path_row)

        layout.addWidget(db_group)

        # API settings
        api_group = QGroupBox("DataForSEO API")
        api_form = QFormLayout(api_group)

        self._dataforseo_login = QLineEdit()
        self._dataforseo_login.setPlaceholderText("DataForSEO login email")
        api_form.addRow("Login:", self._dataforseo_login)

        self._dataforseo_key = QLineEdit()
        self._dataforseo_key.setPlaceholderText("DataForSEO API key")
        self._dataforseo_key.setEchoMode(QLineEdit.EchoMode.Password)
        api_form.addRow("API Key:", self._dataforseo_key)

        test_row = QHBoxLayout()
        test_row.addStretch()
        self._test_btn = QPushButton("🔌 Test Connection")
        self._test_btn.setProperty("class", "btn-primary")
        self._test_btn.clicked.connect(self._test_connection)
        test_row.addWidget(self._test_btn)
        api_form.addRow("", test_row)

        self._test_status = QLabel("")
        api_form.addRow("", self._test_status)

        layout.addWidget(api_group)

        # Google Books API
        google_group = QGroupBox("Google Books API")
        google_form = QFormLayout(google_group)

        self._google_books_key = QLineEdit()
        self._google_books_key.setPlaceholderText("Google Books API key (optional — 1000 req/day free)")
        self._google_books_key.setEchoMode(QLineEdit.EchoMode.Password)
        google_form.addRow("API Key:", self._google_books_key)

        google_info = QLabel("Free: get a key from Google Cloud Console → APIs & Services → Google Books API")
        google_info.setProperty("class", "info-text")
        google_info.setWordWrap(True)
        google_form.addRow("", google_info)

        layout.addWidget(google_group)

        # Proxy settings
        proxy_group = QGroupBox("Proxy")
        proxy_form = QFormLayout(proxy_group)

        self._proxy_url = QLineEdit()
        self._proxy_url.setPlaceholderText("http://user:pass@host:port (optional)")
        proxy_form.addRow("Proxy URL:", self._proxy_url)

        layout.addWidget(proxy_group)

        # Rate limiting
        rate_group = QGroupBox("Rate Limits")
        rate_form = QFormLayout(rate_group)

        self._rate_amazon = QDoubleSpinBox()
        self._rate_amazon.setRange(0.1, 30.0)
        self._rate_amazon.setSingleStep(0.5)
        self._rate_amazon.setDecimals(1)
        self._rate_amazon.setSuffix(" sec")
        rate_form.addRow("Amazon delay:", self._rate_amazon)

        self._rate_dataforseo = QDoubleSpinBox()
        self._rate_dataforseo.setRange(0.1, 30.0)
        self._rate_dataforseo.setSingleStep(0.5)
        self._rate_dataforseo.setDecimals(1)
        self._rate_dataforseo.setSuffix(" sec")
        rate_form.addRow("DataForSEO delay:", self._rate_dataforseo)

        self._max_concurrent = QSpinBox()
        self._max_concurrent.setRange(1, 20)
        rate_form.addRow("Max concurrent:", self._max_concurrent)

        layout.addWidget(rate_group)

        # Logging
        log_group = QGroupBox("Logging")
        log_form = QFormLayout(log_group)

        self._log_level = QComboBox()
        self._log_level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        log_form.addRow("Log Level:", self._log_level)

        layout.addWidget(log_group)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._reset_btn = QPushButton("↩ Reset to Defaults")
        self._reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(self._reset_btn)

        self._save_btn = QPushButton("💾 Save Settings")
        self._save_btn.setProperty("class", "btn-primary")
        self._save_btn.clicked.connect(self._save_settings)
        btn_row.addWidget(self._save_btn)

        layout.addLayout(btn_row)
        layout.addStretch()

        scroll.setWidget(content)

        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _load_settings(self):
        try:
            from kdp_scout.config import Config

            self._db_path_input.setText(str(Config.get_db_path()))
            self._dataforseo_login.setText(Config.DATAFORSEO_LOGIN or "")
            self._dataforseo_key.setText(Config.DATAFORSEO_API_KEY or "")
            self._proxy_url.setText(Config.PROXY_URL or "")
            self._google_books_key.setText(getattr(Config, 'GOOGLE_BOOKS_API_KEY', '') or "")

            self._rate_amazon.setValue(getattr(Config, 'AMAZON_RATE_LIMIT', 2.0))
            self._rate_dataforseo.setValue(getattr(Config, 'DATAFORSEO_RATE_LIMIT', 1.0))
            self._max_concurrent.setValue(getattr(Config, 'MAX_CONCURRENT', 3))

            log_level = getattr(Config, 'LOG_LEVEL', 'INFO')
            idx = self._log_level.findText(log_level)
            if idx >= 0:
                self._log_level.setCurrentIndex(idx)

        except Exception as e:
            QMessageBox.warning(self, "Settings", f"Could not load settings: {e}")

    def _save_settings(self):
        try:
            env_lines = []

            db_path = self._db_path_input.text().strip()
            if db_path:
                env_lines.append(f"KDP_SCOUT_DB_PATH={db_path}")

            login = self._dataforseo_login.text().strip()
            if login:
                env_lines.append(f"DATAFORSEO_LOGIN={login}")

            api_key = self._dataforseo_key.text().strip()
            if api_key:
                env_lines.append(f"DATAFORSEO_API_KEY={api_key}")

            proxy = self._proxy_url.text().strip()
            if proxy:
                env_lines.append(f"PROXY_URL={proxy}")

            google_key = self._google_books_key.text().strip()
            if google_key:
                env_lines.append(f"GOOGLE_BOOKS_API_KEY={google_key}")

            env_lines.append(f"AMAZON_RATE_LIMIT={self._rate_amazon.value()}")
            env_lines.append(f"DATAFORSEO_RATE_LIMIT={self._rate_dataforseo.value()}")
            env_lines.append(f"MAX_CONCURRENT={self._max_concurrent.value()}")
            env_lines.append(f"LOG_LEVEL={self._log_level.currentText()}")

            # Write to .env file
            env_path = Path.home() / ".kdp-scout" / ".env"
            env_path.parent.mkdir(parents=True, exist_ok=True)

            # Read existing .env and merge
            existing = {}
            if env_path.exists():
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, _, value = line.partition('=')
                            existing[key.strip()] = value.strip()

            # Update with new values
            for line in env_lines:
                key, _, value = line.partition('=')
                existing[key.strip()] = value.strip()

            # Write back
            with open(env_path, 'w') as f:
                f.write("# KDP Scout Configuration\n")
                f.write("# Auto-generated by KDP Scout GUI\n\n")
                for key, value in sorted(existing.items()):
                    f.write(f"{key}={value}\n")

            QMessageBox.information(
                self, "Settings Saved",
                f"Settings saved to {env_path}\n\nRestart the app for changes to take effect."
            )

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")

    def _reset_defaults(self):
        reply = QMessageBox.question(
            self, "Reset Settings",
            "Reset all settings to their default values?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._db_path_input.setText("")
            self._dataforseo_login.setText("")
            self._dataforseo_key.setText("")
            self._proxy_url.setText("")
            self._google_books_key.setText("")
            self._rate_amazon.setValue(2.0)
            self._rate_dataforseo.setValue(1.0)
            self._max_concurrent.setValue(3)
            self._log_level.setCurrentText("INFO")

    def _browse_db_path(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Database Location", "", "SQLite (*.db);;All Files (*)"
        )
        if filepath:
            self._db_path_input.setText(filepath)

    def _test_connection(self):
        login = self._dataforseo_login.text().strip()
        api_key = self._dataforseo_key.text().strip()

        if not login or not api_key:
            QMessageBox.warning(self, "Test", "Please enter login and API key first.")
            return

        self._test_btn.setEnabled(False)
        self._test_status.setText("Testing...")
        self._test_status.setStyleSheet("color: #f9e2af;")

        self._worker = TestConnectionWorker(login, api_key)
        self._worker.finished_with_result.connect(self._on_test_success)
        self._worker.error.connect(self._on_test_error)
        self._worker.start()

    def _on_test_success(self, result):
        self._test_btn.setEnabled(True)
        self._test_status.setText("✅ Connection successful!")
        self._test_status.setStyleSheet("color: #a6e3a1;")
        self._worker = None

    def _on_test_error(self, error_msg):
        self._test_btn.setEnabled(True)
        self._test_status.setText(f"❌ Connection failed: {error_msg}")
        self._test_status.setStyleSheet("color: #f38ba8;")
        self._worker = None

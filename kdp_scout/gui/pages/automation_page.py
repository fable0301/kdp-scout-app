from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QPlainTextEdit, QFrame, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt, QTimer, QSettings

from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.base_worker import BaseWorker


class DailyWorker(BaseWorker):
    """Worker that runs the daily automation."""

    def run_task(self):
        from kdp_scout.automation import DailyAutomation

        self.status.emit("Running daily automation...")
        self.log.emit("Starting daily tasks...")

        auto = DailyAutomation()

        def on_progress(message):
            self.log.emit(message)

        result = auto.run_daily(progress_callback=on_progress)

        self.log.emit("\nDaily automation complete.")
        summary = auto.get_daily_summary()
        if summary:
            for key, value in summary.items():
                self.log.emit(f"  {key}: {value}")

        self.status.emit("Daily automation complete")
        return result


class WeeklyWorker(BaseWorker):
    """Worker that runs the weekly automation."""

    def run_task(self):
        from kdp_scout.automation import DailyAutomation

        self.status.emit("Running weekly automation...")
        self.log.emit("Starting weekly tasks...")

        auto = DailyAutomation()

        def on_progress(message):
            self.log.emit(message)

        result = auto.run_weekly(progress_callback=on_progress)

        self.log.emit("\nWeekly automation complete.")
        self.status.emit("Weekly automation complete")
        return result


class AutomationPage(QWidget):
    """Page for managing automated tasks."""

    DAILY_INTERVAL_MS = 24 * 60 * 60 * 1000  # 24 hours
    WEEKLY_INTERVAL_MS = 7 * 24 * 60 * 60 * 1000  # 7 days

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._daily_timer = QTimer(self)
        self._daily_timer.timeout.connect(self._run_daily)
        self._weekly_timer = QTimer(self)
        self._weekly_timer.timeout.connect(self._run_weekly)
        self._setup_ui()
        self._restore_settings()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("<h2>🤖 Automation</h2>")
        layout.addWidget(header)

        # Schedule controls
        schedule_group = QGroupBox("Scheduled Tasks")
        schedule_layout = QVBoxLayout(schedule_group)

        # Daily row
        daily_row = QHBoxLayout()
        daily_row.setSpacing(12)

        self._daily_toggle = QPushButton("Enable Daily")
        self._daily_toggle.setCheckable(True)
        self._daily_toggle.setProperty("class", "btn-toggle")
        self._daily_toggle.toggled.connect(self._on_daily_toggled)
        daily_row.addWidget(self._daily_toggle)

        self._daily_status = QLabel("Disabled")
        self._daily_status.setProperty("class", "automation-status")
        daily_row.addWidget(self._daily_status)

        daily_row.addStretch()

        self._run_daily_btn = QPushButton("▶ Run Daily Now")
        self._run_daily_btn.setProperty("class", "btn-primary")
        self._run_daily_btn.clicked.connect(self._run_daily)
        daily_row.addWidget(self._run_daily_btn)

        schedule_layout.addLayout(daily_row)

        # Daily info
        daily_info = QLabel(
            "Daily: Mines keywords from all seeds, takes competitor snapshots, "
            "scores new keywords."
        )
        daily_info.setWordWrap(True)
        daily_info.setProperty("class", "info-text")
        schedule_layout.addWidget(daily_info)

        # Weekly row
        weekly_row = QHBoxLayout()
        weekly_row.setSpacing(12)

        self._weekly_toggle = QPushButton("Enable Weekly")
        self._weekly_toggle.setCheckable(True)
        self._weekly_toggle.setProperty("class", "btn-toggle")
        self._weekly_toggle.toggled.connect(self._on_weekly_toggled)
        weekly_row.addWidget(self._weekly_toggle)

        self._weekly_status = QLabel("Disabled")
        self._weekly_status.setProperty("class", "automation-status")
        weekly_row.addWidget(self._weekly_status)

        weekly_row.addStretch()

        self._run_weekly_btn = QPushButton("▶ Run Weekly Now")
        self._run_weekly_btn.setProperty("class", "btn-primary")
        self._run_weekly_btn.clicked.connect(self._run_weekly)
        weekly_row.addWidget(self._run_weekly_btn)

        schedule_layout.addLayout(weekly_row)

        weekly_info = QLabel(
            "Weekly: Discovers trending keywords, generates reports, "
            "exports updated KDP backend keywords."
        )
        weekly_info.setWordWrap(True)
        weekly_info.setProperty("class", "info-text")
        schedule_layout.addWidget(weekly_info)

        layout.addWidget(schedule_group)

        # Summary panel
        summary_group = QGroupBox("Last Run Summary")
        summary_layout = QVBoxLayout(summary_group)

        self._summary_label = QLabel("No automation has been run yet.")
        self._summary_label.setWordWrap(True)
        self._summary_label.setProperty("class", "summary-text")
        summary_layout.addWidget(self._summary_label)

        layout.addWidget(summary_group)

        # Log output
        log_group = QGroupBox("Automation Log")
        log_layout = QVBoxLayout(log_group)

        self._log_output = QPlainTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setProperty("class", "log-output")
        self._log_output.setMinimumHeight(200)
        log_layout.addWidget(self._log_output)

        clear_row = QHBoxLayout()
        clear_row.addStretch()
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self._log_output.clear)
        clear_row.addWidget(clear_btn)
        log_layout.addLayout(clear_row)

        layout.addWidget(log_group, 1)

        # Progress
        self._progress = ProgressPanel(show_log=False)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

    def _restore_settings(self):
        settings = QSettings()
        daily_enabled = settings.value("automation/daily_enabled", False, type=bool)
        weekly_enabled = settings.value("automation/weekly_enabled", False, type=bool)

        if daily_enabled:
            self._daily_toggle.setChecked(True)
        if weekly_enabled:
            self._weekly_toggle.setChecked(True)

    def _save_settings(self):
        settings = QSettings()
        settings.setValue("automation/daily_enabled", self._daily_toggle.isChecked())
        settings.setValue("automation/weekly_enabled", self._weekly_toggle.isChecked())

    def _on_daily_toggled(self, checked: bool):
        if checked:
            self._daily_toggle.setText("✅ Daily Enabled")
            self._daily_status.setText("Scheduled (runs every 24h)")
            self._daily_timer.start(self.DAILY_INTERVAL_MS)
            self._log("Daily automation enabled")
        else:
            self._daily_toggle.setText("Enable Daily")
            self._daily_status.setText("Disabled")
            self._daily_timer.stop()
            self._log("Daily automation disabled")
        self._save_settings()

    def _on_weekly_toggled(self, checked: bool):
        if checked:
            self._weekly_toggle.setText("✅ Weekly Enabled")
            self._weekly_status.setText("Scheduled (runs every 7 days)")
            self._weekly_timer.start(self.WEEKLY_INTERVAL_MS)
            self._log("Weekly automation enabled")
        else:
            self._weekly_toggle.setText("Enable Weekly")
            self._weekly_status.setText("Disabled")
            self._weekly_timer.stop()
            self._log("Weekly automation disabled")
        self._save_settings()

    def _set_buttons_enabled(self, enabled: bool):
        self._run_daily_btn.setEnabled(enabled)
        self._run_weekly_btn.setEnabled(enabled)

    def _run_daily(self):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "Busy", "An automation task is already running.")
            return

        self._set_buttons_enabled(False)
        self._progress.start()
        self._log("\n--- Starting Daily Automation ---")

        self._worker = DailyWorker()
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.finished_with_result.connect(self._on_daily_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _run_weekly(self):
        if self._worker and self._worker.isRunning():
            QMessageBox.warning(self, "Busy", "An automation task is already running.")
            return

        self._set_buttons_enabled(False)
        self._progress.start()
        self._log("\n--- Starting Weekly Automation ---")

        self._worker = WeeklyWorker()
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._log)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.finished_with_result.connect(self._on_weekly_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_daily_finished(self, result):
        self._set_buttons_enabled(True)
        self._progress.finish("Daily automation complete")
        self._log("--- Daily Automation Complete ---\n")
        self._update_summary()
        self._worker = None

    def _on_weekly_finished(self, result):
        self._set_buttons_enabled(True)
        self._progress.finish("Weekly automation complete")
        self._log("--- Weekly Automation Complete ---\n")
        self._update_summary()
        self._worker = None

    def _on_worker_error(self, error_msg: str):
        self._set_buttons_enabled(True)
        self._progress.finish(f"Error: {error_msg}")
        self._log(f"ERROR: {error_msg}")
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()

    def _log(self, text: str):
        self._log_output.appendPlainText(text)
        scrollbar = self._log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _update_summary(self):
        try:
            from kdp_scout.automation import DailyAutomation
            auto = DailyAutomation()
            summary = auto.get_daily_summary()

            if summary:
                lines = []
                for key, value in summary.items():
                    lines.append(f"<b>{key}:</b> {value}")
                self._summary_label.setText("<br>".join(lines))
            else:
                self._summary_label.setText("Automation completed. No summary available.")
        except Exception:
            self._summary_label.setText("Automation completed.")

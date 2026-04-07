from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QProgressBar, QLabel,
    QPlainTextEdit, QPushButton, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal


class ProgressPanel(QWidget):
    """A panel showing progress bar, status text, log output, and cancel button."""

    cancel_requested = pyqtSignal()

    def __init__(self, parent=None, show_log=True):
        super().__init__(parent)
        self._show_log = show_log
        self._setup_ui()
        self.reset()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(6)

        # Status row
        status_row = QHBoxLayout()
        status_row.setSpacing(8)

        self._status_label = QLabel("Ready")
        self._status_label.setProperty("class", "progress-status")
        status_row.addWidget(self._status_label, 1)

        self._progress_label = QLabel("")
        self._progress_label.setProperty("class", "progress-numbers")
        self._progress_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        status_row.addWidget(self._progress_label)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setProperty("class", "btn-danger")
        self._cancel_btn.setFixedWidth(80)
        self._cancel_btn.clicked.connect(self._on_cancel)
        self._cancel_btn.setVisible(False)
        status_row.addWidget(self._cancel_btn)

        # Toggle console button
        self._toggle_log_btn = QPushButton("👁")
        self._toggle_log_btn.setToolTip("Show console")
        self._toggle_log_btn.setFixedSize(32, 32)
        self._toggle_log_btn.setStyleSheet(
            "QPushButton { background: #313244; color: #cdd6f4; border: none; "
            "border-radius: 6px; font-size: 16px; }"
            "QPushButton:hover { background: #45475a; }"
        )
        self._toggle_log_btn.setVisible(False)
        self._toggle_log_btn.clicked.connect(self._toggle_log)
        status_row.addWidget(self._toggle_log_btn)

        layout.addLayout(status_row)

        # Progress bar
        self._progress_bar = QProgressBar()
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setProperty("class", "slim-progress")
        layout.addWidget(self._progress_bar)

        # Log output
        self._log_collapsed = False
        if self._show_log:
            self._log_output = QPlainTextEdit()
            self._log_output.setReadOnly(True)
            self._log_output.setMaximumHeight(150)
            self._log_output.setProperty("class", "log-output")
            self._log_output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            self._log_output.setVisible(False)
            layout.addWidget(self._log_output)
        else:
            self._log_output = None

    def set_progress(self, value: int, maximum: int = 100):
        self._progress_bar.setMaximum(maximum)
        self._progress_bar.setValue(value)
        if maximum > 0:
            self._progress_label.setText(f"{value}/{maximum}")
        else:
            self._progress_label.setText("")

    def set_status(self, text: str):
        self._status_label.setText(text)

    def append_log(self, text: str):
        if self._log_output is not None:
            if not self._log_output.isVisible() and not self._log_collapsed:
                self._log_output.setVisible(True)
            self._toggle_log_btn.setVisible(True)
            self._log_output.appendPlainText(text)
            # Auto-scroll to bottom
            scrollbar = self._log_output.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def start(self):
        self._cancel_btn.setVisible(True)
        self._cancel_btn.setEnabled(True)
        self._progress_bar.setValue(0)
        self._log_collapsed = False
        if self._log_output:
            self._log_output.clear()
            self._log_output.setVisible(True)
        self._toggle_log_btn.setVisible(True)
        self._toggle_log_btn.setToolTip("Hide console")

    def finish(self, status_text: str = "Done"):
        self._cancel_btn.setVisible(False)
        self._status_label.setText(status_text)

    def reset(self):
        self._progress_bar.setValue(0)
        self._progress_bar.setMaximum(100)
        self._progress_label.setText("")
        self._status_label.setText("Ready")
        self._cancel_btn.setVisible(False)
        self._toggle_log_btn.setVisible(False)
        self._log_collapsed = False
        if self._log_output:
            self._log_output.clear()
            self._log_output.setVisible(False)

    def _toggle_log(self):
        if self._log_output is None:
            return
        self._log_collapsed = not self._log_collapsed
        self._log_output.setVisible(not self._log_collapsed)
        self._toggle_log_btn.setToolTip(
            "Show console" if self._log_collapsed else "Hide console"
        )

    def _on_cancel(self):
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("Cancelling...")
        self._status_label.setText("Cancelling...")
        self.cancel_requested.emit()

    def set_indeterminate(self):
        self._progress_bar.setMaximum(0)
        self._progress_bar.setValue(0)
        self._progress_label.setText("")

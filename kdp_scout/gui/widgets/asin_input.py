import re
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton, QLabel
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QValidator


class ASINValidator(QValidator):
    """Validates Amazon ASIN format: 10 chars starting with B."""

    ASIN_PATTERN = re.compile(r'^B[A-Z0-9]{0,9}$', re.IGNORECASE)

    def validate(self, text: str, pos: int):
        text = text.strip().upper()
        if not text:
            return QValidator.State.Intermediate, text, pos
        if len(text) > 10:
            return QValidator.State.Invalid, text, pos
        if not text[0] == 'B':
            return QValidator.State.Invalid, text, pos
        if len(text) < 10:
            if re.match(r'^B[A-Z0-9]*$', text):
                return QValidator.State.Intermediate, text, pos
            return QValidator.State.Invalid, text, pos
        if re.match(r'^B[A-Z0-9]{9}$', text):
            return QValidator.State.Acceptable, text, pos
        return QValidator.State.Invalid, text, pos


class ASINInput(QWidget):
    """Reusable ASIN input widget with validation and Go button."""

    asin_submitted = pyqtSignal(str)

    def __init__(self, placeholder: str = "Enter ASIN (e.g., B08N5WRWNW)", parent=None):
        super().__init__(parent)
        self._setup_ui(placeholder)

    def _setup_ui(self, placeholder: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._label = QLabel("ASIN:")
        self._label.setProperty("class", "input-label")
        layout.addWidget(self._label)

        self._input = QLineEdit()
        self._input.setPlaceholderText(placeholder)
        self._input.setMaxLength(10)
        self._input.setFixedWidth(180)
        self._input.setValidator(ASINValidator())
        self._input.returnPressed.connect(self._submit)
        self._input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._input)

        self._go_btn = QPushButton("Go")
        self._go_btn.setProperty("class", "btn-primary")
        self._go_btn.setFixedWidth(60)
        self._go_btn.setEnabled(False)
        self._go_btn.clicked.connect(self._submit)
        layout.addWidget(self._go_btn)

        self._error_label = QLabel("")
        self._error_label.setProperty("class", "error-text")
        layout.addWidget(self._error_label)

        layout.addStretch()

    def _on_text_changed(self, text: str):
        text = text.strip().upper()
        is_valid = bool(re.match(r'^B[A-Z0-9]{9}$', text))
        self._go_btn.setEnabled(is_valid)
        if text and not is_valid:
            if len(text) >= 10:
                self._error_label.setText("Invalid ASIN format")
            else:
                self._error_label.setText("")
        else:
            self._error_label.setText("")

    def _submit(self):
        text = self._input.text().strip().upper()
        if re.match(r'^B[A-Z0-9]{9}$', text):
            self._error_label.setText("")
            self.asin_submitted.emit(text)
        else:
            self._error_label.setText("Please enter a valid ASIN (10 chars starting with B)")

    def get_asin(self) -> str:
        return self._input.text().strip().upper()

    def clear(self):
        self._input.clear()
        self._error_label.setText("")

    def set_enabled(self, enabled: bool):
        self._input.setEnabled(enabled)
        self._go_btn.setEnabled(enabled and bool(re.match(
            r'^B[A-Z0-9]{9}$', self._input.text().strip().upper()
        )))

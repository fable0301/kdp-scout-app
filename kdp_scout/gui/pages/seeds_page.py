from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QComboBox, QLabel, QMessageBox
)
from PyQt6.QtCore import Qt

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.search_history import SearchHistory


SEED_COLUMNS = ["keyword", "department", "times_mined", "last_mined", "added"]

SEED_DISPLAY_NAMES = {
    "keyword": "Keyword",
    "department": "Department",
    "times_mined": "Times Mined",
    "last_mined": "Last Mined",
    "added": "Added",
}


class SeedsPage(QWidget):
    """Page for managing seed keywords."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("<h2>🌱 Seed Keywords</h2>")
        layout.addWidget(header)

        # Add seed toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._seed_input = QLineEdit()
        self._seed_input.setPlaceholderText("Enter seed keyword...")
        self._seed_input.returnPressed.connect(self._on_add)
        toolbar.addWidget(self._seed_input, 1)

        dept_label = QLabel("Department:")
        toolbar.addWidget(dept_label)

        self._dept_combo = QComboBox()
        self._dept_combo.setMinimumWidth(160)
        self._dept_combo.addItems([
            "digital-text",
            "stripbooks",
            "audible",
            "books",
        ])
        toolbar.addWidget(self._dept_combo)

        self._add_btn = QPushButton("➕ Add")
        self._add_btn.setProperty("class", "btn-primary")
        self._add_btn.clicked.connect(self._on_add)
        toolbar.addWidget(self._add_btn)

        self._delete_btn = QPushButton("🗑 Delete")
        self._delete_btn.setProperty("class", "btn-danger")
        self._delete_btn.clicked.connect(self._on_delete)
        toolbar.addWidget(self._delete_btn)

        self._refresh_btn = QPushButton("🔄")
        self._refresh_btn.setFixedWidth(40)
        self._refresh_btn.clicked.connect(self._load_data)
        toolbar.addWidget(self._refresh_btn)

        layout.addLayout(toolbar)

        # Info
        info = QLabel(
            "Seed keywords are used as starting points for keyword mining. "
            "Add seeds here and use the Keywords page to mine from them."
        )
        info.setWordWrap(True)
        info.setProperty("class", "info-text")
        layout.addWidget(info)

        # Data table
        self._table = DataTable()
        layout.addWidget(self._table, 1)

    def _load_data(self):
        try:
            from kdp_scout.seeds import SeedManager
            manager = SeedManager()
            seeds = manager.list_seeds()

            if seeds:
                self._table.load_data(seeds, SEED_COLUMNS, SEED_DISPLAY_NAMES)
            else:
                self._table.clear()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load seeds: {e}")

    def _on_add(self):
        keyword = self._seed_input.text().strip()
        if not keyword:
            QMessageBox.warning(self, "Error", "Please enter a seed keyword.")
            return

        department = self._dept_combo.currentText()

        try:
            from kdp_scout.seeds import SeedManager
            manager = SeedManager()
            manager.add_seed(keyword, department=department)
            self._seed_input.clear()
            self._load_data()
            SearchHistory.instance().log(
                tool="Seeds", action="Add Seed",
                query=f"{keyword} ({department})",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add seed: {e}")

    def _on_delete(self):
        row_data = self._table.get_selected_row()
        if not row_data:
            QMessageBox.information(self, "Delete", "Please select a seed to delete.")
            return

        keyword = row_data.get("keyword", "")

        reply = QMessageBox.question(
            self, "Delete Seed",
            f"Delete seed '{keyword}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                from kdp_scout.seeds import SeedManager
                manager = SeedManager()
                manager.remove_seed(keyword)
                self._load_data()
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete seed: {e}")

    def focus_search(self):
        self._table.focus_search()

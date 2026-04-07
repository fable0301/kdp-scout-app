"""History page — browse, review, and export all past searches."""

import csv
import json
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QTextEdit, QFileDialog, QMessageBox, QComboBox, QFrame,
    QAbstractItemView, QMenu, QApplication,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction
import webbrowser
import urllib.parse

from kdp_scout.gui.search_history import SearchHistory


# Tool icons for visual clarity
TOOL_ICONS = {
    "Keywords": "🔍",
    "Trending": "📈",
    "Competitors": "🏷",
    "Ads": "📊",
    "Seeds": "🌱",
    "ASIN Lookup": "🔎",
    "Automation": "🤖",
    "Google Trending": "📈",
    "Google Keywords": "🔍",
    "Google Books": "📚",
}


class HistoryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history = SearchHistory.instance()
        self._current_entry_id = None
        self._current_results = None
        self._setup_ui()
        self._load_history()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header = QHBoxLayout()
        title = QLabel("Search History")
        title.setProperty("class", "page-title")
        header.addWidget(title)
        header.addStretch()

        # Filter combo
        self._filter_combo = QComboBox()
        self._filter_combo.addItem("All Tools")
        for tool in ["Keywords", "Trending", "Competitors", "Ads", "Seeds", "ASIN Lookup",
                     "Google Trending", "Google Keywords", "Google Books"]:
            self._filter_combo.addItem(f"{TOOL_ICONS.get(tool, '')} {tool}", tool)
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)
        self._filter_combo.setMinimumWidth(160)
        header.addWidget(QLabel("Filter:"))
        header.addWidget(self._filter_combo)

        # Refresh
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setProperty("class", "secondary-btn")
        refresh_btn.clicked.connect(self._load_history)
        header.addWidget(refresh_btn)

        # Clear all
        clear_btn = QPushButton("Clear All")
        clear_btn.setProperty("class", "danger-btn")
        clear_btn.clicked.connect(self._on_clear_all)
        header.addWidget(clear_btn)

        layout.addLayout(header)

        # Splitter: history list (top) + detail view (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- History table ---
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Date/Time", "Tool", "Action", "Query", "Results", "Notes"
        ])
        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(True)
        hdr.setSectionsMovable(True)
        for col in range(6):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        hdr.resizeSection(0, 150)
        hdr.resizeSection(1, 100)
        hdr.resizeSection(2, 100)
        hdr.resizeSection(3, 250)
        hdr.resizeSection(4, 70)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_table_context_menu)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._table)

        # --- Detail panel ---
        detail_frame = QFrame()
        detail_layout = QVBoxLayout(detail_frame)
        detail_layout.setContentsMargins(0, 8, 0, 0)

        detail_header = QHBoxLayout()
        self._detail_label = QLabel("Select a search to view details")
        self._detail_label.setProperty("class", "section-title")
        detail_header.addWidget(self._detail_label)
        detail_header.addStretch()

        # Export buttons
        self._export_csv_btn = QPushButton("Export CSV")
        self._export_csv_btn.setProperty("class", "primary-btn")
        self._export_csv_btn.setEnabled(False)
        self._export_csv_btn.clicked.connect(self._on_export_csv)
        detail_header.addWidget(self._export_csv_btn)

        self._export_json_btn = QPushButton("Export JSON")
        self._export_json_btn.setProperty("class", "secondary-btn")
        self._export_json_btn.setEnabled(False)
        self._export_json_btn.clicked.connect(self._on_export_json)
        detail_header.addWidget(self._export_json_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setProperty("class", "danger-btn")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_entry)
        detail_header.addWidget(self._delete_btn)

        detail_layout.addLayout(detail_header)

        # Results preview table
        self._detail_table = QTableWidget()
        self._detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setAlternatingRowColors(True)
        self._detail_table.horizontalHeader().setSectionsMovable(True)
        self._detail_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._detail_table.customContextMenuRequested.connect(self._show_detail_context_menu)
        detail_layout.addWidget(self._detail_table)

        splitter.addWidget(detail_frame)
        splitter.setSizes([300, 400])

        layout.addWidget(splitter, 1)

    def _load_history(self):
        """Load all history entries into the table."""
        self._entries = self._history.get_all(limit=1000)
        self._display_entries(self._entries)

    def _display_entries(self, entries: list[dict]):
        self._table.setRowCount(len(entries))
        for row_idx, entry in enumerate(entries):
            # Date/Time
            ts = entry.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts)
                display_ts = dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                display_ts = ts

            item_ts = QTableWidgetItem(display_ts)
            item_ts.setData(Qt.ItemDataRole.UserRole, entry.get("id"))
            self._table.setItem(row_idx, 0, item_ts)

            # Tool
            tool = entry.get("tool", "")
            icon = TOOL_ICONS.get(tool, "")
            self._table.setItem(row_idx, 1, QTableWidgetItem(f"{icon} {tool}"))

            # Action
            self._table.setItem(row_idx, 2, QTableWidgetItem(entry.get("action", "")))

            # Query
            self._table.setItem(row_idx, 3, QTableWidgetItem(entry.get("query", "")))

            # Result count
            count = entry.get("result_count", 0)
            self._table.setItem(row_idx, 4, QTableWidgetItem(str(count)))

            # Notes
            self._table.setItem(row_idx, 5, QTableWidgetItem(entry.get("notes", "")))

    def _apply_filter(self):
        tool_filter = self._filter_combo.currentData()
        if tool_filter:
            filtered = [e for e in self._entries if e.get("tool") == tool_filter]
        else:
            filtered = self._entries
        self._display_entries(filtered)

    def _on_selection_changed(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._detail_label.setText("Select a search to view details")
            self._detail_table.setRowCount(0)
            self._detail_table.setColumnCount(0)
            self._export_csv_btn.setEnabled(False)
            self._export_json_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._current_entry_id = None
            self._current_results = None
            return

        row_idx = rows[0].row()
        item = self._table.item(row_idx, 0)
        if not item:
            return

        entry_id = item.data(Qt.ItemDataRole.UserRole)
        self._current_entry_id = entry_id
        self._delete_btn.setEnabled(True)

        # Load results
        results = self._history.get_results(entry_id)
        self._current_results = results

        entry = self._history.get_entry(entry_id)
        tool = entry.get("tool", "") if entry else ""
        action = entry.get("action", "") if entry else ""
        query = entry.get("query", "") if entry else ""
        count = entry.get("result_count", 0) if entry else 0

        self._detail_label.setText(
            f"{TOOL_ICONS.get(tool, '')} {tool} > {action} — \"{query}\" ({count} results)"
        )

        if results and isinstance(results, list) and len(results) > 0:
            self._export_csv_btn.setEnabled(True)
            self._export_json_btn.setEnabled(True)
            self._populate_detail_table(results)
        else:
            self._export_csv_btn.setEnabled(False)
            self._export_json_btn.setEnabled(False)
            self._detail_table.setRowCount(0)
            self._detail_table.setColumnCount(0)

    def _populate_detail_table(self, results: list):
        """Show results in the detail table."""
        if not results:
            return

        # Determine columns
        first = results[0]
        if isinstance(first, dict):
            columns = list(first.keys())
        elif isinstance(first, (list, tuple)):
            columns = [f"Col {i+1}" for i in range(len(first))]
        else:
            columns = ["Value"]
            results = [{"Value": str(r)} for r in results]

        self._detail_table.setColumnCount(len(columns))
        self._detail_table.setHorizontalHeaderLabels(columns)
        self._detail_table.setRowCount(len(results))

        for row_idx, row_data in enumerate(results):
            if isinstance(row_data, dict):
                for col_idx, col in enumerate(columns):
                    val = row_data.get(col, "")
                    self._detail_table.setItem(row_idx, col_idx, QTableWidgetItem(str(val) if val is not None else ""))
            elif isinstance(row_data, (list, tuple)):
                for col_idx, val in enumerate(row_data):
                    self._detail_table.setItem(row_idx, col_idx, QTableWidgetItem(str(val) if val is not None else ""))

        # Auto-resize then unlock for drag
        dhdr = self._detail_table.horizontalHeader()
        for i in range(len(columns)):
            dhdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        dhdr.setStretchLastSection(True)
        def _unlock_detail():
            for i in range(len(columns)):
                if i < len(columns) - 1:
                    dhdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                else:
                    dhdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        QTimer.singleShot(100, _unlock_detail)

    def _on_export_csv(self):
        if not self._current_results:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export History as CSV", "", "CSV Files (*.csv)"
        )
        if not filepath:
            return

        try:
            data = self._current_results
            first = data[0]
            if isinstance(first, dict):
                fieldnames = list(first.keys())
                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(data)
            else:
                with open(filepath, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    for row in data:
                        if isinstance(row, (list, tuple)):
                            writer.writerow(row)
                        else:
                            writer.writerow([row])

            QMessageBox.information(self, "Export", f"Exported {len(data)} rows to:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _on_export_json(self):
        if not self._current_results:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export History as JSON", "", "JSON Files (*.json)"
        )
        if not filepath:
            return

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self._current_results, f, indent=2, default=str, ensure_ascii=False)
            QMessageBox.information(
                self, "Export", f"Exported {len(self._current_results)} entries to:\n{filepath}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Export Error", str(e))

    def _on_delete_entry(self):
        if self._current_entry_id is None:
            return

        reply = QMessageBox.question(
            self, "Delete Entry",
            "Delete this history entry?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._history.delete_entry(self._current_entry_id)
            self._current_entry_id = None
            self._current_results = None
            self._load_history()

    def _show_table_context_menu(self, pos):
        menu = QMenu(self)
        copy_cell = QAction("Copy Cell", self)
        copy_cell.triggered.connect(lambda: self._copy_cell(self._table))
        menu.addAction(copy_cell)
        copy_row = QAction("Copy Row", self)
        copy_row.triggered.connect(lambda: self._copy_row(self._table))
        menu.addAction(copy_row)
        menu.addSeparator()
        search_web = QAction("🔍 Search on the Web", self)
        search_web.triggered.connect(lambda: self._search_on_web(self._table))
        menu.addAction(search_web)
        export_csv = QAction("Export CSV...", self)
        export_csv.triggered.connect(self._on_export_csv)
        menu.addAction(export_csv)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _show_detail_context_menu(self, pos):
        menu = QMenu(self)
        copy_cell = QAction("Copy Cell", self)
        copy_cell.triggered.connect(lambda: self._copy_cell(self._detail_table))
        menu.addAction(copy_cell)
        copy_row = QAction("Copy Row", self)
        copy_row.triggered.connect(lambda: self._copy_row(self._detail_table))
        menu.addAction(copy_row)
        menu.addSeparator()
        search_web = QAction("🔍 Search on the Web", self)
        search_web.triggered.connect(lambda: self._search_on_web(self._detail_table))
        menu.addAction(search_web)
        export_csv = QAction("Export CSV...", self)
        export_csv.triggered.connect(self._on_export_csv)
        menu.addAction(export_csv)
        menu.exec(self._detail_table.viewport().mapToGlobal(pos))

    def _copy_cell(self, table):
        item = table.currentItem()
        if item:
            QApplication.clipboard().setText(item.text())

    def _copy_row(self, table):
        row = table.currentRow()
        if row < 0:
            return
        vals = []
        for col in range(table.columnCount()):
            item = table.item(row, col)
            vals.append(item.text() if item else "")
        QApplication.clipboard().setText("\t".join(vals))

    def _search_on_web(self, table):
        item = table.currentItem()
        if item and item.text().strip():
            query = urllib.parse.quote_plus(item.text().strip())
            webbrowser.open(f"https://www.google.com/search?q={query}")

    def _on_clear_all(self):
        reply = QMessageBox.warning(
            self, "Clear All History",
            "This will permanently delete ALL search history.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._history.clear_all()
            self._load_history()
            self._detail_table.setRowCount(0)
            self._detail_table.setColumnCount(0)
            self._detail_label.setText("History cleared")

import csv
import io
from typing import List, Dict, Any, Optional

from PyQt6.QtWidgets import (
    QTableView, QHeaderView, QMenu, QApplication, QFileDialog, QWidget,
    QVBoxLayout, QHBoxLayout, QLineEdit, QLabel, QPushButton, QAbstractItemView
)
from PyQt6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QSortFilterProxyModel,
    QVariant, pyqtSignal
)
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
import webbrowser
import urllib.parse


class DictTableModel(QAbstractTableModel):
    """Table model backed by a list of dicts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[Dict[str, Any]] = []
        self._columns: List[str] = []
        self._display_names: Dict[str, str] = {}

    def load_data(self, data: List[Dict[str, Any]], columns: Optional[List[str]] = None,
                  display_names: Optional[Dict[str, str]] = None):
        self.beginResetModel()
        # Convert sqlite3.Row or any non-dict mapping to plain dicts
        self._data = [dict(row) if not isinstance(row, dict) else row for row in (data or [])]
        if columns:
            self._columns = columns
        elif data:
            self._columns = list(data[0].keys())
        else:
            self._columns = []
        self._display_names = display_names or {}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self._data)

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            row = self._data[index.row()]
            col = self._columns[index.column()]
            value = row.get(col, "")
            if isinstance(value, float):
                return f"{value:,.2f}"
            if value is None:
                return ""
            return str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            row = self._data[index.row()]
            col = self._columns[index.column()]
            value = row.get(col, "")
            if isinstance(value, (int, float)):
                return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.UserRole:
            row = self._data[index.row()]
            col = self._columns[index.column()]
            return row.get(col, "")
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            if orientation == Qt.Orientation.Horizontal and section < len(self._columns):
                col = self._columns[section]
                return self._display_names.get(col, col.replace("_", " ").title())
            if orientation == Qt.Orientation.Vertical:
                return str(section + 1)
        return None

    def get_row_data(self, row: int) -> Optional[Dict[str, Any]]:
        if 0 <= row < len(self._data):
            return self._data[row]
        return None

    def get_all_data(self) -> List[Dict[str, Any]]:
        return self._data

    def get_columns(self) -> List[str]:
        return self._columns


class DataTable(QWidget):
    """Reusable data table with search filtering, sorting, and export."""

    row_double_clicked = pyqtSignal(dict)
    selection_changed = pyqtSignal(dict)
    count_changed = pyqtSignal(int, int)   # (visible, total)

    def __init__(self, parent=None, show_filter_bar=True):
        super().__init__(parent)
        self._show_filter_bar = show_filter_bar
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Filter bar — wrapped in a QWidget so it can be hidden
        self._filter_bar_widget = QWidget()
        filter_bar = QHBoxLayout(self._filter_bar_widget)
        filter_bar.setContentsMargins(0, 0, 0, 0)
        filter_bar.setSpacing(8)

        self._filter_input = QLineEdit()
        self._filter_input.setPlaceholderText("🔍 Filter rows...")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._filter_input, 1)

        self._count_label = QLabel("0 rows")
        self._count_label.setProperty("class", "table-count")
        filter_bar.addWidget(self._count_label)

        if not self._show_filter_bar:
            self._filter_bar_widget.hide()
        layout.addWidget(self._filter_bar_widget)

        # Table model
        self._model = DictTableModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterKeyColumn(-1)  # search all columns
        self._proxy.setSortRole(Qt.ItemDataRole.UserRole)

        # Table view
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.doubleClicked.connect(self._on_double_click)
        self._table.setWordWrap(False)

        # Header
        header = self._table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionsMovable(True)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        self._table.verticalHeader().setDefaultSectionSize(32)
        self._table.verticalHeader().setVisible(False)

        # Selection
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        layout.addWidget(self._table, 1)

    def load_data(self, data: List[Dict[str, Any]], columns: Optional[List[str]] = None,
                  display_names: Optional[Dict[str, str]] = None):
        self._model.load_data(data, columns, display_names)
        self._update_count()
        # Auto-resize columns to content, then switch to Interactive for drag resize
        header = self._table.horizontalHeader()
        for i in range(self._model.columnCount()):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        if self._model.columnCount() > 0:
            header.setSectionResizeMode(
                self._model.columnCount() - 1, QHeaderView.ResizeMode.Stretch
            )
        # Allow user to drag-resize after initial fit
        from PyQt6.QtCore import QTimer
        def _unlock_resize():
            for i in range(self._model.columnCount()):
                if i < self._model.columnCount() - 1:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                else:
                    header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        QTimer.singleShot(100, _unlock_resize)

    def _apply_filter(self, text: str):
        self._proxy.setFilterFixedString(text)
        self._update_count()

    def _update_count(self):
        visible = self._proxy.rowCount()
        total = self._model.rowCount()
        if visible == total:
            self._count_label.setText(f"{total} rows")
        else:
            self._count_label.setText(f"{visible} / {total} rows")
        self.count_changed.emit(visible, total)

    def _on_double_click(self, index: QModelIndex):
        source_index = self._proxy.mapToSource(index)
        row_data = self._model.get_row_data(source_index.row())
        if row_data:
            self.row_double_clicked.emit(row_data)

    def _on_selection_changed(self, selected, deselected):
        indexes = self._table.selectionModel().selectedRows()
        if indexes:
            source_index = self._proxy.mapToSource(indexes[0])
            row_data = self._model.get_row_data(source_index.row())
            if row_data:
                self.selection_changed.emit(row_data)

    def get_selected_row(self) -> Optional[Dict[str, Any]]:
        indexes = self._table.selectionModel().selectedRows()
        if indexes:
            source_index = self._proxy.mapToSource(indexes[0])
            return self._model.get_row_data(source_index.row())
        return None

    def _show_context_menu(self, pos):
        menu = QMenu(self)

        copy_action = QAction("Copy Cell", self)
        copy_action.triggered.connect(self._copy_cell)
        menu.addAction(copy_action)

        copy_row_action = QAction("Copy Row", self)
        copy_row_action.triggered.connect(self._copy_row)
        menu.addAction(copy_row_action)

        menu.addSeparator()

        search_web_action = QAction("🔍 Search on the Web", self)
        search_web_action.triggered.connect(self._search_on_web)
        menu.addAction(search_web_action)

        export_action = QAction("Export Visible as CSV...", self)
        export_action.triggered.connect(self.export_csv)
        menu.addAction(export_action)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_cell(self):
        index = self._table.currentIndex()
        if index.isValid():
            value = self._proxy.data(index, Qt.ItemDataRole.DisplayRole)
            if value:
                QApplication.clipboard().setText(str(value))

    def _copy_row(self):
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            return
        source_index = self._proxy.mapToSource(indexes[0])
        row_data = self._model.get_row_data(source_index.row())
        if row_data:
            text = "\t".join(str(v) for v in row_data.values())
            QApplication.clipboard().setText(text)

    def _search_on_web(self):
        index = self._table.currentIndex()
        if index.isValid():
            value = self._proxy.data(index, Qt.ItemDataRole.DisplayRole)
            if value:
                query = urllib.parse.quote_plus(str(value))
                webbrowser.open(f"https://www.google.com/search?q={query}")

    def export_csv(self, filepath: Optional[str] = None):
        if not filepath:
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Export CSV", "export.csv", "CSV Files (*.csv)"
            )
        if not filepath:
            return

        columns = self._model.get_columns()
        display_names = {
            col: self._model.headerData(i, Qt.Orientation.Horizontal)
            for i, col in enumerate(columns)
        }

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            # Header
            writer.writerow([display_names.get(c, c) for c in columns])
            # Visible rows only
            for row in range(self._proxy.rowCount()):
                source_row = self._proxy.mapToSource(self._proxy.index(row, 0)).row()
                row_data = self._model.get_row_data(source_row)
                if row_data:
                    writer.writerow([row_data.get(c, "") for c in columns])

        return filepath

    def get_visible_data(self) -> List[Dict[str, Any]]:
        result = []
        for row in range(self._proxy.rowCount()):
            source_row = self._proxy.mapToSource(self._proxy.index(row, 0)).row()
            row_data = self._model.get_row_data(source_row)
            if row_data:
                result.append(row_data)
        return result

    def focus_search(self):
        self._filter_input.setFocus()
        self._filter_input.selectAll()

    def clear(self):
        self._model.load_data([])
        self._update_count()

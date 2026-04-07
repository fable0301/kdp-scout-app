from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QComboBox,
    QLabel, QFileDialog, QTextEdit, QMessageBox, QApplication, QCheckBox,
    QGroupBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal

from kdp_scout.gui.widgets.data_table import DataTable
from kdp_scout.gui.widgets.progress_panel import ProgressPanel
from kdp_scout.gui.workers.mine_worker import (
    MineWorker, MultiMarketplaceMineWorker, ScoreWorker, CompetitionProbeWorker,
    MergeEnrichWorker,
)
from kdp_scout.gui.workers.export_worker import ExportCSVWorker, KDPSlotsWorker
from kdp_scout.gui.search_history import SearchHistory


KEYWORD_COLUMNS = [
    "row_num", "keyword", "score",
    "multi_source", "trend", "google_suggest", "bsr_top1",
    "autocomplete_position",
    "competition_count", "avg_bsr_top_results",
    "ku_ratio", "median_reviews",
    "impressions", "clicks", "orders", "source",
]

KEYWORD_DISPLAY_NAMES = {
    "row_num": "#",
    "keyword": "Keyword",
    "score": "Score",
    "multi_source": "🔗 Sources",
    "trend": "📈 Trend",
    "google_suggest": "G.Suggest",
    "bsr_top1": "BSR #1",
    "autocomplete_position": "AC Pos",
    "competition_count": "Competition",
    "avg_bsr_top_results": "Avg BSR Top10",
    "ku_ratio": "KU Ratio",
    "median_reviews": "Median Reviews",
    "impressions": "Impressions",
    "clicks": "Clicks",
    "orders": "Orders",
    "source": "Source",
}

MARKETPLACES = ["us", "uk", "de", "fr", "ca", "au", "jp", "es", "it"]


class MineDialog(QDialog):
    """Dialog for configuring keyword mining parameters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mine Keywords")
        self.setMinimumWidth(440)

        layout = QFormLayout(self)

        self.seed_input = QLineEdit()
        self.seed_input.setPlaceholderText("e.g., coloring book for adults")
        layout.addRow("Seed Keyword:", self.seed_input)

        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 5)
        self.depth_spin.setValue(2)
        self.depth_spin.setToolTip("Higher depth = more keywords but slower")
        layout.addRow("Depth:", self.depth_spin)

        self.department_combo = QComboBox()
        self.department_combo.addItems([
            "digital-text", "stripbooks", "audible", "books",
        ])
        layout.addRow("Department:", self.department_combo)

        # Marketplace selector
        self.multi_check = QCheckBox("Mine across multiple marketplaces")
        self.multi_check.setToolTip("Mine the same seed on US, UK, DE, CA simultaneously")
        self.multi_check.toggled.connect(self._on_multi_toggled)
        layout.addRow("", self.multi_check)

        # Single marketplace combo (visible when multi unchecked)
        self.marketplace_combo = QComboBox()
        self.marketplace_combo.addItems(MARKETPLACES)
        self._mp_single_label = QLabel("Marketplace:")
        layout.addRow(self._mp_single_label, self.marketplace_combo)

        # Multi marketplace checkboxes (visible when multi checked)
        self._mp_group = QGroupBox("Select Marketplaces")
        mp_layout = QHBoxLayout(self._mp_group)
        self._mp_checks = {}
        defaults = {"us", "uk", "de", "ca"}
        for mp in MARKETPLACES[:6]:
            cb = QCheckBox(mp.upper())
            cb.setChecked(mp in defaults)
            self._mp_checks[mp] = cb
            mp_layout.addWidget(cb)
        self._mp_group.setVisible(False)
        layout.addRow(self._mp_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _on_multi_toggled(self, checked):
        self.marketplace_combo.setVisible(not checked)
        self._mp_single_label.setVisible(not checked)
        self._mp_group.setVisible(checked)

    def get_values(self):
        multi = self.multi_check.isChecked()
        if multi:
            marketplaces = [mp for mp, cb in self._mp_checks.items() if cb.isChecked()]
            if not marketplaces:
                marketplaces = ["us"]
        else:
            marketplaces = [self.marketplace_combo.currentText()]

        return {
            "seed": self.seed_input.text().strip(),
            "depth": self.depth_spin.value(),
            "department": self.department_combo.currentText(),
            "marketplace": marketplaces[0],
            "multi": multi,
            "marketplaces": marketplaces,
        }


class MergeEnrichDialog(QDialog):
    """Dialog for configuring cross-source keyword fusion."""

    def __init__(self, seed_hint="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔗 Merge & Enrich — Cross-Source Fusion")
        self.setMinimumWidth(480)

        layout = QFormLayout(self)

        info = QLabel(
            "Cross-reference your mined keywords with <b>Google Suggest</b>, "
            "<b>Google Trends</b> (12-month direction), and <b>Amazon BSR #1</b> "
            "to identify multi-source demand signals.\n\n"
            "A keyword confirmed by 3–4 sources is a much stronger signal "
            "than one from a single source."
        )
        info.setWordWrap(True)
        info.setProperty("class", "info-text")
        layout.addRow(info)

        self.seed_input = QLineEdit(seed_hint)
        self.seed_input.setPlaceholderText("e.g., coloring book for adults")
        self.seed_input.setToolTip(
            "The seed used for mining. Enables efficient Google Suggest "
            "alphabet crawl (~60 requests) instead of per-stem queries."
        )
        layout.addRow("Seed (recommended):", self.seed_input)

        self.trends_spin = QSpinBox()
        self.trends_spin.setRange(0, 100)
        self.trends_spin.setValue(20)
        self.trends_spin.setToolTip("Max keywords to query on Google Trends (batches of 5)")
        layout.addRow("Max Trends keywords:", self.trends_spin)

        self.bsr_spin = QSpinBox()
        self.bsr_spin.setRange(0, 100)
        self.bsr_spin.setValue(30)
        self.bsr_spin.setToolTip("Max keywords to fetch Amazon BSR #1 for (1 request each)")
        layout.addRow("Max BSR probes:", self.bsr_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def get_values(self):
        return {
            "seed": self.seed_input.text().strip(),
            "max_trends": self.trends_spin.value(),
            "max_bsr": self.bsr_spin.value(),
        }


class ScoreBreakdownDialog(QDialog):
    """Dialog showing detailed score breakdown for a keyword."""

    def __init__(self, keyword_data: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Score Breakdown: {keyword_data.get('keyword', '')}")
        self.setMinimumSize(540, 460)

        layout = QVBoxLayout(self)

        title = QLabel(f"<h2>{keyword_data.get('keyword', '')}</h2>")
        layout.addWidget(title)

        score = keyword_data.get('score', 'N/A')
        score_label = QLabel(f"<h3>Overall Score: {score}</h3>")
        score_label.setProperty("class", "score-highlight")
        layout.addWidget(score_label)

        details = QTextEdit()
        details.setReadOnly(True)

        field_labels = {
            "autocomplete_position": "Autocomplete Position",
            "competition_count": "Competition Count",
            "avg_bsr_top_results": "Avg BSR Top 10",
            "ku_ratio": "KU Ratio (top 10)",
            "median_reviews": "Median Reviews (top 10)",
            "impressions": "Impressions",
            "clicks": "Clicks",
            "orders": "Orders",
            "source": "Source",
            "search_volume": "Search Volume",
            "cpc": "Cost Per Click",
        }

        info_lines = []
        for key, label in field_labels.items():
            value = keyword_data.get(key)
            if value is not None:
                if key == "ku_ratio" and isinstance(value, (int, float)):
                    value = f"{value * 100:.0f}%"
                info_lines.append(f"<b>{label}:</b> {value}")

        details.setHtml(
            "<br>".join(info_lines) if info_lines else "No detailed data available"
        )
        layout.addWidget(details)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)


class KDPSlotsDialog(QDialog):
    """Dialog showing KDP backend keyword slot preview."""

    def __init__(self, slots: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KDP Backend Keyword Slots")
        self.setMinimumSize(600, 500)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Amazon KDP allows 7 keyword slots (each up to 50 characters) "
            "for book discoverability. These are optimized based on your keyword scores."
        )
        info.setWordWrap(True)
        info.setProperty("class", "info-text")
        layout.addWidget(info)

        if isinstance(slots, list):
            for i, slot in enumerate(slots):
                slot_text = slot if isinstance(slot, str) else str(slot)
                slot_frame = QWidget()
                slot_layout = QHBoxLayout(slot_frame)
                slot_layout.setContentsMargins(0, 4, 0, 4)

                label = QLabel(f"<b>Slot {i + 1}:</b>")
                label.setFixedWidth(60)
                slot_layout.addWidget(label)

                value = QLineEdit(slot_text)
                value.setReadOnly(True)
                slot_layout.addWidget(value)

                chars = QLabel(f"{len(slot_text)}/50")
                chars.setFixedWidth(50)
                slot_layout.addWidget(chars)

                layout.addWidget(slot_frame)

            for i in range(len(slots), 7):
                slot_frame = QWidget()
                slot_layout = QHBoxLayout(slot_frame)
                slot_layout.setContentsMargins(0, 4, 0, 4)

                label = QLabel(f"<b>Slot {i + 1}:</b>")
                label.setFixedWidth(60)
                slot_layout.addWidget(label)

                value = QLineEdit("")
                value.setReadOnly(True)
                value.setPlaceholderText("(empty)")
                slot_layout.addWidget(value)

                chars = QLabel("0/50")
                chars.setFixedWidth(50)
                slot_layout.addWidget(chars)

                layout.addWidget(slot_frame)
        else:
            layout.addWidget(QLabel("No slot data available"))

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        copy_btn = QPushButton("Copy All to Clipboard")
        copy_btn.setProperty("class", "btn-primary")
        copy_btn.clicked.connect(lambda: self._copy_all(slots))
        btn_row.addWidget(copy_btn)

        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _copy_all(self, slots):
        if isinstance(slots, list):
            text = "\n".join(s if isinstance(s, str) else str(s) for s in slots)
            QApplication.clipboard().setText(text)


class KeywordsPage(QWidget):
    """Main keywords page with mining, scoring, competition probing, and export."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self._enrichment = {}          # keyword_lower -> {google_suggest, trend, bsr_top1, multi_source}
        self._last_mine_seed = ""
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        header = QLabel("<h2>🔍 Keywords</h2>")
        layout.addWidget(header)

        # ── Row 1: Action buttons ─────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self._mine_btn = QPushButton("⛏  Mine Keywords")
        self._mine_btn.setProperty("class", "btn-primary")
        self._mine_btn.setToolTip("Mine new keywords from a seed (single or multi-marketplace)")
        self._mine_btn.setMinimumWidth(280)
        self._mine_btn.setMaximumWidth(400)
        self._mine_btn.setMinimumHeight(58)
        font = self._mine_btn.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        self._mine_btn.setFont(font)
        self._mine_btn.clicked.connect(self._on_mine)
        toolbar.addWidget(self._mine_btn)

        self._probe_btn = QPushButton("🔎 Probe & Score")
        self._probe_btn.setToolTip(
            "Probe Amazon search results to enrich keywords with real competition data\n"
            "(avg BSR top 10, KU ratio, median reviews), then auto-score all keywords."
        )
        self._probe_btn.clicked.connect(self._on_probe)
        toolbar.addWidget(self._probe_btn)

        self._merge_btn = QPushButton("🔗 Merge && Enrich")
        self._merge_btn.setToolTip(
            "Cross-reference keywords with Google Suggest, Google Trends,\n"
            "and Amazon BSR to identify multi-source demand signals."
        )
        self._merge_btn.clicked.connect(self._on_merge)
        toolbar.addWidget(self._merge_btn)

        self._export_btn = QPushButton("📄 Export CSV")
        self._export_btn.setToolTip("Export keywords to CSV")
        self._export_btn.clicked.connect(self._on_export_csv)
        toolbar.addWidget(self._export_btn)

        self._slots_btn = QPushButton("🏷 KDP Slots")
        self._slots_btn.setToolTip("Generate KDP backend keyword slots")
        self._slots_btn.clicked.connect(self._on_kdp_slots)
        toolbar.addWidget(self._slots_btn)

        self._refresh_btn = QPushButton("🔄")
        self._refresh_btn.setToolTip("Refresh data")
        self._refresh_btn.setFixedWidth(40)
        self._refresh_btn.clicked.connect(self._load_data)
        toolbar.addWidget(self._refresh_btn)

        layout.addLayout(toolbar)

        # ── Row 2: Filters (keyword search + marketplace + row count) ────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("🔍 Filter keywords...")
        self._search_input.setClearButtonEnabled(True)
        filter_row.addWidget(self._search_input, 2)

        mp_label = QLabel("Marketplace:")
        filter_row.addWidget(mp_label)

        self._mp_filter = QComboBox()
        self._mp_filter.addItem("All", "all")
        for mp in MARKETPLACES:
            self._mp_filter.addItem(mp.upper(), mp)
        self._mp_filter.setFixedWidth(100)
        self._mp_filter.currentIndexChanged.connect(self._load_data)
        filter_row.addWidget(self._mp_filter)

        self._row_count_label = QLabel("")
        self._row_count_label.setProperty("class", "info-text")
        filter_row.addWidget(self._row_count_label)

        layout.addLayout(filter_row)

        # Data table — built-in filter bar hidden (our filter_row replaces it)
        self._table = DataTable(show_filter_bar=False)
        self._table.row_double_clicked.connect(self._on_row_double_click)
        # Our search input drives DataTable's filter
        self._search_input.textChanged.connect(self._table._apply_filter)
        # Update row count label whenever the filter updates
        self._table.count_changed.connect(
            lambda vis, tot: self._row_count_label.setText(
                f"{tot} rows" if vis == tot else f"{vis} / {tot} rows"
            )
        )
        layout.addWidget(self._table, 1)

        # Progress panel
        self._progress = ProgressPanel(show_log=True)
        self._progress.cancel_requested.connect(self._on_cancel)
        layout.addWidget(self._progress)

    def _load_data(self):
        try:
            from kdp_scout.db import KeywordRepository, init_db
            init_db()
            repo = KeywordRepository()
            keywords = repo.get_keywords_with_latest_metrics(limit=10000)
            repo.close()

            keywords = [dict(kw) if not isinstance(kw, dict) else kw for kw in keywords]
            for i, kw in enumerate(keywords):
                kw["row_num"] = i + 1
                if kw.get("ku_ratio") is not None:
                    kw["ku_ratio"] = f"{kw['ku_ratio'] * 100:.0f}%"
                # Merge enrichment overlay
                enrich = self._enrichment.get(
                    (kw.get("keyword") or "").lower().strip(), {}
                )
                if enrich:
                    kw["google_suggest"] = "✓" if enrich.get("google_suggest") else ""
                    kw["trend"] = enrich.get("trend", "")
                    bsr1 = enrich.get("bsr_top1")
                    kw["bsr_top1"] = f"{bsr1:,}" if bsr1 else ""
                    kw["multi_source"] = enrich.get("multi_source", 1)
                else:
                    kw.setdefault("google_suggest", "")
                    kw.setdefault("trend", "")
                    kw.setdefault("bsr_top1", "")
                    kw.setdefault("multi_source", "")

            self._table.load_data(keywords, KEYWORD_COLUMNS, KEYWORD_DISPLAY_NAMES)
            self._row_count_label.setText(f"{len(keywords)} rows")
        except Exception as e:
            self._progress.set_status(f"Error loading data: {e}")

    def _set_buttons_enabled(self, enabled: bool):
        self._mine_btn.setEnabled(enabled)
        self._probe_btn.setEnabled(enabled)
        self._merge_btn.setEnabled(enabled)
        self._export_btn.setEnabled(enabled)
        self._slots_btn.setEnabled(enabled)

    def _on_mine(self):
        dialog = MineDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = dialog.get_values()
        if not values["seed"]:
            QMessageBox.warning(self, "Error", "Please enter a seed keyword.")
            return

        self._set_buttons_enabled(False)
        self._progress.start()
        self._last_mine_seed = values["seed"]

        if values["multi"]:
            mps = ", ".join(m.upper() for m in values["marketplaces"])
            self._progress.set_status(f"Starting multi-marketplace mining ({mps})...")
            self._progress.append_log(
                f"Mining '{values['seed']}' across {mps} — depth={values['depth']}"
            )
            self._worker = MultiMarketplaceMineWorker(
                seed=values["seed"],
                depth=values["depth"],
                department=values["department"],
                marketplaces=values["marketplaces"],
            )
        else:
            mp = values["marketplace"].upper()
            self._progress.set_status(f"Starting mining on {mp}...")
            self._progress.append_log(
                f"Mining '{values['seed']}' on {mp} — depth={values['depth']}"
            )
            self._worker = MineWorker(
                seed=values["seed"],
                depth=values["depth"],
                department=values["department"],
                marketplace=values["marketplace"],
            )

        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_mine_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_mine_finished(self, result):
        self._set_buttons_enabled(True)
        if result is None:
            self._progress.finish("Mining cancelled")
            self._worker = None
            return
        if isinstance(result, dict):
            count = result.get('total_mined') or result.get('total_unique', 0)
        else:
            count = len(result) if result else 0
        self._progress.finish(f"Mining complete: {count} keywords found")
        self._load_data()
        try:
            from kdp_scout.db import KeywordRepository, init_db
            init_db()
            repo = KeywordRepository()
            all_kws = repo.get_keywords_with_latest_metrics(limit=10000)
            repo.close()
            history_data = [dict(kw) if not isinstance(kw, dict) else kw for kw in all_kws]
            SearchHistory.instance().log(
                tool="Keywords", action="Mine",
                query=getattr(self, '_last_mine_seed', ''),
                results=history_data, result_count=count,
            )
        except Exception:
            pass
        self._worker = None

    def _on_probe(self):
        """Launch competition probe + auto-score for current keyword DB."""
        from PyQt6.QtWidgets import QInputDialog

        limit, ok = QInputDialog.getInt(
            self, "Probe Competition",
            "How many keywords to probe? (top-scored first)\n"
            "Note: each probe makes 1 Amazon search request.",
            value=30, min=1, max=500,
        )
        if not ok:
            return

        mp = self._mp_filter.currentData() or "us"
        if mp == "all":
            mp = "us"

        self._set_buttons_enabled(False)
        self._progress.start()

        self._worker = CompetitionProbeWorker(
            limit=limit, marketplace=mp,
        )
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_probe_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_probe_finished(self, results):
        self._set_buttons_enabled(True)
        if results is None:
            self._progress.finish("Probe cancelled")
            self._worker = None
            return
        ok = sum(1 for r in results if r.get('success')) if results else 0
        self._progress.finish(f"Probe complete: {ok}/{len(results)} keywords enriched")
        self._on_score()

    def _on_score(self):
        self._set_buttons_enabled(False)
        self._progress.start()

        self._worker = ScoreWorker()
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_score_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_score_finished(self, result):
        self._set_buttons_enabled(True)
        count = result if isinstance(result, int) else (len(result) if result else 0)
        self._progress.finish(f"Scoring complete: {count} keywords scored")
        self._load_data()
        try:
            from kdp_scout.db import KeywordRepository, init_db
            init_db()
            repo = KeywordRepository()
            all_kws = repo.get_keywords_with_latest_metrics(limit=10000)
            repo.close()
            history_data = [dict(kw) if not isinstance(kw, dict) else kw for kw in all_kws]
            SearchHistory.instance().log(
                tool="Keywords", action="Score All",
                results=history_data, result_count=count,
            )
        except Exception:
            pass
        self._worker = None

    # ── Merge & Enrich ─────────────────────────────────────────────

    def _on_merge(self):
        """Launch cross-source keyword fusion."""
        # Collect all keywords currently in the table
        all_data = self._table._model.get_all_data()
        keywords = [
            row.get("keyword", "").strip()
            for row in all_data
            if row.get("keyword", "").strip()
        ]
        if not keywords:
            QMessageBox.warning(
                self, "No Keywords",
                "Mine some keywords first before running Merge & Enrich.",
            )
            return

        seed_hint = getattr(self, "_last_mine_seed", "")
        dialog = MergeEnrichDialog(seed_hint=seed_hint, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = dialog.get_values()
        mp = self._mp_filter.currentData() or "us"
        if mp == "all":
            mp = "us"

        self._set_buttons_enabled(False)
        self._progress.start()
        self._progress.set_status("Starting cross-source fusion…")
        self._progress.append_log(
            f"🔗 Merge & Enrich: {len(keywords)} keywords | "
            f"seed='{values['seed']}' | trends={values['max_trends']} | "
            f"bsr={values['max_bsr']} | mp={mp.upper()}"
        )

        self._worker = MergeEnrichWorker(
            keywords=keywords,
            seed=values["seed"],
            max_trends=values["max_trends"],
            max_bsr=values["max_bsr"],
            marketplace=mp,
        )
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_merge_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_merge_finished(self, enrichment):
        self._set_buttons_enabled(True)
        if enrichment is None:
            self._progress.finish("Merge & Enrich cancelled")
            self._worker = None
            return

        # Store enrichment overlay and reload table
        self._enrichment = enrichment
        kw_count = len(enrichment)
        multi_vals = [e.get("multi_source", 1) for e in enrichment.values()]
        avg_multi = sum(multi_vals) / max(len(multi_vals), 1)
        gs_ct = sum(1 for e in enrichment.values() if e.get("google_suggest"))
        trend_ct = sum(1 for e in enrichment.values() if e.get("trend", "—") != "—")
        bsr_ct = sum(1 for e in enrichment.values() if e.get("bsr_top1"))

        self._progress.finish(
            f"🔗 Enrichment complete: {kw_count} keywords — "
            f"G.Suggest: {gs_ct} | Trends: {trend_ct} | BSR: {bsr_ct} | "
            f"Avg sources: {avg_multi:.1f}"
        )
        self._load_data()

        # Log to history
        try:
            SearchHistory.instance().log(
                tool="Keywords", action="Merge & Enrich",
                results=[
                    {"keyword": k, **v}
                    for k, v in enrichment.items()
                ],
                result_count=kw_count,
            )
        except Exception:
            pass
        self._worker = None

    def _on_export_csv(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Keywords CSV", "keywords_export.csv", "CSV Files (*.csv)"
        )
        if not filepath:
            return

        self._set_buttons_enabled(False)
        self._progress.start()

        visible_data = self._table.get_visible_data()
        self._worker = ExportCSVWorker(filepath, data=visible_data if visible_data else None)
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_export_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_export_finished(self, result):
        self._set_buttons_enabled(True)
        self._progress.finish(f"Exported to {result}")
        self._worker = None

    def _on_kdp_slots(self):
        self._set_buttons_enabled(False)
        self._progress.start()

        self._worker = KDPSlotsWorker()
        self._worker.progress.connect(self._progress.set_progress)
        self._worker.status.connect(self._progress.set_status)
        self._worker.log.connect(self._progress.append_log)
        self._worker.finished_with_result.connect(self._on_slots_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_slots_finished(self, result):
        self._set_buttons_enabled(True)
        self._progress.finish("KDP slots generated")
        self._worker = None

        if result:
            dialog = KDPSlotsDialog(result, self)
            dialog.exec()

    def _on_row_double_click(self, row_data: dict):
        dialog = ScoreBreakdownDialog(row_data, self)
        dialog.exec()

    def _on_worker_error(self, error_msg: str):
        self._set_buttons_enabled(True)
        self._progress.finish(f"Error: {error_msg}")
        QMessageBox.critical(self, "Error", error_msg)
        self._worker = None

    def _on_cancel(self):
        if self._worker:
            self._worker.cancel()
            self._progress.set_status("Cancelling...")

    def focus_search(self):
        self._search_input.setFocus()
        self._search_input.selectAll()

"""Issues page: triage findings and drive the automated repair workflow."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from database.repository import ProjectRepository
from repair.engine import RepairEngine
from services.analysis_service import AnalysisService
from ui.widgets.common import (
    SEVERITY_COLORS,
    make_table,
    page_header,
    primary_button,
    secondary_button,
    set_row,
)
from verification.verifier import FixVerifier

logger = logging.getLogger(__name__)


class RepairDialog(QDialog):
    """Shows a suggested patch (unified diff) before it is applied."""

    def __init__(self, suggestion: Dict[str, object], parent=None):
        super().__init__(parent)
        self.suggestion = suggestion
        self.setWindowTitle(f"Suggested fix - {suggestion.get('rule_id')}")
        self.resize(900, 560)
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        explanation = QLabel(str(self.suggestion.get("explanation") or ""))
        explanation.setWordWrap(True)
        explanation.setStyleSheet("color: #d5d5e0; font-size: 13px;")
        layout.addWidget(explanation)

        meta = QLabel(
            "strategy: {strategy}   confidence: {confidence}   status: {status}".format(
                strategy=self.suggestion.get("strategy"),
                confidence=self.suggestion.get("confidence"),
                status=self.suggestion.get("status"),
            )
        )
        meta.setStyleSheet("color: #8b8b9c; font-size: 12px;")
        layout.addWidget(meta)

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(QFont("monospace", 10))
        self.diff_view.setPlainText(
            str(self.suggestion.get("diff") or "No automatic patch for this finding.")
        )
        layout.addWidget(self.diff_view, stretch=1)

        buttons = QDialogButtonBox()
        self.apply_button = buttons.addButton("Apply to file", QDialogButtonBox.AcceptRole)
        buttons.addButton("Close", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.apply_button.setEnabled(bool(self.suggestion.get("can_apply")))
        layout.addWidget(buttons)


class IssuesPage(QWidget):
    """Findings triage with one-click repair suggestions and verification."""

    def __init__(
        self,
        project_repo: ProjectRepository,
        analysis_service: AnalysisService,
        repair_engine: RepairEngine,
        verifier: FixVerifier,
        parent=None,
    ):
        super().__init__(parent)
        self.project_repo = project_repo
        self.analysis_service = analysis_service
        self.repair_engine = repair_engine
        self.verifier = verifier
        self.current_project_id: Optional[int] = None
        self.current_run_id: Optional[int] = None
        self._findings: List[Dict[str, object]] = []
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(14)

        layout.addWidget(
            page_header(
                "Issues",
                "Every finding from the latest analysis, with a suggested patch and a verification step.",
            )
        )

        filters = QHBoxLayout()
        filters.setSpacing(10)
        filters.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(240)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        filters.addWidget(self.project_combo)

        self.severity_filter = QComboBox()
        self.severity_filter.addItems(["All severities", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"])
        self.severity_filter.currentIndexChanged.connect(self.render_findings)
        filters.addWidget(self.severity_filter)

        self.category_filter = QComboBox()
        self.category_filter.addItems(
            ["All categories", "BUG", "SECURITY", "PERFORMANCE", "QUALITY", "DOCUMENTATION", "DUPLICATION", "DEPENDENCY", "SYNTAX"]
        )
        self.category_filter.currentIndexChanged.connect(self.render_findings)
        filters.addWidget(self.category_filter)
        filters.addStretch()

        self.fix_button = primary_button("Suggest Fix")
        self.fix_button.clicked.connect(self.suggest_fix)
        filters.addWidget(self.fix_button)

        self.verify_button = secondary_button("Verify Fix")
        self.verify_button.clicked.connect(self.verify_fix)
        filters.addWidget(self.verify_button)

        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.load_findings)
        filters.addWidget(self.refresh_button)
        layout.addLayout(filters)

        splitter = QSplitter(Qt.Vertical)

        self.table = make_table(["Severity", "Rule", "Location", "Title", "Status"])
        self.table.itemSelectionChanged.connect(self.show_detail)
        splitter.addWidget(self.table)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMinimumHeight(150)
        splitter.addWidget(self.detail)
        splitter.setSizes([420, 200])
        layout.addWidget(splitter, stretch=1)

        self.status_label = QLabel("Select a finding to see details.")
        self.status_label.setStyleSheet("color: #8b8b9c;")
        layout.addWidget(self.status_label)

        self._last_repair: Optional[Dict[str, object]] = None

    # -- data --------------------------------------------------------------
    def load_projects(self) -> None:
        previous = self.current_project_id
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        try:
            projects = self.project_repo.list_all()
        except Exception as error:  # pragma: no cover - defensive
            logger.error("Could not list projects: %s", error)
            projects = []
        for project in projects:
            self.project_combo.addItem(f"{project.name} (#{project.id})", project.id)
        self.project_combo.blockSignals(False)
        if previous is not None:
            index = self.project_combo.findData(previous)
            if index >= 0:
                self.project_combo.setCurrentIndex(index)
        self._on_project_changed()

    def select_project(self, project_id: int) -> None:
        index = self.project_combo.findData(project_id)
        if index >= 0:
            self.project_combo.setCurrentIndex(index)

    def _on_project_changed(self) -> None:
        data = self.project_combo.currentData()
        self.current_project_id = int(data) if data is not None else None
        self.load_findings()

    def load_findings(self) -> None:
        if self.current_project_id is None:
            self._findings = []
            self.table.setRowCount(0)
            self.detail.clear()
            return
        run = self.analysis_service.latest_run(self.current_project_id)
        self.current_run_id = int(run["run_id"]) if run else None
        try:
            self._findings = self.analysis_service.findings(
                self.current_project_id, run_id=self.current_run_id
            )
        except Exception as error:  # pragma: no cover - defensive
            logger.error("Could not load findings: %s", error)
            self._findings = []
        self.render_findings()
        self.status_label.setText(f"{len(self._findings)} finding(s) loaded.")

    def render_findings(self) -> None:
        severity = self.severity_filter.currentText()
        category = self.category_filter.currentText()
        rows = [
            finding
            for finding in self._findings
            if (severity == "All severities" or finding["severity"] == severity)
            and (category == "All categories" or finding["category"] == category)
        ]
        self.table.setRowCount(len(rows))
        for index, finding in enumerate(rows):
            location = f"{finding['file_path']}:{finding['line_start'] or '-'}"
            set_row(
                self.table,
                index,
                [
                    finding["severity"],
                    finding["rule_id"] or "",
                    location,
                    finding["title"],
                    finding["status"],
                ],
                colors=[SEVERITY_COLORS.get(str(finding["severity"]))],
            )
        self.table._rows = rows  # type: ignore[attr-defined]

    def _selected_finding(self) -> Optional[Dict[str, object]]:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        index = rows[0].row()
        available = getattr(self.table, "_rows", [])
        return available[index] if 0 <= index < len(available) else None

    def show_detail(self) -> None:
        finding = self._selected_finding()
        if not finding:
            return
        lines = [
            f"[{finding['severity']}] {finding['title']} ({finding['rule_id']})",
            f"File: {finding['file_path']}:{finding['line_start']}",
            f"Category: {finding['category']}   Detector: {finding['detector']}   Confidence: {finding['confidence']}",
            "",
            str(finding.get("description") or ""),
        ]
        if finding.get("code_snippet"):
            lines.extend(["", "Code:", str(finding["code_snippet"])])
        if finding.get("suggestion"):
            lines.extend(["", f"Suggested fix: {finding['suggestion']}"])
        self.detail.setPlainText("\n".join(lines))

    # -- repair workflow ---------------------------------------------------
    def suggest_fix(self) -> None:
        finding = self._selected_finding()
        if not finding:
            QMessageBox.information(self, "No finding", "Select a finding first.")
            return
        try:
            suggestion = self.repair_engine.suggest_for_finding(int(finding["id"]), force=True)
        except Exception as error:
            QMessageBox.critical(self, "Repair failed", str(error))
            return

        self._last_repair = suggestion
        dialog = RepairDialog(suggestion, self)
        if dialog.exec() == QDialog.Accepted:
            if not suggestion.get("can_apply"):
                QMessageBox.information(
                    self,
                    "Manual fix required",
                    str(suggestion.get("explanation") or ""),
                )
                return
            confirm = QMessageBox.question(
                self,
                "Apply patch",
                "Write the patched file to disk?\nA .bak backup of the original is kept.",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            try:
                self.repair_engine.apply(int(suggestion["repair_id"]))
            except Exception as error:
                QMessageBox.critical(self, "Apply failed", str(error))
                return
            self.status_label.setText(
                f"Applied repair #{suggestion['repair_id']}. Run 'Verify Fix' to check it."
            )
            self.load_findings()

    def verify_fix(self) -> None:
        if not self._last_repair or not self._last_repair.get("can_apply"):
            QMessageBox.information(
                self, "Nothing to verify", "Suggest a fix for a finding first."
            )
            return
        try:
            outcome = self.verifier.verify_repair(int(self._last_repair["repair_id"]))
        except Exception as error:
            QMessageBox.critical(self, "Verification failed", str(error))
            return
        detail = "\n".join(
            f"- {check['name']}: {'PASS' if check['passed'] else 'FAIL'}"
            + (f" ({check['detail'][:300]})" if check.get("detail") else "")
            for check in outcome.get("checks", [])  # type: ignore[union-attr]
        )
        message = "Verification passed." if outcome.get("passed") else "Verification failed."
        QMessageBox.information(self, message, detail or message)
        self.status_label.setText(message)

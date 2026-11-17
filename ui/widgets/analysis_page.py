"""Code Analysis page: run the static analysis engine and browse the findings."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from database.repository import ProjectRepository
from services.analysis_service import AnalysisService
from ui.widgets.common import (
    SEVERITY_COLORS,
    StatCardsRow,
    make_table,
    page_header,
    primary_button,
    secondary_button,
    set_row,
    start_worker,
)

logger = logging.getLogger(__name__)


class AnalysisPage(QWidget):
    """Runs :class:`AnalysisService` for a project and shows the results."""

    def __init__(self, project_repo: ProjectRepository, analysis_service: AnalysisService, parent=None):
        super().__init__(parent)
        self.project_repo = project_repo
        self.analysis_service = analysis_service
        self.current_project_id: Optional[int] = None
        self.current_run_id: Optional[int] = None
        self._findings: List[Dict[str, object]] = []
        self.init_ui()

    # -- construction ------------------------------------------------------
    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        layout.addWidget(
            page_header(
                "Code Analysis",
                "Static analysis: bugs, security, performance, quality, documentation, duplication and dependencies.",
            )
        )

        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(260)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        controls.addWidget(self.project_combo)

        self.run_button = primary_button("Run Analysis")
        self.run_button.clicked.connect(self.run_analysis)
        controls.addWidget(self.run_button)

        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.load_projects)
        controls.addWidget(self.refresh_button)
        controls.addStretch()

        self.severity_filter = QComboBox()
        self.severity_filter.addItems(["All severities", "CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"])
        self.severity_filter.currentIndexChanged.connect(self.render_findings)
        controls.addWidget(self.severity_filter)
        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        layout.addWidget(self.progress)

        self.stats = StatCardsRow(["Files", "Findings", "Critical", "Duplicate blocks", "Maintainability"])
        layout.addWidget(self.stats)

        self.status_label = QLabel("Select a project and run the analysis.")
        self.status_label.setStyleSheet("color: #8b8b9c;")
        layout.addWidget(self.status_label)

        self.table = make_table(["Severity", "Rule", "Location", "Title", "Category"])
        self.table.setMinimumHeight(280)
        layout.addWidget(self.table, stretch=1)

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
        self.current_run_id = None
        self._findings = []
        self.table.setRowCount(0)
        if self.current_project_id is None:
            self.status_label.setText("No project selected. Create one on the Projects page.")
            return
        self.load_existing_run()

    def load_existing_run(self) -> None:
        if self.current_project_id is None:
            return
        try:
            run = self.analysis_service.latest_run(self.current_project_id)
            if not run or run["status"] != "COMPLETED":
                self.status_label.setText("No completed analysis yet - click 'Run Analysis'.")
                return
            self.current_run_id = int(run["run_id"])
            self._findings = self.analysis_service.findings(
                self.current_project_id, run_id=self.current_run_id
            )
            metrics = self.analysis_service.metrics(self.current_project_id, run_id=self.current_run_id)
            self._update_stats(run, metrics)
            self.render_findings()
            self.status_label.setText(
                f"Loaded run #{self.current_run_id} from {run['completed_at'] or 'earlier'}."
            )
        except Exception as error:
            logger.error("Could not load analysis run: %s", error)
            self.status_label.setText(f"Could not load the previous run: {error}")

    def _update_stats(self, run: Dict[str, object], metrics: Dict[str, object]) -> None:
        counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}
        for finding in self._findings:
            counts[str(finding["severity"])] = counts.get(str(finding["severity"]), 0) + 1
        duplicates = 0
        if self.current_run_id is not None:
            duplicates = len(self.analysis_service.duplicates(self.current_run_id))
        self.stats.set_value("Files", run.get("files_analyzed", 0))
        self.stats.set_value("Findings", run.get("findings_count", len(self._findings)))
        self.stats.set_value("Critical", counts.get("CRITICAL", 0))
        self.stats.set_value("Duplicate blocks", duplicates)
        maintainability = metrics.get("maintainability_index")
        self.stats.set_value("Maintainability", f"{maintainability}" if maintainability is not None else "--")

    def render_findings(self) -> None:
        selected = self.severity_filter.currentText()
        rows = [
            finding
            for finding in self._findings
            if selected == "All severities" or finding["severity"] == selected
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
                    finding["category"],
                ],
                colors=[SEVERITY_COLORS.get(str(finding["severity"]))],
            )

    # -- actions -----------------------------------------------------------
    def run_analysis(self) -> None:
        if self.current_project_id is None:
            QMessageBox.information(self, "No project", "Select a project first.")
            return
        project_id = self.current_project_id
        self.run_button.setEnabled(False)
        self.progress.setValue(0)
        self.status_label.setText("Analysing...")

        def task(progress):
            return self.analysis_service.run(project_id, progress_callback=lambda pct: progress("Analysing", pct))

        start_worker(self, task, self._on_finished, self._on_failed, self._on_progress)

    def _on_progress(self, name: str, percent: int) -> None:
        self.progress.setValue(percent)
        self.status_label.setText(f"{name}... {percent}%")

    def _on_finished(self, summary: object) -> None:
        self.run_button.setEnabled(True)
        self.progress.setValue(100)
        payload = dict(summary or {})  # type: ignore[arg-type]
        self.current_run_id = payload.get("run_id")
        self._findings = self.analysis_service.findings(
            int(self.current_project_id or 0), run_id=self.current_run_id
        )
        metrics = self.analysis_service.metrics(
            int(self.current_project_id or 0), run_id=self.current_run_id
        )
        self._update_stats(payload, metrics)
        self.render_findings()
        counts = payload.get("severity_counts") or {}
        self.status_label.setText(
            "Analysis complete: {files} file(s), {findings} finding(s) "
            "({critical} critical, {high} high) in {duration}s.".format(
                files=payload.get("files_analyzed", 0),
                findings=payload.get("findings", 0),
                critical=counts.get("CRITICAL", 0),
                high=counts.get("HIGH", 0),
                duration=payload.get("duration_seconds", 0),
            )
        )

    def _on_failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.progress.setValue(0)
        self.status_label.setText("Analysis failed.")
        QMessageBox.critical(self, "Analysis failed", message)

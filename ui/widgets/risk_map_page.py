"""Risk Map page: per-file risk heat derived from finding severities and metrics."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from database.repository import ProjectRepository
from services.analysis_service import AnalysisService
from ui.widgets.common import SEVERITY_COLORS, make_table, page_header, secondary_button, set_row

logger = logging.getLogger(__name__)

SEVERITY_WEIGHT = {"CRITICAL": 25, "HIGH": 10, "MEDIUM": 4, "LOW": 1, "INFO": 0}


def file_risk_score(findings: List[Dict[str, object]]) -> int:
    """0-100 risk score for one file (capped)."""
    score = sum(SEVERITY_WEIGHT.get(str(f.get("severity")), 0) for f in findings)
    return min(score, 100)


def risk_band(score: int) -> str:
    if score >= 60:
        return "CRITICAL"
    if score >= 35:
        return "HIGH"
    if score >= 15:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "INFO"


class RiskMapPage(QWidget):
    """Shows which files carry the most risk."""

    def __init__(self, project_repo: ProjectRepository, analysis_service: AnalysisService, parent=None):
        super().__init__(parent)
        self.project_repo = project_repo
        self.analysis_service = analysis_service
        self.current_project_id: Optional[int] = None
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(14)

        layout.addWidget(
            page_header(
                "Risk Map",
                "Files ranked by weighted finding severity - the hot spots to fix first.",
            )
        )

        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(260)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        controls.addWidget(self.project_combo)

        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.load_risk_map)
        controls.addWidget(self.refresh_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.summary_label = QLabel("No analysis loaded.")
        self.summary_label.setStyleSheet("color: #8b8b9c;")
        layout.addWidget(self.summary_label)

        self.table = make_table(["File", "Risk", "Critical", "High", "Medium", "Low", "Findings", "Complexity"])
        self.table.setMinimumHeight(320)
        layout.addWidget(self.table, stretch=1)

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
        self.load_risk_map()

    def load_risk_map(self) -> None:
        self.table.setRowCount(0)
        if self.current_project_id is None:
            self.summary_label.setText("No project selected.")
            return
        run = self.analysis_service.latest_run(self.current_project_id)
        if not run:
            self.summary_label.setText("Run the analysis first.")
            return
        try:
            findings = self.analysis_service.findings(
                self.current_project_id, run_id=int(run["run_id"])
            )
        except Exception as error:  # pragma: no cover - defensive
            logger.error("Could not load findings: %s", error)
            findings = []

        per_file: Dict[str, List[Dict[str, object]]] = {}
        for finding in findings:
            per_file.setdefault(str(finding["file_path"]), []).append(finding)

        metrics = self.analysis_service.metrics(self.current_project_id, run_id=int(run["run_id"]))
        average_complexity = metrics.get("average_complexity")

        rows = []
        for path, items in per_file.items():
            counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
            for item in items:
                if item["severity"] in counts:
                    counts[item["severity"]] += 1
            rows.append((path, file_risk_score(items), counts, len(items)))
        rows.sort(key=lambda row: -row[1])

        self.table.setRowCount(len(rows))
        for index, (path, score, counts, total) in enumerate(rows):
            band = risk_band(score)
            set_row(
                self.table,
                index,
                [
                    path,
                    f"{score} ({band})",
                    counts["CRITICAL"],
                    counts["HIGH"],
                    counts["MEDIUM"],
                    counts["LOW"],
                    total,
                    average_complexity if average_complexity is not None else "--",
                ],
                colors=[None, SEVERITY_COLORS.get(band)],
            )
        self.summary_label.setText(
            f"{len(rows)} file(s) with findings, {len(findings)} finding(s) total."
        )

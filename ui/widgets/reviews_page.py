"""Reviews page: run the five agents and inspect their scores and insights."""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from database.repository import ProjectRepository
from reports.generator import ReportGenerator
from services.review_service import ReviewService
from ui.widgets.common import (
    RISK_COLORS,
    make_table,
    page_header,
    primary_button,
    secondary_button,
    set_row,
    start_worker,
)

logger = logging.getLogger(__name__)


class ReviewsPage(QWidget):
    """Multi-agent review: one row per agent, plus the aggregated verdict."""

    def __init__(
        self,
        project_repo: ProjectRepository,
        review_service: ReviewService,
        report_generator: ReportGenerator,
        parent=None,
    ):
        super().__init__(parent)
        self.project_repo = project_repo
        self.review_service = review_service
        self.report_generator = report_generator
        self.current_project_id: Optional[int] = None
        self.current_session_id: Optional[int] = None
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(16)

        layout.addWidget(
            page_header(
                "Multi-Agent Review",
                "Bug Detection, Security, Performance, Code Quality and Documentation agents score the project independently.",
            )
        )

        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(260)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        controls.addWidget(self.project_combo)

        self.run_button = primary_button("Run Multi-Agent Review")
        self.run_button.clicked.connect(self.run_review)
        controls.addWidget(self.run_button)

        self.export_button = secondary_button("Export Report")
        self.export_button.clicked.connect(self.export_report)
        self.export_button.setEnabled(False)
        controls.addWidget(self.export_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        verdict = QHBoxLayout()
        verdict.setSpacing(24)
        self.score_label = QLabel("--")
        self.score_label.setStyleSheet("font-size: 46px; font-weight: 700; color: #ffffff;")
        self.risk_label = QLabel("risk: --")
        self.risk_label.setStyleSheet("font-size: 16px; color: #8b8b9c;")
        self.provider_label = QLabel("provider: --")
        self.provider_label.setStyleSheet("font-size: 12px; color: #626270;")
        verdict.addWidget(self.score_label)
        verdict.addWidget(self.risk_label)
        verdict.addWidget(self.provider_label)
        verdict.addStretch()
        layout.addLayout(verdict)

        self.summary_label = QLabel("Run a review to see the verdict.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #b9b9c9; font-size: 13px;")
        layout.addWidget(self.summary_label)

        self.agents_table = make_table(["Agent", "Score", "Weight", "Findings", "Critical", "High"])
        self.agents_table.setMinimumHeight(190)
        self.agents_table.itemSelectionChanged.connect(self.show_selected_agent)
        layout.addWidget(self.agents_table)

        insights_label = QLabel("Agent insights")
        insights_label.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff;")
        layout.addWidget(insights_label)

        self.insights_box = QTextEdit()
        self.insights_box.setReadOnly(True)
        self.insights_box.setMinimumHeight(140)
        layout.addWidget(self.insights_box, stretch=1)

        self._agents: List[Dict[str, object]] = []

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
        self.current_session_id = None
        self._agents = []
        self.agents_table.setRowCount(0)
        self.insights_box.clear()
        self.export_button.setEnabled(False)
        if self.current_project_id is None:
            self.summary_label.setText("No project selected.")
            return
        self.load_latest_review()

    def load_latest_review(self) -> None:
        if self.current_project_id is None:
            return
        try:
            review = self.review_service.latest_review(self.current_project_id)
        except Exception as error:  # pragma: no cover - defensive
            logger.error("Could not load review: %s", error)
            review = None
        if not review:
            self.summary_label.setText("No review yet - click 'Run Multi-Agent Review'.")
            return
        self._render_review(review)

    def _render_review(self, review: Dict[str, object]) -> None:
        self.current_session_id = int(review.get("session_id") or 0) or None
        score = review.get("overall_score")
        risk = str(review.get("risk_level") or "--")
        self.score_label.setText(f"{score}" if score is not None else "--")
        self.risk_label.setText(f"risk: {risk}")
        self.risk_label.setStyleSheet(
            f"font-size: 16px; color: {RISK_COLORS.get(risk, '#8b8b9c')}; font-weight: 600;"
        )
        self.provider_label.setText(f"provider: {review.get('provider') or '--'}")
        self.summary_label.setText(str(review.get("summary") or ""))

        self._agents = list(review.get("agents") or [])  # type: ignore[arg-type]
        self.agents_table.setRowCount(len(self._agents))
        for index, agent in enumerate(self._agents):
            set_row(
                self.agents_table,
                index,
                [
                    agent.get("agent_name"),
                    agent.get("score"),
                    agent.get("weight"),
                    agent.get("findings_count"),
                    agent.get("critical_count"),
                    agent.get("high_count"),
                ],
            )
        self.export_button.setEnabled(self.current_session_id is not None)
        if self._agents:
            self.agents_table.selectRow(0)
            self.show_selected_agent()

    def show_selected_agent(self) -> None:
        rows = self.agents_table.selectionModel().selectedRows() if self.agents_table.selectionModel() else []
        if not rows:
            return
        index = rows[0].row()
        if not (0 <= index < len(self._agents)):
            return
        agent = self._agents[index]
        lines = [f"{agent.get('agent_name')} - score {agent.get('score')}/100", ""]
        lines.append(str(agent.get("summary") or ""))
        lines.append("")
        for insight in agent.get("insights") or []:  # type: ignore[union-attr]
            lines.append(f"* {insight}")
        self.insights_box.setPlainText("\n".join(lines))

    # -- actions -----------------------------------------------------------
    def run_review(self) -> None:
        if self.current_project_id is None:
            QMessageBox.information(self, "No project", "Select a project first.")
            return
        project_id = self.current_project_id
        self.run_button.setEnabled(False)
        self.progress.setValue(0)
        self.summary_label.setText("Running the agents...")

        def task(progress):
            return self.review_service.review_project(project_id, progress_callback=progress)

        start_worker(self, task, self._on_finished, self._on_failed, self._on_progress)

    def _on_progress(self, name: str, percent: int) -> None:
        self.progress.setValue(percent)
        self.summary_label.setText(f"{name}... {percent}%")

    def _on_finished(self, result: object) -> None:
        self.run_button.setEnabled(True)
        self.progress.setValue(100)
        payload = dict(result or {})  # type: ignore[arg-type]
        session_id = payload.get("session_id")
        if session_id is not None:
            review = self.review_service.get_review(int(session_id))
            if review:
                self._render_review(review)

    def _on_failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.progress.setValue(0)
        QMessageBox.critical(self, "Review failed", message)

    def export_report(self) -> None:
        if self.current_session_id is None:
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export report",
            f"review_{self.current_session_id}.md",
            "Markdown (*.md);;HTML (*.html);;JSON (*.json)",
        )
        if not path:
            return
        fmt = "markdown"
        if path.lower().endswith(".html") or "HTML" in selected_filter:
            fmt = "html"
        elif path.lower().endswith(".json") or "JSON" in selected_filter:
            fmt = "json"
        try:
            self.report_generator.export(self.current_session_id, path, fmt)
        except Exception as error:  # pragma: no cover - defensive
            QMessageBox.critical(self, "Export failed", str(error))
            return
        QMessageBox.information(self, "Report exported", f"Saved to:\n{os.path.abspath(path)}")

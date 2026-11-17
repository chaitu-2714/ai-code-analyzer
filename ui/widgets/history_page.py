"""History page: review sessions over time plus the score trend."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from database.repository import ProjectRepository
from services.review_service import ReviewService
from ui.widgets.common import (
    RISK_COLORS,
    Sparkline,
    make_table,
    page_header,
    secondary_button,
    set_row,
)

logger = logging.getLogger(__name__)


class HistoryPage(QWidget):
    """Quality trend and review history for one project."""

    def __init__(self, project_repo: ProjectRepository, review_service: ReviewService, parent=None):
        super().__init__(parent)
        self.project_repo = project_repo
        self.review_service = review_service
        self.current_project_id: Optional[int] = None
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(14)

        layout.addWidget(
            page_header("History", "Every review session with its score, risk level and trend.")
        )

        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(QLabel("Project:"))
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(260)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        controls.addWidget(self.project_combo)

        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.load_history)
        controls.addWidget(self.refresh_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.sparkline = Sparkline()
        layout.addWidget(self.sparkline)

        self.table = make_table(["Session", "Score", "Risk", "Created"])
        layout.addWidget(self.table, stretch=1)

        self.leaderboard_label = QLabel("")
        self.leaderboard_label.setStyleSheet("color: #8b8b9c; font-size: 12px;")
        self.leaderboard_label.setWordWrap(True)
        layout.addWidget(self.leaderboard_label)

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
        self.load_history()

    def load_history(self) -> None:
        self.table.setRowCount(0)
        self.sparkline.set_values([])
        self.leaderboard_label.setText("")
        if self.current_project_id is None:
            return
        try:
            reviews = self.review_service.list_reviews(self.current_project_id, limit=50)
            trend = self.review_service.quality_trend(self.current_project_id, limit=50)
            leaderboard = self.review_service.agent_leaderboard(self.current_project_id)
        except Exception as error:  # pragma: no cover - defensive
            logger.error("Could not load history: %s", error)
            return

        self.table.setRowCount(len(reviews))
        for index, review in enumerate(reviews):
            set_row(
                self.table,
                index,
                [
                    review.get("session_id"),
                    review.get("overall_score"),
                    review.get("risk_level"),
                    review.get("created_at"),
                ],
                colors=[None, None, RISK_COLORS.get(str(review.get("risk_level")), None), None],
            )
        self.sparkline.set_values([row["overall_score"] for row in trend if row["overall_score"] is not None])
        if leaderboard:
            self.leaderboard_label.setText(
                "Agent averages: "
                + " | ".join(f"{item['agent_name']} {item['average_score']}" for item in leaderboard)
            )

import logging

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.repository import ProjectRepository, ReviewSessionRepository

logger = logging.getLogger(__name__)

class DashboardWidget(QWidget):
    """Analytics dashboard widget presenting counts and recent projects."""
    def __init__(self, project_repo: ProjectRepository, session_repo: ReviewSessionRepository, parent=None):
        super().__init__(parent)
        self.project_repo = project_repo
        self.session_repo = session_repo
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(25)

        # Header
        header = QLabel("Dashboard")
        header.setObjectName("PageHeader")
        layout.addWidget(header)

        # Cards Layout (KPIs)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(20)

        self.projects_card = self.create_card("Projects", "0")
        self.reviews_card = self.create_card("Reviews", "0")
        self.issues_card = self.create_card("Issues Found", "0")
        self.quality_card = self.create_card("Average Quality", "--")

        cards_layout.addWidget(self.projects_card)
        cards_layout.addWidget(self.reviews_card)
        cards_layout.addWidget(self.issues_card)
        cards_layout.addWidget(self.quality_card)
        layout.addLayout(cards_layout)

        # Recent Projects Section
        recent_label = QLabel("Recent Projects")
        recent_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff; margin-top: 10px;")
        layout.addWidget(recent_label)

        # Table for recent projects
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Project Name", "Language", "Source Path", "Created At"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        # Load dynamic database content
        self.refresh()

    def create_card(self, title: str, default_value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("CardFrame")
        card.setFrameShape(QFrame.StyledPanel)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 15, 15, 15)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("CardTitle")

        lbl_val = QLabel(default_value)
        lbl_val.setObjectName("CardValue")

        card_layout.addWidget(lbl_title)
        card_layout.addWidget(lbl_val)

        # Store a reference to the label to update value dynamically
        card.setProperty("value_label", lbl_val)
        return card

    def refresh(self):
        """Queries database and updates KPI card and recent projects table."""
        try:
            p_count = self.project_repo.count()
            s_count = self.session_repo.count()
            avg_score = self.session_repo.get_average_score()

            # Update KPI card values
            self.projects_card.property("value_label").setText(str(p_count))
            self.reviews_card.property("value_label").setText(str(s_count))

            # Phase 1 Placeholders for issues & overall score quality
            self.issues_card.property("value_label").setText("0")

            if avg_score is not None:
                self.quality_card.property("value_label").setText(f"{avg_score}%")
            else:
                self.quality_card.property("value_label").setText("--")

            # Load recent projects
            projects = self.project_repo.list_all()
            # Limit to top 5 in recent
            recent_projects = projects[:5]

            self.table.setRowCount(0)
            for project in recent_projects:
                row = self.table.rowCount()
                self.table.insertRow(row)

                self.table.setItem(row, 0, QTableWidgetItem(project.name))
                self.table.setItem(row, 1, QTableWidgetItem(project.language or "Unknown"))
                self.table.setItem(row, 2, QTableWidgetItem(project.source_path or "N/A"))

                created_str = project.created_at.strftime("%Y-%m-%d %H:%M") if project.created_at else "N/A"
                self.table.setItem(row, 3, QTableWidgetItem(created_str))

        except Exception as e:
            logger.error(f"Error loading dashboard details: {e}")

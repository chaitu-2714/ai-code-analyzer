import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from database.repository import ProjectRepository, ReviewSessionRepository
from repair.engine import RepairEngine
from reports.generator import ReportGenerator
from services.analysis_service import AnalysisService
from services.ingestion import IngestionService
from services.playground_service import PlaygroundService
from services.review_service import ReviewService
from ui.styles import load_stylesheet
from ui.widgets.analysis_page import AnalysisPage
from ui.widgets.code_explorer import CodeExplorerWidget
from ui.widgets.compiler_page import CompilerPage
from ui.widgets.dashboard import DashboardWidget
from ui.widgets.history_page import HistoryPage
from ui.widgets.issues_page import IssuesPage
from ui.widgets.project_overview import ProjectOverviewWidget
from ui.widgets.projects import ProjectsWidget
from ui.widgets.reviews_page import ReviewsPage
from ui.widgets.risk_map_page import RiskMapPage
from ui.widgets.settings_page import SettingsPage
from verification.verifier import FixVerifier

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main window of the AI Code Reviewer platform containing sidebar navigation."""

    def __init__(
        self,
        project_repo: ProjectRepository,
        session_repo: ReviewSessionRepository,
        app_name: str,
        app_version: str,
        config=None,
    ):
        super().__init__()
        self.project_repo = project_repo
        self.session_repo = session_repo
        self.app_name = app_name
        self.app_version = app_version
        self.config = config
        self.current_project_id = None

        # Services (Phases 1, 3, 5, 6, 7, 8)
        session_factory = project_repo.session_factory
        self.ingestion_service = IngestionService(session_factory)
        self.analysis_service = AnalysisService(session_factory, config)
        self.review_service = ReviewService(session_factory, config, analysis_service=self.analysis_service)
        self.repair_engine = RepairEngine(session_factory, config=config)
        self.verifier = FixVerifier(session_factory, config)
        self.playground_service = PlaygroundService(config)
        self.report_generator = ReportGenerator(
            session_factory, review_service=self.review_service, analysis_service=self.analysis_service
        )

        self.setWindowTitle(f"{self.app_name} (v{self.app_version})")
        self.resize(1280, 860)
        self.setMinimumSize(1100, 700)

        style = load_stylesheet()
        if style:
            self.setStyleSheet(style)
        else:
            logger.warning("Could not load styles. Proceeding with default Qt theme.")

        self.init_ui()

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        main_layout.addWidget(self._build_sidebar())

        self.pages_container = QStackedWidget()
        self._build_pages()
        main_layout.addWidget(self.pages_container)

        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready")
        logger.info("Main window layout initialized.")

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("SidebarWidget")
        sidebar.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(5)

        title_lbl = QLabel(self.app_name.upper())
        title_lbl.setObjectName("SidebarTitle")
        title_lbl.setAlignment(Qt.AlignCenter)
        title_lbl.setWordWrap(True)
        sidebar_layout.addWidget(title_lbl)
        sidebar_layout.addSpacing(15)

        self.nav_buttons = []
        self.sidebar_pages = [
            ("Dashboard", self.show_dashboard_page),
            ("Projects", self.show_projects_page),
            ("Code Explorer", self.show_code_explorer_sidebar),
            ("Compiler", self.show_compiler_page),
            ("Code Analysis", self.show_analysis_page),
            ("Reviews", self.show_reviews_page),
            ("Issues", self.show_issues_page),
            ("Risk Map", self.show_risk_map_page),
            ("History", self.show_history_page),
            ("Settings", self.show_settings_page),
        ]

        for index, (name, callback) in enumerate(self.sidebar_pages):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setObjectName("SidebarNavButton")
            btn.setProperty("class", "SidebarNavButton")
            btn.setCursor(Qt.PointingHandCursor)
            if index == 0:
                btn.setChecked(True)
            btn.clicked.connect(callback)
            btn.clicked.connect(lambda checked, b=btn: self.handle_nav_click(b))
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()

        version_lbl = QLabel(f"v{self.app_version}")
        version_lbl.setStyleSheet("color: #626270; font-size: 11px; padding: 5px;")
        version_lbl.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(version_lbl)
        return sidebar

    def _build_pages(self):
        # Core pages
        self.dashboard_widget = DashboardWidget(self.project_repo, self.session_repo)
        self.projects_widget = ProjectsWidget(self.project_repo, self.ingestion_service)
        self.overview_widget = ProjectOverviewWidget(self.project_repo)
        self.explorer_widget = CodeExplorerWidget(self.project_repo)

        self.compiler_widget = CompilerPage(self.playground_service)

        # Phase 3-8 pages
        self.analysis_widget = AnalysisPage(self.project_repo, self.analysis_service)
        self.reviews_widget = ReviewsPage(self.project_repo, self.review_service, self.report_generator)
        self.issues_widget = IssuesPage(
            self.project_repo, self.analysis_service, self.repair_engine, self.verifier
        )
        self.risk_widget = RiskMapPage(self.project_repo, self.analysis_service)
        self.history_widget = HistoryPage(self.project_repo, self.review_service)
        self.settings_widget = SettingsPage(self.config)

        # Generic message screen (used when no project is active)
        self.placeholder_widget = QWidget()
        placeholder_layout = QVBoxLayout(self.placeholder_widget)
        placeholder_layout.setContentsMargins(50, 50, 50, 50)
        placeholder_layout.setAlignment(Qt.AlignCenter)
        self.placeholder_title = QLabel("Feature Screen")
        self.placeholder_title.setObjectName("PageHeader")
        self.placeholder_desc = QLabel("Feature available in upcoming phase.")
        self.placeholder_desc.setStyleSheet("font-size: 15px; color: #8b8b9c; margin-top: 10px;")
        self.placeholder_desc.setWordWrap(True)
        placeholder_layout.addWidget(self.placeholder_title)
        placeholder_layout.addWidget(self.placeholder_desc)

        self.page_index = {}
        for name, widget in (
            ("dashboard", self.dashboard_widget),
            ("projects", self.projects_widget),
            ("placeholder", self.placeholder_widget),
            ("overview", self.overview_widget),
            ("explorer", self.explorer_widget),
            ("compiler", self.compiler_widget),
            ("analysis", self.analysis_widget),
            ("reviews", self.reviews_widget),
            ("issues", self.issues_widget),
            ("risk", self.risk_widget),
            ("history", self.history_widget),
            ("settings", self.settings_widget),
        ):
            self.page_index[name] = self.pages_container.addWidget(widget)

        self.project_pages = (
            self.analysis_widget,
            self.reviews_widget,
            self.issues_widget,
            self.risk_widget,
            self.history_widget,
        )

    # ------------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------------
    def handle_nav_click(self, clicked_btn: QPushButton):
        for btn in self.nav_buttons:
            if btn != clicked_btn:
                btn.setChecked(False)
        clicked_btn.setChecked(True)

    def _sync_project_pages(self):
        """Keeps every project-scoped page pointed at the active project."""
        if self.current_project_id is None:
            return
        for page in self.project_pages:
            page.select_project(self.current_project_id)

    def show_dashboard_page(self):
        self.dashboard_widget.refresh()
        self.pages_container.setCurrentIndex(self.page_index["dashboard"])
        self.statusBar().showMessage("Viewing Dashboard")

    def show_projects_page(self):
        self.projects_widget.refresh()
        self.pages_container.setCurrentIndex(self.page_index["projects"])
        self.statusBar().showMessage("Viewing Projects")

    def show_compiler_page(self):
        self.pages_container.setCurrentIndex(self.page_index["compiler"])
        self.statusBar().showMessage("Viewing Compiler")

    def show_analysis_page(self):
        self.analysis_widget.load_projects()
        self._sync_project_pages()
        self.pages_container.setCurrentIndex(self.page_index["analysis"])
        self.statusBar().showMessage("Viewing Code Analysis")

    def show_reviews_page(self):
        self.reviews_widget.load_projects()
        self._sync_project_pages()
        self.pages_container.setCurrentIndex(self.page_index["reviews"])
        self.statusBar().showMessage("Viewing Multi-Agent Reviews")

    def show_issues_page(self):
        self.issues_widget.load_projects()
        self._sync_project_pages()
        self.pages_container.setCurrentIndex(self.page_index["issues"])
        self.statusBar().showMessage("Viewing Issues")

    def show_risk_map_page(self):
        self.risk_widget.load_projects()
        self._sync_project_pages()
        self.pages_container.setCurrentIndex(self.page_index["risk"])
        self.statusBar().showMessage("Viewing Risk Map")

    def show_history_page(self):
        self.history_widget.load_projects()
        self._sync_project_pages()
        self.pages_container.setCurrentIndex(self.page_index["history"])
        self.statusBar().showMessage("Viewing History")

    def show_settings_page(self):
        self.pages_container.setCurrentIndex(self.page_index["settings"])
        self.statusBar().showMessage("Viewing Settings")

    def show_placeholder_page(self, title: str, description: str = "Feature available in upcoming phase."):
        self.placeholder_title.setText(title)
        self.placeholder_desc.setText(description)
        self.pages_container.setCurrentIndex(self.page_index["placeholder"])
        self.statusBar().showMessage(f"Viewing {title}")

    def show_project_overview_page(self, project_id: int):
        self.current_project_id = project_id
        self.overview_widget.load_project_overview(project_id)
        self.pages_container.setCurrentIndex(self.page_index["overview"])
        self.statusBar().showMessage(f"Viewing Project Overview (ID: {project_id})")
        for btn in self.nav_buttons:
            btn.setChecked(False)

    def show_code_explorer_page(self, project_id: int):
        self.current_project_id = project_id
        self.explorer_widget.load_project_workspace(project_id)
        self.pages_container.setCurrentIndex(self.page_index["explorer"])
        self.statusBar().showMessage(f"Viewing Code Explorer (ID: {project_id})")
        for btn in self.nav_buttons:
            if btn.text() == "Code Explorer":
                btn.setChecked(True)
            else:
                btn.setChecked(False)

    def show_code_explorer_sidebar(self):
        if self.current_project_id is None:
            self.show_placeholder_page(
                "Code Explorer",
                "No active project loaded. Go to Projects and select 'Explore' for a codebase.",
            )
            self.statusBar().showMessage("No active project for Explorer")
        else:
            self.show_code_explorer_page(self.current_project_id)

    def update_dashboard_kpis(self):
        """Triggered when project CRUD events occur, keeping dashboard fresh."""
        self.dashboard_widget.refresh()

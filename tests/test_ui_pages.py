"""GUI smoke tests: every page builds and refreshes without a display server."""
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from database.repository import ProjectRepository, ReviewSessionRepository  # noqa: E402
from services.analysis_service import AnalysisService  # noqa: E402
from services.review_service import ReviewService  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, session_factory, indexed_project):
    project_repo = ProjectRepository(session_factory)
    session_repo = ReviewSessionRepository(session_factory)
    main = MainWindow(
        project_repo=project_repo,
        session_repo=session_repo,
        app_name="Test App",
        app_version="1.0.0",
        config=None,
    )
    yield main
    main.close()


def test_all_pages_are_wired(window):
    for name in (
        "dashboard",
        "projects",
        "placeholder",
        "overview",
        "explorer",
        "compiler",
        "analysis",
        "reviews",
        "issues",
        "risk",
        "history",
        "settings",
    ):
        assert name in window.page_index


def test_sidebar_has_no_placeholders_left(window):
    labels = [button.text() for button in window.nav_buttons]
    assert labels == [
        "Dashboard",
        "Projects",
        "Code Explorer",
        "Compiler",
        "Code Analysis",
        "Reviews",
        "Issues",
        "Risk Map",
        "History",
        "Settings",
    ]


def test_navigation_between_pages(window):
    for show in (
        window.show_dashboard_page,
        window.show_projects_page,
        window.show_analysis_page,
        window.show_reviews_page,
        window.show_issues_page,
        window.show_risk_map_page,
        window.show_history_page,
        window.show_settings_page,
    ):
        show()
        assert window.pages_container.currentIndex() >= 0


def test_project_pages_accept_the_active_project(window, indexed_project):
    window.current_project_id = indexed_project.id
    window.show_analysis_page()
    window.show_reviews_page()
    window.show_issues_page()
    window.show_risk_map_page()
    window.show_history_page()

    assert window.analysis_widget.current_project_id == indexed_project.id
    assert window.reviews_widget.current_project_id == indexed_project.id
    assert window.issues_widget.current_project_id == indexed_project.id


def test_pages_refresh_with_real_data(window, session_factory, indexed_project):
    AnalysisService(session_factory).run(indexed_project.id)
    ReviewService(session_factory).review_project(indexed_project.id)

    window.current_project_id = indexed_project.id
    window.show_analysis_page()
    assert window.analysis_widget.table.rowCount() > 0

    window.show_issues_page()
    window.issues_widget.load_findings()
    assert window.issues_widget.table.rowCount() > 0

    window.show_risk_map_page()
    window.risk_widget.load_risk_map()
    assert window.risk_widget.table.rowCount() > 0

    window.show_reviews_page()
    window.reviews_widget.load_latest_review()
    assert window.reviews_widget.agents_table.rowCount() == 5

    window.show_history_page()
    window.history_widget.load_history()
    assert window.history_widget.table.rowCount() == 1


def test_project_overview_page_loads(window, indexed_project):
    window.show_project_overview_page(indexed_project.id)
    assert "Project Overview" in window.overview_widget.lbl_title.text()


def test_compiler_page_reviews_and_rewrites(window):
    page = window.compiler_widget
    window.show_compiler_page()
    page.set_code("import os\ndef f(p, c=[]):\n    return eval(p)\n", "Python")
    assert page.editor_status.text().startswith("3 lines")

    review = page.playground.review_snippet(page.editor.toPlainText(), "Python")
    page._on_review_done(review)
    assert page.agents_table.rowCount() == 5
    assert page.findings_table.rowCount() > 0
    assert page.score_label.text() not in ("", "--")

    rewrite = page.playground.rewrite_snippet(page.editor.toPlainText(), "Python")
    page._on_rewrite_done(rewrite)
    assert "ast.literal_eval" in page.rewritten_view.toPlainText()
    assert "fix(es) applied" in page.rewrite_status.text()
    assert page.copy_button.isEnabled()


def test_compiler_page_compile_check(window):
    page = window.compiler_widget
    page.set_code("def broken(:\n    pass\n", "Python")
    assert page.playground.compile_check(page.editor.toPlainText(), "Python")["ok"] is False
    page.clear_editor()
    assert page.editor.toPlainText() == ""
    assert page.score_label.text() == "--"


def test_no_project_does_not_crash(window):
    window.current_project_id = None
    window.show_code_explorer_sidebar()
    assert window.placeholder_title.text() == "Code Explorer"

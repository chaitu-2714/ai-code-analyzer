import logging

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.constants import SUPPORTED_LANGUAGES
from core.exceptions import ProjectError
from database.repository import ProjectRepository
from services.ingestion import IngestionService
from ui.dialogs.import_wizard import ImportWizardDialog

logger = logging.getLogger(__name__)

class AddProjectDialog(QDialog):
    """Form Dialog to create a new project in the platform."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Project")
        self.setMinimumWidth(500)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        form = QFormLayout()
        form.setSpacing(10)

        # Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. My Web App")
        form.addRow(QLabel("Project Name:"), self.name_input)

        # Description
        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText("Brief details about this codebase...")
        self.desc_input.setMaximumHeight(80)
        form.addRow(QLabel("Description:"), self.desc_input)

        # Language Selection
        self.lang_input = QComboBox()
        self.lang_input.addItems(SUPPORTED_LANGUAGES)
        form.addRow(QLabel("Programming Language:"), self.lang_input)

        # Source Path picker
        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select codebase folder...")
        btn_browse = QPushButton("Browse...")
        btn_browse.setObjectName("SecondaryButton")
        btn_browse.clicked.connect(self.browse_folder)
        path_layout.addWidget(self.path_input)
        path_layout.addWidget(btn_browse)
        form.addRow(QLabel("Source Directory:"), path_layout)

        layout.addLayout(form)

        # Bottom buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("SecondaryButton")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("Save Project")
        btn_save.setObjectName("PrimaryButton")
        btn_save.clicked.connect(self.validate_and_save)

        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_save)
        layout.addLayout(btn_layout)

    def browse_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Codebase Directory")
        if directory:
            self.path_input.setText(directory)

    def validate_and_save(self):
        if not self.name_input.text().strip():
            QMessageBox.warning(self, "Validation Error", "Project name is required.")
            return
        self.accept()

    def get_data(self):
        return {
            "name": self.name_input.text().strip(),
            "description": self.desc_input.toPlainText().strip(),
            "language": self.lang_input.currentText(),
            "source_path": self.path_input.text().strip()
        }


class ProjectsWidget(QWidget):
    """Project management view displaying existing projects and creation options."""
    def __init__(self, project_repo: ProjectRepository, ingestion_service: IngestionService, parent=None):
        super().__init__(parent)
        self.project_repo = project_repo
        self.ingestion_service = ingestion_service
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Top Bar: Title + Add Project Button
        top_bar = QHBoxLayout()
        header = QLabel("Projects")
        header.setObjectName("PageHeader")

        btn_add = QPushButton("Create Project")
        btn_add.setObjectName("PrimaryButton")
        btn_add.clicked.connect(self.open_add_dialog)

        top_bar.addWidget(header)
        top_bar.addStretch()
        top_bar.addWidget(btn_add)
        layout.addLayout(top_bar)

        # Projects Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Language", "Path", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.refresh()

    def open_add_dialog(self):
        dialog = AddProjectDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            try:
                self.project_repo.create(
                    name=data["name"],
                    description=data["description"],
                    language=data["language"],
                    source_path=data["source_path"]
                )
                logger.info(f"Project '{data['name']}' saved successfully.")
                self.refresh()
                # If parent main window has a status bar or dashboard update trigger
                if hasattr(self.window(), "update_dashboard_kpis"):
                    self.window().update_dashboard_kpis()
            except ProjectError as e:
                QMessageBox.critical(self, "Database Error", str(e))

    def delete_project(self, project_id: int, project_name: str):
        reply = QMessageBox.question(
            self, "Delete Project",
            f"Are you sure you want to delete project '{project_name}'?\nThis action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.project_repo.delete(project_id)
                logger.info(f"Deleted project ID {project_id}.")
                self.refresh()
                if hasattr(self.window(), "update_dashboard_kpis"):
                    self.window().update_dashboard_kpis()
            except ProjectError as e:
                QMessageBox.critical(self, "Error Deleting Project", str(e))

    def open_import_wizard(self, project_id: int):
        dialog = ImportWizardDialog(self.ingestion_service, project_id, self)
        if dialog.exec() == QDialog.Accepted:
            self.refresh()
            if hasattr(self.window(), "update_dashboard_kpis"):
                self.window().update_dashboard_kpis()

    def refresh(self):
        """Loads projects from the database repository and lists them in the table."""
        try:
            projects = self.project_repo.list_all()
            self.table.setRowCount(0)

            for project in projects:
                row = self.table.rowCount()
                self.table.insertRow(row)

                self.table.setItem(row, 0, QTableWidgetItem(str(project.id)))
                self.table.setItem(row, 1, QTableWidgetItem(project.name))
                self.table.setItem(row, 2, QTableWidgetItem(project.language or "Unknown"))
                self.table.setItem(row, 3, QTableWidgetItem(project.source_path or "N/A"))

                # Action buttons group
                btn_layout = QHBoxLayout()
                btn_layout.setContentsMargins(2, 2, 2, 2)
                btn_layout.setSpacing(4)

                btn_import = QPushButton("Import")
                btn_import.setObjectName("PrimaryButton")
                btn_import.setStyleSheet("padding: 3px 6px; font-size: 11px;")
                btn_import.clicked.connect(lambda checked=False, pid=project.id: self.open_import_wizard(pid))

                btn_overview = QPushButton("Overview")
                btn_overview.setObjectName("SecondaryButton")
                btn_overview.setStyleSheet("padding: 3px 6px; font-size: 11px;")
                btn_overview.clicked.connect(
                    lambda checked=False, pid=project.id: self.window().show_project_overview_page(pid)
                    if hasattr(self.window(), "show_project_overview_page") else None
                )

                btn_explore = QPushButton("Explore")
                btn_explore.setObjectName("SecondaryButton")
                btn_explore.setStyleSheet("padding: 3px 6px; font-size: 11px;")
                btn_explore.clicked.connect(
                    lambda checked=False, pid=project.id: self.window().show_code_explorer_page(pid)
                    if hasattr(self.window(), "show_code_explorer_page") else None
                )

                btn_delete = QPushButton("Delete")
                btn_delete.setObjectName("DangerButton")
                btn_delete.setStyleSheet("padding: 3px 6px; font-size: 11px;")
                btn_delete.clicked.connect(
                    lambda checked=False, pid=project.id, pname=project.name: self.delete_project(pid, pname)
                )

                btn_layout.addWidget(btn_import)
                btn_layout.addWidget(btn_overview)
                btn_layout.addWidget(btn_explore)
                btn_layout.addWidget(btn_delete)

                cell_widget = QWidget()
                cell_widget.setLayout(btn_layout)
                self.table.setCellWidget(row, 4, cell_widget)

        except Exception as e:
            logger.error(f"Failed to refresh projects page: {e}")
            QMessageBox.critical(self, "Error Loading Projects", f"Could not fetch project list: {e}")

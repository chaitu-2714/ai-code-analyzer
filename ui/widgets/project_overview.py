import json
import logging

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from database.models import Project, ProjectFile, ProjectImport, ProjectMetadata
from database.repository import ProjectRepository

logger = logging.getLogger(__name__)

class ProjectOverviewWidget(QWidget):
    """Summarizes project files, lines, language shares, dependency imports, and duplicates."""
    def __init__(self, project_repo: ProjectRepository, parent=None):
        super().__init__(parent)
        self.project_repo = project_repo
        self.project_id = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Header Title
        self.lbl_title = QLabel("Project Overview")
        self.lbl_title.setObjectName("PageHeader")
        layout.addWidget(self.lbl_title)

        # KPIs row
        kpi_layout = QHBoxLayout()
        kpi_layout.setSpacing(15)

        self.card_files = self.create_card("Total Files", "0")
        self.card_lines = self.create_card("Total Lines", "0")
        self.card_src = self.create_card("Source Files", "0")
        self.card_test = self.create_card("Test Files", "0")

        kpi_layout.addWidget(self.card_files)
        kpi_layout.addWidget(self.card_lines)
        kpi_layout.addWidget(self.card_src)
        kpi_layout.addWidget(self.card_test)
        layout.addLayout(kpi_layout)

        # Language distribution & Duplicate detection panels
        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(20)

        # Left panel: Languages and duplicates
        left_sub = QVBoxLayout()
        left_sub.addWidget(QLabel("Language Distribution"))
        self.lang_list = QListWidget()
        self.lang_list.setMaximumHeight(150)
        left_sub.addWidget(self.lang_list)

        left_sub.addWidget(QLabel("Duplicates Detected"))
        self.dup_list = QListWidget()
        self.dup_list.setMaximumHeight(150)
        left_sub.addWidget(self.dup_list)
        lists_layout.addLayout(left_sub)

        # Right panel: External Dependencies list
        right_sub = QVBoxLayout()
        right_sub.addWidget(QLabel("Project Import Dependencies"))
        self.deps_table = QTableWidget()
        self.deps_table.setColumnCount(2)
        self.deps_table.setHorizontalHeaderLabels(["Library Name", "Language Source"])
        self.deps_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        right_sub.addWidget(self.deps_table)
        lists_layout.addLayout(right_sub)

        layout.addLayout(lists_layout)

    def create_card(self, title: str, default_value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("CardFrame")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(15, 15, 15, 15)

        lbl_title = QLabel(title)
        lbl_title.setObjectName("CardTitle")

        lbl_val = QLabel(default_value)
        lbl_val.setObjectName("CardValue")

        card_layout.addWidget(lbl_title)
        card_layout.addWidget(lbl_val)
        card.setProperty("value_label", lbl_val)
        return card

    def load_project_overview(self, project_id: int):
        """Fetches project database entries and updates all statistics dashboards."""
        self.project_id = project_id
        session_factory = self.project_repo.session_factory

        with session_factory() as session:
            # Query Project
            project = session.query(Project).filter(Project.id == project_id).first()
            if not project:
                return

            self.lbl_title.setText(f"Project Overview: {project.name}")

            # Query Metadata
            meta = session.query(ProjectMetadata).filter(ProjectMetadata.project_id == project_id).first()
            if meta:
                self.card_files.property("value_label").setText(str(meta.total_files))
                self.card_lines.property("value_label").setText(f"{meta.total_lines:,}")
                self.card_src.property("value_label").setText(str(meta.source_files))
                self.card_test.property("value_label").setText(str(meta.test_files))

                # Update Language breakdown list
                self.lang_list.clear()
                try:
                    dist = json.loads(meta.languages)
                    total = sum(dist.values())
                    for lang, count in dist.items():
                        percentage = (count / total) * 100 if total > 0 else 0
                        item = QListWidgetItem(f"{lang}: {count} files ({percentage:.1f}%)")
                        self.lang_list.addItem(item)
                except Exception:
                    pass
            else:
                self.card_files.property("value_label").setText("0")
                self.card_lines.property("value_label").setText("0")
                self.card_src.property("value_label").setText("0")
                self.card_test.property("value_label").setText("0")
                self.lang_list.clear()

            # Find duplicate files
            self.dup_list.clear()
            files = session.query(ProjectFile).filter(ProjectFile.project_id == project_id).all()

            # Map hashes to file objects
            hash_map = {}
            for f in files:
                hash_map.setdefault(f.content_hash, []).append(f)

            duplicates_found = False
            for content_hash, file_list in hash_map.items():
                if len(file_list) > 1:
                    duplicates_found = True
                    names = [f.relative_path for f in file_list]
                    item = QListWidgetItem(f"Match: {', '.join(names)} (SHA-256: {content_hash[:8]}...)")
                    self.dup_list.addItem(item)

            if not duplicates_found:
                self.dup_list.addItem("No duplicates detected.")

            # Load External Import Dependencies
            self.deps_table.setRowCount(0)
            file_ids = [f.id for f in files]
            if file_ids:
                imports = (
                    session.query(ProjectImport.import_name, ProjectFile.language)
                    .join(ProjectFile, ProjectImport.project_file_id == ProjectFile.id)
                    .filter(ProjectFile.id.in_(file_ids))
                    .distinct()
                    .all()
                )
                for imp_name, lang in imports:
                    row = self.deps_table.rowCount()
                    self.deps_table.insertRow(row)
                    self.deps_table.setItem(row, 0, QTableWidgetItem(imp_name))
                    self.deps_table.setItem(row, 1, QTableWidgetItem(lang or "Unknown"))

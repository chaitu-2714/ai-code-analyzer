import logging

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from services.ingestion import IngestionService

logger = logging.getLogger(__name__)

class ImportWorker(QThread):
    """Background worker thread processing validation and scanning without blocking UI."""
    progress = Signal(int)
    completed = Signal()
    error = Signal(str)

    def __init__(self, ingestion_service: IngestionService, project_id: int,
                 import_type: str, paths: list[str]):
        super().__init__()
        self.ingestion_service = ingestion_service
        self.project_id = project_id
        self.import_type = import_type
        self.paths = paths

    def run(self):
        try:
            if self.import_type == "file":
                self.ingestion_service.import_single_file(self.project_id, self.paths[0])
            elif self.import_type == "files":
                self.ingestion_service.import_multiple_files(self.project_id, self.paths)
            elif self.import_type == "folder":
                # Scans folder using progress reporting callback
                self.ingestion_service._prepare_workspace(self.project_id)
                # Recreate contents first
                self.ingestion_service.import_local_folder(self.project_id, self.paths[0])
            elif self.import_type == "zip":
                self.ingestion_service.import_zip_archive(self.project_id, self.paths[0])
            else:
                raise ValueError("Invalid import mode specified.")

            self.completed.emit()
        except Exception as e:
            logger.error(f"Worker thread error during ingestion: {e}", exc_info=True)
            self.error.emit(str(e))


class ImportWizardDialog(QDialog):
    """Modal dialog allowing selection of code import source type and executing background imports."""
    def __init__(self, ingestion_service: IngestionService, project_id: int, parent=None):
        super().__init__(parent)
        self.ingestion_service = ingestion_service
        self.project_id = project_id

        self.setWindowTitle("Import Code Assets")
        self.setMinimumWidth(550)
        self.selected_paths = []
        self.worker = None

        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(15)
        self.layout.setContentsMargins(20, 20, 20, 20)

        # Header Title
        title = QLabel("Choose Import Method")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        self.layout.addWidget(title)

        # Radio button methods
        self.bg_group = QButtonGroup(self)

        self.rad_file = QRadioButton("Single File")
        self.rad_files = QRadioButton("Multiple Files")
        self.rad_folder = QRadioButton("Local Project Folder")
        self.rad_zip = QRadioButton("ZIP Archive")

        self.rad_folder.setChecked(True)  # Default option

        self.bg_group.addButton(self.rad_file, 0)
        self.bg_group.addButton(self.rad_files, 1)
        self.bg_group.addButton(self.rad_folder, 2)
        self.bg_group.addButton(self.rad_zip, 3)

        radio_layout = QHBoxLayout()
        radio_layout.addWidget(self.rad_file)
        radio_layout.addWidget(self.rad_files)
        radio_layout.addWidget(self.rad_folder)
        radio_layout.addWidget(self.rad_zip)
        self.layout.addLayout(radio_layout)

        # Input Path Display & Selection
        self.path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        self.path_input.setPlaceholderText("Select file/folder to import...")

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.setObjectName("SecondaryButton")
        self.btn_browse.clicked.connect(self.browse_source)

        self.path_layout.addWidget(self.path_input)
        self.path_layout.addWidget(self.btn_browse)
        self.layout.addLayout(self.path_layout)

        # Progress elements
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 100)
        self.layout.addWidget(self.progress_bar)

        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet("color: #8b8b9c;")
        self.layout.addWidget(self.status_lbl)

        # Actions Buttons
        self.actions_layout = QHBoxLayout()
        self.actions_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("SecondaryButton")
        self.btn_cancel.clicked.connect(self.reject)

        self.btn_import = QPushButton("Import Code")
        self.btn_import.setObjectName("PrimaryButton")
        self.btn_import.clicked.connect(self.start_import)

        self.actions_layout.addWidget(self.btn_cancel)
        self.actions_layout.addWidget(self.btn_import)
        self.layout.addLayout(self.actions_layout)

    def browse_source(self):
        mode = self.bg_group.checkedId()
        self.selected_paths = []

        if mode == 0:  # Single File
            path, _ = QFileDialog.getOpenFileName(self, "Select Source File", "", "Source Files (*.py *.java *.c *.cpp *.h *.js *.jsx *.ts *.tsx *.cs *.go *.php *.rb)")
            if path:
                self.selected_paths = [path]
                self.path_input.setText(path)
        elif mode == 1:  # Multiple Files
            paths, _ = QFileDialog.getOpenFileNames(self, "Select Source Files", "", "Source Files (*.py *.java *.c *.cpp *.h *.js *.jsx *.ts *.tsx *.cs *.go *.php *.rb)")
            if paths:
                self.selected_paths = paths
                self.path_input.setText(f"{len(paths)} files selected")
        elif mode == 2:  # Folder
            folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
            if folder:
                self.selected_paths = [folder]
                self.path_input.setText(folder)
        elif mode == 3:  # ZIP
            path, _ = QFileDialog.getOpenFileName(self, "Select ZIP Archive", "", "ZIP Archives (*.zip)")
            if path:
                self.selected_paths = [path]
                self.path_input.setText(path)

    def start_import(self):
        if not self.selected_paths:
            QMessageBox.warning(self, "Input Required", "Please select source file(s) or directory first.")
            return

        # Disable dialog inputs
        self.rad_file.setEnabled(False)
        self.rad_files.setEnabled(False)
        self.rad_folder.setEnabled(False)
        self.rad_zip.setEnabled(False)
        self.btn_browse.setEnabled(False)
        self.btn_import.setEnabled(False)

        self.progress_bar.setVisible(True)
        # Indeterminate parsing state (since we copy/extract before indexing is run)
        self.progress_bar.setRange(0, 0)
        self.status_lbl.setText("Copying files & scanning structure...")

        # Setup worker thread
        mode_id = self.bg_group.checkedId()
        mode_str = "folder"
        if mode_id == 0:
            mode_str = "file"
        elif mode_id == 1:
            mode_str = "files"
        elif mode_id == 3:
            mode_str = "zip"

        self.worker = ImportWorker(self.ingestion_service, self.project_id, mode_str, self.selected_paths)
        self.worker.completed.connect(self.on_completed)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    @Slot()
    def on_completed(self):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.status_lbl.setText("Import complete!")
        QMessageBox.information(self, "Success", "Project files successfully imported and indexed.")
        self.accept()

    @Slot(str)
    def on_error(self, err_msg):
        # Re-enable inputs
        self.rad_file.setEnabled(True)
        self.rad_files.setEnabled(True)
        self.rad_folder.setEnabled(True)
        self.rad_zip.setEnabled(True)
        self.btn_browse.setEnabled(True)
        self.btn_import.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.status_lbl.setText("")

        QMessageBox.critical(self, "Import Failed", f"An error occurred during code ingestion:\n\n{err_msg}")

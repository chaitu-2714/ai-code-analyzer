import logging
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from database.models import ProjectFile
from database.repository import ProjectRepository
from ui.widgets.code_viewer import CodeViewerWidget

logger = logging.getLogger(__name__)

class CodeExplorerWidget(QWidget):
    """Combines a QTreeWidget folder structure pane and a CodeViewerWidget pane."""
    file_selected = Signal(str, str, str)  # absolute_path, relative_path, language

    def __init__(self, project_repo: ProjectRepository, parent=None):
        super().__init__(parent)
        self.project_repo = project_repo
        self.project_id = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # Horizontal Splitter between Tree and Code Viewer
        splitter = QSplitter(Qt.Horizontal)

        # Left Panel (Tree)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 5, 0)

        tree_header = QLabel("Workspace Files")
        tree_header.setStyleSheet("font-size: 13px; font-weight: bold; color: #ffffff; padding: 5px;")
        left_layout.addWidget(tree_header)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        left_layout.addWidget(self.tree)

        splitter.addWidget(left_widget)

        # Right Panel (Viewer)
        self.viewer = CodeViewerWidget()
        splitter.addWidget(self.viewer)

        # Set sizes (30% tree, 70% viewer)
        splitter.setSizes([300, 700])
        layout.addWidget(splitter)

    def load_project_workspace(self, project_id: int):
        """Builds tree nodes from the sqlite files indices."""
        self.project_id = project_id
        self.tree.clear()

        session_factory = self.project_repo.session_factory
        with session_factory() as session:
            files = (
                session.query(ProjectFile)
                .filter(ProjectFile.project_id == project_id)
                .order_by(ProjectFile.relative_path)
                .all()
            )

            # Build virtual tree hierarchy from relative paths
            root_nodes = {}
            for f in files:
                parts = f.relative_path.split(os.sep)
                if len(parts) == 1:
                    # split path might be forward slash if zip or unix source
                    parts = f.relative_path.split('/')

                current_parent = self.tree
                path_so_far = ""

                for idx, part in enumerate(parts):
                    path_so_far = os.path.join(path_so_far, part) if path_so_far else part
                    is_file = (idx == len(parts) - 1)

                    if path_so_far in root_nodes:
                        # Existing node
                        if not is_file:
                            current_parent = root_nodes[path_so_far]
                    else:
                        # Create new tree node
                        item = QTreeWidgetItem()
                        item.setText(0, part)

                        if is_file:
                            # Attach file attributes to tree item
                            item.setData(0, Qt.UserRole, {
                                "absolute_path": f.absolute_path,
                                "relative_path": f.relative_path,
                                "language": f.language
                            })
                            # Monospace style for files
                            item.setFont(0, self.viewer.editor.font())
                        else:
                            # Folder node styling/expands
                            item.setForeground(0, Qt.white)

                        if current_parent == self.tree:
                            self.tree.addTopLevelItem(item)
                        else:
                            current_parent.addChild(item)

                        if not is_file:
                            root_nodes[path_so_far] = item
                            current_parent = item

            # Expand root nodes initially
            self.tree.expandAll()

    def on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Triggers CodeViewer loading when a file node is double-clicked."""
        data = item.data(0, Qt.UserRole)
        if data:
            abs_path = data["absolute_path"]
            rel_path = data["relative_path"]
            lang = data["language"]

            # Load in our right-hand viewer pane
            self.viewer.load_file(abs_path, rel_path, lang)
            # Emit globally in case main window wants to listen
            self.file_selected.emit(abs_path, rel_path, lang)

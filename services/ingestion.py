import json
import logging
import os
import shutil
import zipfile

from analyzer.import_parser import extract_imports
from core.timeutils import utcnow
from database.models import Project, ProjectFile, ProjectImport, ProjectMetadata
from utils.file_validator import get_max_files_limit, get_zip_size_limit, is_path_safe, validate_source_file
from utils.language_detector import detect_language
from utils.metadata_extractor import extract_file_metrics
from utils.project_scanner import scan_project_directory

logger = logging.getLogger(__name__)

class IngestionService:
    """Orchestrates importing code assets, validation, extraction, metadata parsing, and DB indexing."""
    def __init__(self, session_factory, workspace_base_dir: str = "data/workspaces"):
        self.session_factory = session_factory
        self.workspace_base_dir = workspace_base_dir

    def get_workspace_path(self, project_id: int) -> str:
        """Returns isolated workspace folder for a given project ID."""
        return os.path.abspath(os.path.join(self.workspace_base_dir, str(project_id)))

    def _prepare_workspace(self, project_id: int) -> str:
        """Creates directory for project code files, clearing old content if present."""
        path = self.get_workspace_path(project_id)
        if os.path.exists(path):
            shutil.rmtree(path)
        os.makedirs(path, exist_ok=True)
        return path

    def import_single_file(self, project_id: int, source_path: str) -> bool:
        """Imports a single source file into the project database and workspace."""
        is_valid, err = validate_source_file(source_path)
        if not is_valid:
            logger.warning(f"File validation failed: {err}")
            raise ValueError(err)

        workspace_dir = self._prepare_workspace(project_id)
        file_name = os.path.basename(source_path)
        dest_path = os.path.join(workspace_dir, file_name)

        shutil.copy2(source_path, dest_path)
        return self.index_project_workspace(project_id, workspace_dir)

    def import_multiple_files(self, project_id: int, file_paths: list[str]) -> bool:
        """Imports multiple files into the project workspace and indexes them."""
        workspace_dir = self._prepare_workspace(project_id)

        # Verify total files count
        if len(file_paths) > get_max_files_limit():
            raise ValueError(f"Number of files ({len(file_paths)}) exceeds limit ({get_max_files_limit()}).")

        for path in file_paths:
            is_valid, _err = validate_source_file(path)
            if not is_valid:
                continue # Skip invalid files rather than failing the whole import

            dest_path = os.path.join(workspace_dir, os.path.basename(path))
            shutil.copy2(path, dest_path)

        return self.index_project_workspace(project_id, workspace_dir)

    def import_zip_archive(self, project_id: int, zip_path: str) -> bool:
        """Securely extracts a ZIP file to the project workspace and indexes it."""
        if not os.path.exists(zip_path):
            raise FileNotFoundError("ZIP file does not exist.")

        # Check zip size
        if os.path.getsize(zip_path) > get_zip_size_limit():
            raise ValueError("ZIP archive exceeds configured size limit.")

        workspace_dir = self._prepare_workspace(project_id)

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Count files first
                infolist = zip_ref.infolist()
                if len(infolist) > get_max_files_limit():
                    raise ValueError(f"ZIP contains too many files ({len(infolist)}). Limit is {get_max_files_limit()}.")

                for member in infolist:
                    # Target path for extraction
                    target_path = os.path.join(workspace_dir, member.filename)

                    # Security Check: Prevent path traversal outside project workspace
                    if not is_path_safe(target_path, workspace_dir):
                        logger.warning(f"Malicious path traversal rejected in zip: {member.filename}")
                        continue

                    # Skip directories or extract safely
                    if member.is_dir():
                        os.makedirs(target_path, exist_ok=True)
                    else:
                        # Ensure output folder exists
                        os.makedirs(os.path.dirname(target_path), exist_ok=True)
                        with zip_ref.open(member) as source, open(target_path, "wb") as target:
                            shutil.copyfileobj(source, target)
        except zipfile.BadZipFile:
            raise ValueError("Corrupted or invalid ZIP archive file.") from None
        except Exception as e:
            logger.error(f"ZIP import failed: {e}")
            raise ValueError(f"Failed to extract ZIP archive: {e}") from e

        return self.index_project_workspace(project_id, workspace_dir)

    def import_local_folder(self, project_id: int, folder_path: str) -> bool:
        """Copies an existing local folder's contents into the workspace and indexes it."""
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise ValueError("Selected folder path is invalid or does not exist.")

        workspace_dir = self._prepare_workspace(project_id)

        # Recursively copy directory tree
        try:
            # Simple recursive copy ignoring standard build/vcs artifacts
            from utils.project_scanner import DEFAULT_IGNORE_DIRS

            def ignore_patterns(dirpath, contents):
                # Filter folder names matching ignored dirs
                ignored = []
                for item in contents:
                    if item in DEFAULT_IGNORE_DIRS:
                        ignored.append(item)
                return ignored

            # Copy to workspace
            # We recreate folders preserving structure
            for root, dirs, files in os.walk(folder_path):
                # Prune in place
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS]

                for file in files:
                    src_file = os.path.join(root, file)
                    rel_path = os.path.relpath(src_file, folder_path)
                    dest_file = os.path.join(workspace_dir, rel_path)

                    # Ensure folder structure exists
                    os.makedirs(os.path.dirname(dest_file), exist_ok=True)
                    shutil.copy2(src_file, dest_file)
        except Exception as e:
            logger.error(f"Folder copy failed: {e}")
            raise ValueError(f"Failed to copy folder contents: {e}") from e

        return self.index_project_workspace(project_id, workspace_dir)

    def index_project_workspace(self, project_id: int, workspace_dir: str, progress_callback=None) -> bool:
        """Scans the local workspace directory, parses file metrics, and stores all indices in DB.

        Can report progress via a callback function for long scanning jobs.
        """
        with self.session_factory() as session:
            try:
                # 1. Verify Project exists
                project = session.query(Project).filter(Project.id == project_id).first()
                if not project:
                    raise ValueError(f"Project ID {project_id} does not exist.")

                # 2. Clear old files for this project to support re-indexing
                session.query(ProjectFile).filter(ProjectFile.project_id == project_id).delete()
                session.query(ProjectMetadata).filter(ProjectMetadata.project_id == project_id).delete()

                # Update source_path of project record
                project.source_path = workspace_dir
                session.commit()

                # 3. Scan workspace
                scanned = scan_project_directory(workspace_dir)
                total_files = len(scanned)
                logger.info(f"Workspace scan complete. Found {total_files} files.")

                source_count = 0
                test_count = 0
                total_lines = 0
                lang_distribution = {}  # lang -> file count

                # Check maximum file count limit
                if total_files > get_max_files_limit():
                     raise ValueError(f"Project contains too many files ({total_files}). Limit is {get_max_files_limit()}.")

                for i, file_info in enumerate(scanned):
                    # Call progress update if provided
                    if progress_callback:
                        progress_callback(int((i / total_files) * 100))

                    abs_path = file_info["absolute_path"]
                    rel_path = file_info["relative_path"]

                    # Validate content & safety of file
                    is_valid, _ = validate_source_file(abs_path)
                    if not is_valid:
                        # Skip files that fail size/binary validation during indexing
                        continue

                    # Language detection
                    lang = detect_language(abs_path)
                    lang_distribution[lang] = lang_distribution.get(lang, 0) + 1

                    # Extract line counts
                    metrics = extract_file_metrics(abs_path, lang)

                    is_src = file_info["is_source"]
                    is_tst = file_info["is_test"]

                    if is_src:
                        source_count += 1
                    if is_tst:
                        test_count += 1
                    total_lines += metrics["line_count"]

                    # Create DB File Record
                    db_file = ProjectFile(
                        project_id=project_id,
                        relative_path=rel_path,
                        absolute_path=abs_path,
                        file_name=file_info["file_name"],
                        extension=file_info["extension"],
                        language=lang,
                        file_size=file_info["file_size"],
                        line_count=metrics["line_count"],
                        non_empty_lines=metrics["non_empty_lines"],
                        comment_lines=metrics["comment_lines"],
                        blank_lines=metrics["blank_lines"],
                        is_test_file=1 if is_tst else 0,
                        is_source_file=1 if is_src else 0,
                        content_hash=file_info["content_hash"]
                    )
                    session.add(db_file)
                    session.flush()  # Flushes to generate db_file.id

                    # Parse and Save Imports
                    try:
                        with open(abs_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                        extracted_imps = extract_imports(content, lang)
                        for imp_name in extracted_imps:
                            db_imp = ProjectImport(
                                project_file_id=db_file.id,
                                import_name=imp_name,
                                import_type="external"
                            )
                            session.add(db_imp)
                    except Exception as e:
                        logger.warning(f"Failed to parse imports for {rel_path}: {e}")

                # Save metadata summary
                metadata = ProjectMetadata(
                    project_id=project_id,
                    total_files=total_files,
                    source_files=source_count,
                    test_files=test_count,
                    languages=json.dumps(lang_distribution),
                    total_lines=total_lines,
                    last_indexed_at=utcnow()
                )
                session.add(metadata)
                session.commit()

                logger.info(f"Successfully indexed project ID {project_id}.")
                return True
            except Exception:
                session.rollback()
                logger.exception("Failed to index workspace")
                raise

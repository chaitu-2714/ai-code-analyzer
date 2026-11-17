from typing import List, Optional

from sqlalchemy import func

from core.exceptions import ProjectError
from core.timeutils import utcnow
from database.models import Project, ReviewSession


class ProjectRepository:
    """Repository handles database CRUD for Projects."""
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def create(self, name: str, description: Optional[str] = None,
               language: Optional[str] = None, source_path: Optional[str] = None) -> Project:
        if not name or not name.strip():
            raise ProjectError("Project name cannot be empty.")

        with self.session_factory() as session:
            try:
                project = Project(
                    name=name,
                    description=description,
                    language=language,
                    source_path=source_path
                )
                session.add(project)
                session.commit()
                # Refresh attaches state to the detached instance before returning
                session.refresh(project)
                return project
            except Exception as e:
                session.rollback()
                raise ProjectError(f"Failed to create project: {e}") from e

    def get_by_id(self, project_id: int) -> Optional[Project]:
        with self.session_factory() as session:
            return session.query(Project).filter(Project.id == project_id).first()

    def list_all(self) -> List[Project]:
        with self.session_factory() as session:
            # We eager load or fetch all directly
            return session.query(Project).order_by(Project.created_at.desc()).all()

    def delete(self, project_id: int) -> bool:
        with self.session_factory() as session:
            try:
                project = session.query(Project).filter(Project.id == project_id).first()
                if project:
                    session.delete(project)
                    session.commit()
                    return True
                return False
            except Exception as e:
                session.rollback()
                raise ProjectError(f"Failed to delete project {project_id}: {e}") from e

    def count(self) -> int:
        with self.session_factory() as session:
            return session.query(func.count(Project.id)).scalar() or 0


class ReviewSessionRepository:
    """Repository handles database CRUD for ReviewSessions."""
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def create(self, project_id: int, status: str = "pending",
               overall_score: Optional[float] = None) -> ReviewSession:
        with self.session_factory() as session:
            try:
                db_session = ReviewSession(
                    project_id=project_id,
                    status=status,
                    overall_score=overall_score,
                    created_at=utcnow()
                )
                session.add(db_session)
                session.commit()
                session.refresh(db_session)
                return db_session
            except Exception as e:
                session.rollback()
                raise ProjectError(f"Failed to create review session: {e}") from e

    def list_by_project(self, project_id: int) -> List[ReviewSession]:
        with self.session_factory() as session:
            return session.query(ReviewSession).filter(ReviewSession.project_id == project_id).all()

    def count(self) -> int:
        with self.session_factory() as session:
            return session.query(func.count(ReviewSession.id)).scalar() or 0

    def get_average_score(self) -> Optional[float]:
        with self.session_factory() as session:
            score = session.query(func.avg(ReviewSession.overall_score)).scalar()
            return round(score, 2) if score is not None else None

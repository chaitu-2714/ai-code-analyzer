"""SQLAlchemy ORM models for the AI Code Review & Automated Repair Platform.

A single declarative ``Base`` is shared by every table.  The schema covers all
delivered phases:

* Phase 1 - projects, project files, imports, metadata
* Phase 2 - structural index (functions / classes stored on files)
* Phase 3 - analysis runs, findings, code metrics, duplicate groups, dependencies
* Phase 5 - review sessions and per-agent review scores
* Phase 6/7 - repair suggestions and their verification results
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship

from core.timeutils import utcnow as _utcnow

Base = declarative_base()


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    language = Column(String(50), nullable=True)
    source_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    sessions = relationship(
        "ReviewSession", back_populates="project", cascade="all, delete-orphan"
    )
    files = relationship(
        "ProjectFile", back_populates="project", cascade="all, delete-orphan"
    )
    metadata_records = relationship(
        "ProjectMetadata", back_populates="project", cascade="all, delete-orphan"
    )
    analysis_runs = relationship(
        "AnalysisRun", back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Project(name='{self.name}', language='{self.language}')>"


class ReviewSession(Base):
    __tablename__ = "review_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    analysis_run_id = Column(
        Integer, ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    overall_score = Column(Float, nullable=True)
    risk_level = Column(String(20), nullable=True)  # LOW, MODERATE, HIGH, CRITICAL
    summary = Column(Text, nullable=True)
    provider = Column(String(50), nullable=True)  # local, gemini
    created_at = Column(DateTime, default=_utcnow)
    completed_at = Column(DateTime, nullable=True)

    project = relationship("Project", back_populates="sessions")
    agent_reviews = relationship(
        "AgentReview", back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<ReviewSession(id={self.id}, project_id={self.project_id}, "
            f"status='{self.status}')>"
        )


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    relative_path = Column(String(500), nullable=False)
    absolute_path = Column(String(500), nullable=False)
    file_name = Column(String(200), nullable=False)
    extension = Column(String(20), nullable=True)
    language = Column(String(50), nullable=True)
    file_size = Column(Integer, default=0)
    line_count = Column(Integer, default=0)
    non_empty_lines = Column(Integer, default=0)
    comment_lines = Column(Integer, default=0)
    blank_lines = Column(Integer, default=0)
    is_test_file = Column(Boolean, default=False)
    is_source_file = Column(Boolean, default=True)
    content_hash = Column(String(64), nullable=False)  # SHA-256 hash
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    project = relationship("Project", back_populates="files")
    imports = relationship(
        "ProjectImport", back_populates="project_file", cascade="all, delete-orphan"
    )
    findings = relationship(
        "Finding", back_populates="file", cascade="all, delete-orphan"
    )
    metrics = relationship(
        "CodeMetric", back_populates="file", uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<ProjectFile(name='{self.file_name}', language='{self.language}')>"


class ProjectImport(Base):
    __tablename__ = "project_imports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_file_id = Column(
        Integer, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    import_name = Column(String(200), nullable=False)
    import_type = Column(String(50), default="external")  # external, local
    created_at = Column(DateTime, default=_utcnow)

    project_file = relationship("ProjectFile", back_populates="imports")

    def __repr__(self):
        return f"<ProjectImport(name='{self.import_name}')>"


class ProjectMetadata(Base):
    __tablename__ = "project_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    total_files = Column(Integer, default=0)
    source_files = Column(Integer, default=0)
    test_files = Column(Integer, default=0)
    languages = Column(Text, default="{}")  # JSON encoded string for portability
    total_lines = Column(Integer, default=0)
    last_indexed_at = Column(DateTime, default=_utcnow)

    project = relationship("Project", back_populates="metadata_records")

    def __repr__(self):
        return f"<ProjectMetadata(project_id={self.project_id}, files={self.total_files})>"


# ---------------------------------------------------------------------------
# Phase 3 - static analysis models
# ---------------------------------------------------------------------------


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String(20), default="QUEUED")  # QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    files_analyzed = Column(Integer, default=0)
    findings_count = Column(Integer, default=0)
    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)

    project = relationship("Project", back_populates="analysis_runs")
    findings = relationship(
        "Finding", back_populates="analysis_run", cascade="all, delete-orphan"
    )
    metrics = relationship(
        "CodeMetric", back_populates="analysis_run", cascade="all, delete-orphan"
    )
    duplicate_groups = relationship(
        "DuplicateGroup", back_populates="analysis_run", cascade="all, delete-orphan"
    )
    dependencies = relationship(
        "Dependency", back_populates="analysis_run", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<AnalysisRun(id={self.id}, project_id={self.project_id}, "
            f"status='{self.status}')>"
        )


class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_run_id = Column(
        Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_id = Column(
        Integer, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    rule_id = Column(String(50), nullable=True)
    category = Column(String(30), nullable=False)  # SYNTAX, BUG, SECURITY, ...
    severity = Column(String(20), nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    file_path = Column(String(500), nullable=False)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    column_start = Column(Integer, nullable=True)
    column_end = Column(Integer, nullable=True)
    code_snippet = Column(Text, nullable=True)
    suggestion = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    detector = Column(String(100), nullable=True)
    status = Column(String(20), default="OPEN")  # OPEN, CONFIRMED, FALSE_POSITIVE, RESOLVED, IGNORED
    created_at = Column(DateTime, default=_utcnow)

    analysis_run = relationship("AnalysisRun", back_populates="findings")
    file = relationship("ProjectFile", back_populates="findings")
    project = relationship("Project")
    repairs = relationship(
        "RepairSuggestion", back_populates="finding", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return (
            f"<Finding(id={self.id}, category='{self.category}', "
            f"severity='{self.severity}')>"
        )


class CodeMetric(Base):
    __tablename__ = "code_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_run_id = Column(
        Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    file_id = Column(Integer, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False)
    lines_of_code = Column(Integer, default=0)
    blank_lines = Column(Integer, default=0)
    comment_lines = Column(Integer, default=0)
    function_count = Column(Integer, default=0)
    class_count = Column(Integer, default=0)
    average_complexity = Column(Float, default=0.0)
    max_complexity = Column(Integer, default=0)
    maintainability_index = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    analysis_run = relationship("AnalysisRun", back_populates="metrics")
    file = relationship("ProjectFile", back_populates="metrics")

    def __repr__(self):
        return f"<CodeMetric(file_id={self.file_id}, loc={self.lines_of_code})>"


class DuplicateGroup(Base):
    __tablename__ = "duplicate_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_run_id = Column(
        Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    similarity = Column(String(20), nullable=False)  # Exact, NearExact
    line_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    analysis_run = relationship("AnalysisRun", back_populates="duplicate_groups")
    instances = relationship(
        "DuplicateInstance", back_populates="group", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<DuplicateGroup(id={self.id}, similarity='{self.similarity}')>"


class DuplicateInstance(Base):
    __tablename__ = "duplicate_instances"

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(
        Integer, ForeignKey("duplicate_groups.id", ondelete="CASCADE"), nullable=False
    )
    file_id = Column(
        Integer, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False
    )
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)
    code_hash = Column(String(64), nullable=False)

    group = relationship("DuplicateGroup", back_populates="instances")
    file = relationship("ProjectFile")

    def __repr__(self):
        return f"<DuplicateInstance(group_id={self.group_id}, file_id={self.file_id})>"


class Dependency(Base):
    __tablename__ = "dependencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    analysis_run_id = Column(
        Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    file_id = Column(Integer, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False)
    imported_module = Column(String(200), nullable=False)
    import_type = Column(String(50), nullable=False)  # external, local, stdlib, missing
    is_missing = Column(Boolean, default=False)
    is_circular = Column(Boolean, default=False)

    analysis_run = relationship("AnalysisRun", back_populates="dependencies")
    file = relationship("ProjectFile")

    def __repr__(self):
        return f"<Dependency(file_id={self.file_id}, module='{self.imported_module}')>"


# ---------------------------------------------------------------------------
# Phase 5 - multi-agent review models
# ---------------------------------------------------------------------------


class AgentReview(Base):
    __tablename__ = "agent_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    review_session_id = Column(
        Integer, ForeignKey("review_sessions.id", ondelete="CASCADE"), nullable=False
    )
    agent_name = Column(String(60), nullable=False)
    score = Column(Float, nullable=True)
    weight = Column(Float, default=0.0)
    status = Column(String(20), default="COMPLETED")
    summary = Column(Text, nullable=True)
    insights = Column(Text, nullable=True)  # JSON encoded list of strings
    findings_count = Column(Integer, default=0)
    critical_count = Column(Integer, default=0)
    high_count = Column(Integer, default=0)
    llm_used = Column(Boolean, default=False)
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    session = relationship("ReviewSession", back_populates="agent_reviews")

    def __repr__(self):
        return f"<AgentReview(agent='{self.agent_name}', score={self.score})>"


# ---------------------------------------------------------------------------
# Phase 6/7 - automated repair and verification models
# ---------------------------------------------------------------------------


class RepairSuggestion(Base):
    __tablename__ = "repair_suggestions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    finding_id = Column(
        Integer, ForeignKey("findings.id", ondelete="CASCADE"), nullable=False
    )
    rule_id = Column(String(50), nullable=True)
    strategy = Column(String(60), nullable=True)  # template, llm, manual
    explanation = Column(Text, nullable=True)
    original_code = Column(Text, nullable=True)
    patched_code = Column(Text, nullable=True)
    diff = Column(Text, nullable=True)
    confidence = Column(Float, default=0.0)
    status = Column(String(20), default="SUGGESTED")  # SUGGESTED, APPLIED, REJECTED
    applied_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    finding = relationship("Finding", back_populates="repairs")
    verifications = relationship(
        "VerificationResult", back_populates="repair", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<RepairSuggestion(id={self.id}, rule='{self.rule_id}', confidence={self.confidence})>"


class VerificationResult(Base):
    __tablename__ = "verification_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repair_id = Column(
        Integer, ForeignKey("repair_suggestions.id", ondelete="CASCADE"), nullable=False
    )
    passed = Column(Boolean, default=False)
    syntax_ok = Column(Boolean, default=False)
    tests_ok = Column(Boolean, nullable=True)
    checks = Column(Text, nullable=True)  # JSON encoded list of check results
    output = Column(Text, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    repair = relationship("RepairSuggestion", back_populates="verifications")

    def __repr__(self):
        return f"<VerificationResult(repair_id={self.repair_id}, passed={self.passed})>"

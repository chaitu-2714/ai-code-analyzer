"""Headless command line interface.

Useful for CI pipelines and for machines without a display server::

    python run.py analyze ./my_project
    python run.py review ./my_project --report review.md
    python run.py review --project 3 --diff changes.diff
    python run.py fix --project 3 --apply --verify
    python run.py rules
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Dict, List, Optional

from core.config import Config
from core.exceptions import ApplicationError
from core.logger import setup_logger
from database.connection import DatabaseManager
from database.repository import ProjectRepository
from repair.engine import RepairEngine
from reports.generator import ReportGenerator
from services.analysis_service import AnalysisService
from services.ingestion import IngestionService
from services.playground_service import PlaygroundService
from services.review_service import ReviewService
from verification.verifier import FixVerifier

logger = logging.getLogger(__name__)


class _Services:
    """Small container so every command shares one initialisation path."""

    def __init__(self, config: Config):
        self.config = config
        self.db = DatabaseManager(config.database_url)
        self.db.initialize()
        self.session_factory = self.db._session_factory
        self.projects = ProjectRepository(self.session_factory)
        self.ingestion = IngestionService(self.session_factory)
        self.analysis = AnalysisService(self.session_factory, config)
        self.review = ReviewService(self.session_factory, config, analysis_service=self.analysis)
        self.repairs = RepairEngine(self.session_factory, config=config)
        self.verifier = FixVerifier(self.session_factory, config)
        self.playground = PlaygroundService(config)
        self.reports = ReportGenerator(
            self.session_factory, review_service=self.review, analysis_service=self.analysis
        )


def _resolve_project(services: _Services, args) -> int:
    """Returns the project id from ``--project`` or by importing ``--path``."""
    if getattr(args, "project", None):
        project = services.projects.get_by_id(int(args.project))
        if project is None:
            raise ApplicationError(f"Project {args.project} does not exist.")
        return int(project.id)

    path = getattr(args, "path", None)
    if not path:
        raise ApplicationError("Provide either --project <id> or a path to a folder/zip.")
    if not os.path.exists(path):
        raise ApplicationError(f"Path does not exist: {path}")

    name = getattr(args, "name", None) or os.path.basename(os.path.abspath(path)) or "Imported project"
    project = services.projects.create(name=name, language=getattr(args, "language", None))
    if os.path.isdir(path):
        ok = services.ingestion.import_local_folder(project.id, path)
    else:
        ok = services.ingestion.import_zip_archive(project.id, path)
    if not ok:
        raise ApplicationError(f"Could not import {path}.")
    services.ingestion.index_project_workspace(
        project.id, services.ingestion.get_workspace_path(project.id)
    )
    print(f"Imported '{name}' as project #{project.id}.")
    return int(project.id)


def _print_analysis(summary: Dict[str, object]) -> None:
    counts = summary.get("severity_counts") or {}
    print(
        "Analysis complete: {files} file(s), {findings} finding(s), {dups} duplicate block(s), "
        "{duration}s".format(
            files=summary.get("files_analyzed", 0),
            findings=summary.get("findings", 0),
            dups=summary.get("duplicate_groups", 0),
            duration=summary.get("duration_seconds", 0),
        )
    )
    print(
        "  severity: "
        + ", ".join(f"{name}={counts.get(name, 0)}" for name in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"))
    )
    metrics = summary.get("metrics") or {}
    if metrics:
        print(
            "  metrics: LOC={loc}, functions={fn}, avg complexity={cx}, maintainability={mi}".format(
                loc=metrics.get("lines_of_code"),
                fn=metrics.get("function_count"),
                cx=metrics.get("average_complexity"),
                mi=metrics.get("maintainability_index"),
            )
        )


def _print_review(result: Dict[str, object]) -> None:
    print(
        "Review #{session} - score {score}/100, risk {risk}, {findings} finding(s), provider {provider}".format(
            session=result.get("session_id"),
            score=result.get("overall_score"),
            risk=result.get("risk_level"),
            findings=result.get("total_findings"),
            provider=result.get("provider"),
        )
    )
    for agent in result.get("agents", []):  # type: ignore[union-attr]
        print(
            "  {name:28s} {score:>5} /100  findings={count:<3} critical={crit} high={high}".format(
                name=str(agent.get("agent_name")),
                score=agent.get("score"),
                count=agent.get("findings_count"),
                crit=agent.get("critical_count"),
                high=agent.get("high_count"),
            )
        )
        for insight in agent.get("insights") or []:  # type: ignore[union-attr]
            print(f"      - {insight}")
    if result.get("summary"):
        print(f"  summary: {result['summary']}")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_analyze(services: _Services, args) -> int:
    project_id = _resolve_project(services, args)
    summary = services.analysis.run(project_id)
    _print_analysis(summary)
    findings = services.analysis.findings(project_id, run_id=int(summary["run_id"]))
    limit = int(getattr(args, "limit", 20) or 20)
    for finding in findings[:limit]:
        print(
            "  [{severity}] {rule} {path}:{line} - {title}".format(
                severity=finding["severity"],
                rule=finding["rule_id"],
                path=finding["file_path"],
                line=finding["line_start"],
                title=finding["title"],
            )
        )
    return 0


def cmd_review(services: _Services, args) -> int:
    project_id = _resolve_project(services, args)
    diff_text = None
    if getattr(args, "diff", None):
        with open(args.diff, "r", encoding="utf-8", errors="ignore") as handle:
            diff_text = handle.read()
    result = services.review.review_project(
        project_id,
        provider_mode=getattr(args, "provider", None),
        diff_text=diff_text,
    )
    _print_review(result)
    if getattr(args, "report", None):
        path = services.reports.export(
            int(result["session_id"]), args.report, getattr(args, "format", None)
        )
        print(f"Report written to {path}")
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_report(services: _Services, args) -> int:
    project_id = _resolve_project(services, args)
    review = services.review.latest_review(project_id)
    if not review:
        raise ApplicationError("No review found for this project; run `review` first.")
    content = services.reports.generate_report(int(review["session_id"]), args.format)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(content)
        print(f"Report written to {args.out}")
    else:
        print(content)
    return 0


def cmd_fix(services: _Services, args) -> int:
    project_id = _resolve_project(services, args)
    run = services.analysis.latest_run(project_id)
    if not run:
        raise ApplicationError("No analysis run found; run `analyze` first.")
    suggestions = services.repairs.suggest_for_run(
        int(run["run_id"]), limit=int(args.limit), severities=args.severity
    )
    auto = [item for item in suggestions if item.get("can_apply")]
    manual = [item for item in suggestions if not item.get("can_apply")]
    print(f"{len(suggestions)} suggestion(s): {len(auto)} auto-patchable, {len(manual)} manual.")
    for item in suggestions:
        print(
            "  #{id} {rule} [{strategy}] confidence={conf} - {explanation}".format(
                id=item["repair_id"],
                rule=item["rule_id"],
                strategy=item["strategy"],
                conf=item["confidence"],
                explanation=(item["explanation"] or "")[:100],
            )
        )
    if args.apply:
        applied = 0
        for item in auto:
            if args.verify:
                outcome = services.verifier.verify_repair(int(item["repair_id"]))
                if not outcome.get("passed"):
                    print(f"  skipping #{item['repair_id']}: verification failed")
                    continue
            services.repairs.apply(int(item["repair_id"]))
            applied += 1
        print(f"Applied {applied} patch(es) (a .bak backup was written next to each file).")
    return 0


def cmd_rewrite(services: _Services, args) -> int:
    """Reviews a single file (or stdin) and prints the rewritten code."""
    if args.file == "-":
        code = sys.stdin.read()
        name = args.name or "snippet.py"
    else:
        if not os.path.exists(args.file):
            raise ApplicationError(f"File does not exist: {args.file}")
        with open(args.file, "r", encoding="utf-8", errors="ignore") as handle:
            code = handle.read()
        name = args.name or os.path.basename(args.file)

    language = args.language
    result = services.playground.rewrite_snippet(
        code, language=language, filename=name, use_llm=args.llm
    )

    before, after = result["before"], result["after"]
    print(
        f"{name}: {len(result['applied'])} fix(es) applied, "
        f"score {before['overall_score']} -> {after['overall_score']}, "
        f"risk {before['risk_level']} -> {after['risk_level']}, "
        f"{'compiles' if result['compile']['ok'] else 'DOES NOT COMPILE'}"
    )
    for item in result["applied"]:
        print(f"  + {item['rule_id']} line {item['line']}: {item['explanation'][:90]}")
    for note in result["notes"]:
        print(f"  * {note}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(result["rewritten_code"])
        print(f"Rewritten code written to {args.out}")
    elif args.diff:
        print(result["diff"] or "(no changes)")
    else:
        print(result["rewritten_code"])
    return 0


def cmd_rules(services: _Services, args) -> int:
    from analyzer.rules import all_rules

    for rule in all_rules():
        print(f"{rule.id:8s} {rule.severity_value:9s} {rule.category_value:14s} {rule.title}")
    print(f"\n{len(all_rules())} rules registered.")
    return 0


def cmd_agents(services: _Services, args) -> int:
    from agents.orchestrator import AgentOrchestrator

    orchestrator = AgentOrchestrator(provider=services.review.provider)
    for agent in orchestrator.describe_agents():
        print(
            f"{agent['agent_name']:30s} weight={agent['weight']}  categories={','.join(agent['categories'])}"
        )
        print(f"    {agent['description']}")
    return 0


COMMANDS = {
    "analyze": cmd_analyze,
    "rewrite": cmd_rewrite,
    "review": cmd_review,
    "report": cmd_report,
    "fix": cmd_fix,
    "rules": cmd_rules,
    "agents": cmd_agents,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="AI Code Reviewer - headless mode (no GUI required).",
    )
    parser.add_argument("--env", default=None, help="Path to the .env file")
    parser.add_argument("--db", default=None, help="Override DATABASE_URL for this run")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub, path_required: bool = False):
        sub.add_argument("path", nargs="?" if not path_required else None, help="Folder or zip to import")
        sub.add_argument("--project", type=int, help="Existing project id")
        sub.add_argument("--name", help="Project name when importing a path")
        sub.add_argument("--language", help="Language label for a new project")

    analyze = subparsers.add_parser("analyze", help="Run static analysis")
    add_common(analyze)
    analyze.add_argument("--limit", type=int, default=20, help="Findings to print")

    review = subparsers.add_parser("review", help="Run the multi-agent review")
    add_common(review)
    review.add_argument("--diff", help="Only review findings inside this unified diff")
    review.add_argument("--report", help="Write a report to this path")
    review.add_argument("--format", default=None, choices=["markdown", "html", "json"])
    review.add_argument("--provider", default=None, choices=["auto", "local", "gemini"])
    review.add_argument("--json", action="store_true", help="Print the full JSON payload")

    report = subparsers.add_parser("report", help="Render the latest review report")
    add_common(report)
    report.add_argument("--format", default="markdown", choices=["markdown", "html", "json"])
    report.add_argument("--out", help="Write to a file instead of stdout")

    fix = subparsers.add_parser("fix", help="Suggest (and optionally apply) repairs")
    add_common(fix)
    fix.add_argument("--limit", type=int, default=20)
    fix.add_argument("--severity", action="append", help="Restrict to a severity (repeatable)")
    fix.add_argument("--apply", action="store_true", help="Write the patches to disk")
    fix.add_argument("--verify", action="store_true", help="Verify before applying")

    rewrite = subparsers.add_parser(
        "rewrite", help="Review one file (or stdin) and print the rewritten code"
    )
    rewrite.add_argument("file", help="Path to a source file, or - to read stdin")
    rewrite.add_argument("--out", help="Write the rewritten code to this path")
    rewrite.add_argument("--diff", action="store_true", help="Print a unified diff instead of the code")
    rewrite.add_argument("--name", help="Filename to assume for the snippet")
    rewrite.add_argument("--language", help="Force a language instead of auto-detecting")
    rewrite.add_argument("--llm", action="store_true", help="Also ask the LLM for a full rewrite")

    subparsers.add_parser("rules", help="List every registered rule")
    subparsers.add_parser("agents", help="List the review agents")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    config = Config(args.env)
    if args.db:
        config.database_url = args.db
    setup_logger(config.log_level, config.log_file)

    try:
        services = _Services(config)
        return COMMANDS[args.command](services, args)
    except ApplicationError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # pragma: no cover - defensive
        logger.exception("Command failed")
        print(f"Unexpected error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

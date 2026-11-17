"""Shared insight helpers: deterministic summaries plus optional LLM enrichment."""
from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List, Optional, Sequence

from analyzer.rules.base import SEVERITY_RANK, get_rule

_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def parse_insight_list(text: str, limit: int = 5) -> List[str]:
    """Extracts a list of short insight strings from an LLM response."""
    cleaned = _FENCE.sub("", text or "").strip()
    if not cleaned:
        return []
    for candidate in (cleaned, _slice_json(cleaned)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            payload = payload.get("insights") or payload.get("findings") or []
        if isinstance(payload, list):
            return [str(item).strip() for item in payload if str(item).strip()][:limit]
    # Fall back to plain lines / bullets.
    lines = [
        re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
        for line in cleaned.splitlines()
        if line.strip()
    ]
    return [line for line in lines if len(line) > 8][:limit]


def _slice_json(text: str) -> str:
    start = min((i for i in (text.find("["), text.find("{")) if i >= 0), default=-1)
    if start < 0:
        return ""
    end = max(text.rfind("]"), text.rfind("}"))
    return text[start : end + 1] if end > start else ""


def group_findings(findings: Sequence[Dict[str, object]]) -> Dict[str, List[Dict[str, object]]]:
    grouped: Dict[str, List[Dict[str, object]]] = {}
    for finding in findings:
        grouped.setdefault(str(finding.get("rule_id") or "UNKNOWN"), []).append(finding)
    return grouped


def local_insights(
    agent_name: str,
    findings: Sequence[Dict[str, object]],
    metrics: Optional[Dict[str, object]] = None,
    limit: int = 5,
) -> List[str]:
    """Deterministic, offline insights derived from the findings themselves."""
    metrics = metrics or {}
    insights: List[str] = []

    if not findings:
        insights.append(
            f"No {agent_name.lower()} issues were detected in the analysed files."
        )
    else:
        ordered = sorted(
            findings,
            key=lambda f: SEVERITY_RANK.get(str(f.get("severity")), 99),
        )
        grouped = group_findings(ordered)
        ranked = sorted(
            grouped.items(),
            key=lambda item: (
                SEVERITY_RANK.get(str(item[1][0].get("severity")), 99),
                -len(item[1]),
            ),
        )
        for rule_id, items in ranked[: max(limit - 1, 1)]:
            rule = get_rule(rule_id)
            title = rule.title if rule else str(items[0].get("title") or rule_id)
            locations = ", ".join(
                f"{item.get('file_path', '?')}:{item.get('line_start')}"
                for item in items[:3]
                if item.get("line_start")
            )
            suffix = f" ({locations})" if locations else ""
            count = f"{len(items)}x " if len(items) > 1 else ""
            insights.append(f"{count}{title}{suffix}.")

    severity_counts: Dict[str, int] = {}
    for finding in findings:
        severity = str(finding.get("severity"))
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
    if severity_counts:
        breakdown = ", ".join(
            f"{count} {severity.lower()}"
            for severity, count in sorted(
                severity_counts.items(), key=lambda kv: SEVERITY_RANK.get(kv[0], 99)
            )
        )
        insights.append(f"Severity mix: {breakdown}.")

    if metrics:
        average_complexity = metrics.get("average_complexity")
        maintainability = metrics.get("maintainability_index")
        if maintainability is not None:
            insights.append(f"Average maintainability index is {maintainability}/100.")
        if average_complexity:
            insights.append(f"Average cyclomatic complexity per file is {average_complexity}.")

    return insights[:limit]


def render_prompt(agent_name: str, role: str, findings: Sequence[Dict[str, object]],
                  metrics: Optional[Dict[str, object]], limit: int = 5) -> str:
    """Builds the review prompt sent to a hosted LLM."""
    metrics = metrics or {}
    lines = [
        f"You are the {agent_name} of an automated code review platform.",
        f"Your focus: {role}",
        "",
        "Static analysis already produced the findings below. Do not invent new issues;",
        "explain the highest-impact ones and give concrete, actionable advice.",
        "",
        f"Findings ({len(findings)} total):",
    ]
    for finding in findings[:25]:
        lines.append(
            "- [{severity}] {rule_id} {title} at {file}:{line} :: {description}".format(
                severity=finding.get("severity"),
                rule_id=finding.get("rule_id"),
                title=finding.get("title"),
                file=finding.get("file_path", "?"),
                line=finding.get("line_start", "?"),
                description=str(finding.get("description", ""))[:200],
            )
        )
    if not findings:
        lines.append("- (none)")
    if metrics:
        lines.append("")
        lines.append(f"Project metrics: {json.dumps(metrics, default=str)[:800]}")
    lines.extend(
        [
            "",
            f"Reply with a JSON array of at most {limit} short strings (max 25 words each).",
            "No prose outside the JSON array.",
        ]
    )
    return "\n".join(lines)


def truncate(text: str, limit: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "..."


def join_insights(insights: Iterable[str]) -> str:
    return " ".join(truncate(item) for item in insights)

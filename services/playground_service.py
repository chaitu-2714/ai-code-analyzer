"""Paste-and-review playground (the "Compiler" page).

Flow: paste code -> compile check -> five agents review it -> rewrite the code
by applying every safe fix, re-analysing after each patch so line numbers never
go stale.

Nothing is executed: "compile" means a real syntax/parse check (``compile()`` for
Python, ``node --check`` for JavaScript). Pasted code is never run.
"""
from __future__ import annotations

import contextlib
import difflib
import logging
import os
import tempfile
import time
from typing import Dict, List, Optional

from agents.base import ReviewContext
from agents.orchestrator import AgentOrchestrator, ReviewResult
from analyzer.engine import FileAnalysis, FileInput, StaticAnalysisEngine
from analyzer.rules.base import language_family
from core.exceptions import ApplicationError
from llm.base import LLMProvider
from llm.factory import create_provider
from repair.fixers import apply_fixer, is_batch_safe
from utils.language_detector import EXTENSION_MAP

logger = logging.getLogger(__name__)

#: Extensions used when writing a snippet to a temporary file for tooling.
EXTENSION_FOR_LANGUAGE = {
    "python": ".py",
    "js": ".js",
    "java": ".java",
    "go": ".go",
    "ruby": ".rb",
    "php": ".php",
    "c": ".c",
    "cpp": ".cpp",
    "csharp": ".cs",
    "shell": ".sh",
}

LANGUAGE_CHOICES = [
    "Python",
    "JavaScript",
    "TypeScript",
    "Java",
    "Go",
    "Ruby",
    "PHP",
    "C",
    "C++",
    "C#",
    "Shell",
]

DEFAULT_FILENAME = {
    "Python": "snippet.py",
    "JavaScript": "snippet.js",
    "TypeScript": "snippet.ts",
    "Java": "Snippet.java",
    "Go": "snippet.go",
    "Ruby": "snippet.rb",
    "PHP": "snippet.php",
    "C": "snippet.c",
    "C++": "snippet.cpp",
    "C#": "snippet.cs",
    "Shell": "snippet.sh",
}


def detect_language(code: str, filename: Optional[str] = None) -> str:
    """Best-effort language detection from the filename, then from the code."""
    if filename:
        extension = os.path.splitext(filename)[1].lower()
        if extension in EXTENSION_MAP:
            return EXTENSION_MAP[extension]

    stripped = code.strip()
    if not stripped:
        return "Python"
    lowered = stripped.lower()
    if any(token in stripped for token in ("def ", "import ", "self.", "elif ")) or lowered.startswith("#!"):
        return "Python"
    js_tokens = (
        "function ",
        "const ",
        "let ",
        "var ",
        "=>",
        "console.log",
        "document.",
        "require(",
        "window.",
        "===",
        "!==",
        "export ",
    )
    if any(token in stripped for token in js_tokens):
        return "JavaScript"
    if "interface " in stripped and ": " in stripped and "function" not in stripped:
        return "TypeScript"
    if any(token in stripped for token in ("public class", "System.out", "private static")):
        return "Java"
    if any(token in stripped for token in ("package main", "func ", "fmt.")):
        return "Go"
    if "<?php" in lowered:
        return "PHP"
    if any(token in stripped for token in ("puts ", "def ", "end\n")):
        return "Ruby"
    if any(token in stripped for token in ("#include", "std::", "printf(")):
        return "C++" if "std::" in stripped else "C"
    return "Python"


def _finding_payload(analysis: FileAnalysis) -> List[Dict[str, object]]:
    """Converts engine findings into the dict shape the agents consume."""
    payload: List[Dict[str, object]] = []
    for finding in analysis.findings:
        payload.append(
            {
                "rule_id": finding.rule_id,
                "category": finding.category,
                "severity": finding.severity,
                "title": finding.title,
                "description": finding.description,
                "file_path": analysis.file.relative_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "code_snippet": finding.code_snippet,
                "suggestion": finding.suggestion,
                "confidence": finding.confidence,
                "detector": finding.detector,
            }
        )
    return payload


class PlaygroundService:
    """Reviews and rewrites a single pasted snippet, without touching the DB."""

    def __init__(
        self,
        config=None,
        provider: Optional[LLMProvider] = None,
        engine: Optional[StaticAnalysisEngine] = None,
        orchestrator: Optional[AgentOrchestrator] = None,
    ):
        self.config = config
        self.provider = provider or create_provider(config)
        self.engine = engine or StaticAnalysisEngine(
            long_function_threshold=getattr(config, "long_function_threshold", 50),
            complexity_threshold=getattr(config, "complexity_threshold", 10),
            duplicate_window=getattr(config, "duplicate_window_lines", 6),
        )
        self.orchestrator = orchestrator or AgentOrchestrator(provider=self.provider)

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _file_input(code: str, language: str, filename: Optional[str] = None) -> FileInput:
        name = filename or DEFAULT_FILENAME.get(language, "snippet.py")
        return FileInput(file_id=0, relative_path=name, absolute_path="", language=language, content=code)

    def analyze(self, code: str, language: str, filename: Optional[str] = None) -> FileAnalysis:
        return self.engine.analyze_file(self._file_input(code, language, filename))

    # -- compile check -----------------------------------------------------
    def compile_check(self, code: str, language: str, filename: Optional[str] = None) -> Dict[str, object]:
        """Real parse/syntax validation of the snippet (never executes it)."""
        started = time.perf_counter()
        family = language_family(language)
        name = filename or DEFAULT_FILENAME.get(language, "snippet.py")

        if family == "python":
            try:
                compile(code, name, "exec")
                return {
                    "ok": True,
                    "message": "Compiles cleanly (syntax check passed).",
                    "duration_seconds": round(time.perf_counter() - started, 3),
                }
            except SyntaxError as error:
                return {
                    "ok": False,
                    "message": f"SyntaxError: {error.msg} (line {error.lineno}, column {error.offset}).",
                    "line": error.lineno,
                    "duration_seconds": round(time.perf_counter() - started, 3),
                }

        if family == "js":
            if "typescript" in str(language).lower() or name.endswith((".ts", ".tsx")):
                return self._typescript_check(code, name, started)
            return self._node_check(code, name, started)

        analysis = self.analyze(code, language, filename)
        if analysis.parse_error:
            return {
                "ok": False,
                "message": analysis.parse_error,
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        return {
            "ok": True,
            "message": f"No parser available for {language}; syntax check skipped.",
            "duration_seconds": round(time.perf_counter() - started, 3),
        }

    @staticmethod
    def _node_check(code: str, name: str, started: float) -> Dict[str, object]:
        import shutil
        import subprocess

        node = shutil.which("node")
        if not node:
            return {
                "ok": True,
                "message": "node is not installed; JavaScript syntax check skipped.",
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        suffix = os.path.splitext(name)[1] or ".js"
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False) as handle:
                handle.write(code)
                temp_path = handle.name
            completed = subprocess.run(
                [node, "--check", temp_path],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            ok = completed.returncode == 0
            message = (completed.stderr or completed.stdout or "").strip()[:500]
            if not ok and "ERR_UNKNOWN_FILE_EXTENSION" in message:
                return {
                    "ok": True,
                    "message": (
                        "node cannot parse this file extension; syntax check skipped."
                    ),
                    "duration_seconds": round(time.perf_counter() - started, 3),
                }
            return {
                "ok": ok,
                "message": message or ("JavaScript syntax OK." if ok else "Syntax error."),
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        except (subprocess.SubprocessError, OSError) as error:  # pragma: no cover - env dependent
            return {
                "ok": True,
                "message": f"node check could not run: {error}",
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        finally:
            if temp_path:
                with contextlib.suppress(OSError):
                    os.unlink(temp_path)

    @staticmethod
    def _typescript_check(code: str, name: str, started: float) -> Dict[str, object]:
        """TypeScript check through ``tsc`` when the toolchain is installed.

        ``node --check`` only understands JavaScript, so TypeScript must not be
        piped through it - valid annotations would be reported as syntax errors.
        """
        import shutil
        import subprocess

        tsc = shutil.which("tsc")
        if not tsc:
            return {
                "ok": True,
                "message": (
                    "TypeScript compiler (tsc) is not installed; syntax check skipped "
                    "(npm i -g typescript to enable it)."
                ),
                "duration_seconds": round(time.perf_counter() - started, 3),
            }

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".ts", delete=False) as handle:
                handle.write(code)
                temp_path = handle.name
            completed = subprocess.run(
                [
                    tsc,
                    "--noEmit",
                    "--skipLibCheck",
                    "--target",
                    "es2020",
                    "--module",
                    "esnext",
                    temp_path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            ok = completed.returncode == 0
            message = (completed.stdout or completed.stderr or "").strip()[:800]
            return {
                "ok": ok,
                "message": message or ("TypeScript compiles cleanly." if ok else "TypeScript errors."),
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        except (subprocess.SubprocessError, OSError) as error:  # pragma: no cover - env dependent
            return {
                "ok": True,
                "message": f"tsc could not run: {error}",
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        finally:
            if temp_path:
                with contextlib.suppress(OSError):
                    os.unlink(temp_path)

    # -- review ------------------------------------------------------------
    def review_snippet(
        self,
        code: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        progress_callback=None,
    ) -> Dict[str, object]:
        """Runs the five agents over a pasted snippet."""
        if not code or not code.strip():
            raise ApplicationError("Paste some code first.")

        language = language or detect_language(code, filename)
        started = time.perf_counter()
        analysis = self.analyze(code, language, filename)
        findings = _finding_payload(analysis)

        context = ReviewContext(
            project_id=0,
            project_name="Pasted snippet",
            findings=findings,
            metrics=analysis.metrics,
            files_analyzed=1,
            duplicate_groups=0,
            dependency_issues=0,
        )
        result: ReviewResult = self.orchestrator.run(context, progress_callback=progress_callback)
        compile_result = self.compile_check(code, language, filename)

        payload = result.to_dict()
        payload.update(
            {
                "language": language,
                "filename": filename or DEFAULT_FILENAME.get(language, "snippet.py"),
                "lines_of_code": analysis.metrics.get("lines_of_code", 0),
                "metrics": analysis.metrics,
                "findings": findings,
                "compile": compile_result,
                "parse_error": analysis.parse_error,
                "duration_seconds": round(time.perf_counter() - started, 3),
            }
        )
        return payload

    # -- rewrite -----------------------------------------------------------
    def rewrite_snippet(
        self,
        code: str,
        language: Optional[str] = None,
        filename: Optional[str] = None,
        max_passes: int = 40,
        use_llm: bool = False,
        progress_callback=None,
    ) -> Dict[str, object]:
        """Applies every safe fix in sequence, re-analysing after each patch."""
        if not code or not code.strip():
            raise ApplicationError("Paste some code first.")

        language = language or detect_language(code, filename)
        started = time.perf_counter()
        original = code
        current = code
        applied: List[Dict[str, object]] = []
        skipped: List[Dict[str, object]] = []
        seen: set = set()
        notes: List[str] = []

        before = self.review_snippet(original, language, filename)
        if progress_callback:
            progress_callback("Rewriting", 30)

        for pass_index in range(max(1, max_passes)):
            analysis = self.analyze(current, language, filename)
            if analysis.parse_error:
                notes.append(
                    "Stopped rewriting: the current code no longer parses "
                    f"({analysis.parse_error})."
                )
                break

            # Fix from the bottom of the file upwards: a patch that inserts or
            # removes lines then only shifts lines we have already handled, so
            # one pass can safely apply many fixes.  If a patch touches anything
            # *above* its own line (e.g. adding a top-of-file import), the
            # remaining line numbers are stale and the pass stops early.
            fixable = [
                finding
                for finding in analysis.findings
                if self._has_fixer(str(finding.rule_id or ""))
            ]
            # Deletion-style fixers (unused import removal) are applied only on a
            # fresh analysis: another patch in the same sweep may just have made
            # that import necessary again.
            batch_safe = [f for f in fixable if is_batch_safe(str(f.rule_id or ""))]
            batch_unsafe = [f for f in fixable if not is_batch_safe(str(f.rule_id or ""))]
            batch_safe.sort(key=lambda f: (-(f.line_start or 0), str(f.rule_id or "")))
            batch_unsafe.sort(key=lambda f: (-(f.line_start or 0), str(f.rule_id or "")))

            progress = False
            for finding in batch_safe:
                rule_id = str(finding.rule_id or "")
                line = finding.line_start or 1
                key = (rule_id, line)
                if key in seen:
                    continue
                payload = {
                    "rule_id": rule_id,
                    "line_start": finding.line_start,
                    "line_end": finding.line_end,
                    "title": finding.title,
                    "severity": finding.severity,
                    "code_snippet": finding.code_snippet,
                    "suggestion": finding.suggestion,
                    "file_path": analysis.file.relative_path,
                }
                result = apply_fixer(rule_id, current, payload, language, validate=False)
                if result is None or not result.can_apply or result.patched_source == current:
                    continue
                seen.add(key)
                if not self._syntax_ok(result.patched_source, language, filename):
                    skipped.append(
                        {
                            "rule_id": rule_id,
                            "line": line,
                            "reason": "the patch would break the syntax",
                        }
                    )
                    continue

                before_lines = current.splitlines()
                current = result.patched_source
                after_lines = current.splitlines()
                applied.append(
                    {
                        "rule_id": rule_id,
                        "title": finding.title,
                        "severity": finding.severity,
                        "line": line,
                        "explanation": result.explanation,
                        "confidence": result.confidence,
                        "pass": pass_index + 1,
                    }
                )
                progress = True

                if before_lines[: line - 1] != after_lines[: line - 1]:
                    # Something above the target line moved: re-analyse before
                    # touching the findings that are left.
                    break

            if not progress:
                # Nothing safe to batch left: try one deletion-style fix, which
                # is always evaluated against the freshly analysed source.
                for finding in batch_unsafe:
                    rule_id = str(finding.rule_id or "")
                    line = finding.line_start or 1
                    if (rule_id, line) in seen:
                        continue
                    payload = {
                        "rule_id": rule_id,
                        "line_start": finding.line_start,
                        "line_end": finding.line_end,
                        "title": finding.title,
                        "severity": finding.severity,
                        "code_snippet": finding.code_snippet,
                        "suggestion": finding.suggestion,
                        "file_path": analysis.file.relative_path,
                    }
                    result = apply_fixer(rule_id, current, payload, language, validate=False)
                    if result is None or not result.can_apply or result.patched_source == current:
                        continue
                    seen.add((rule_id, line))
                    if not self._syntax_ok(result.patched_source, language, filename):
                        skipped.append(
                            {"rule_id": rule_id, "line": line, "reason": "the patch would break the syntax"}
                        )
                        continue
                    current = result.patched_source
                    applied.append(
                        {
                            "rule_id": rule_id,
                            "title": finding.title,
                            "severity": finding.severity,
                            "line": line,
                            "explanation": result.explanation,
                            "confidence": result.confidence,
                            "pass": pass_index + 1,
                        }
                    )
                    progress = True
                    break

            if not progress:
                break

        if progress_callback:
            progress_callback("Validating", 75)

        llm_used = False
        if use_llm and current.strip():
            llm_code, _llm_note = self._llm_rewrite(current, language, filename, before)
            if llm_code and llm_code.strip() != current.strip():
                if self._syntax_ok(llm_code, language, filename):
                    current = llm_code
                    llm_used = True
                    notes.append("AI rewrite applied and syntax-validated.")
                else:
                    notes.append("AI rewrite discarded: the returned code did not parse.")

        after = self.review_snippet(current, language, filename)
        if progress_callback:
            progress_callback("Completed", 100)

        remaining = [
            finding
            for finding in after["findings"]
            if not self._has_fixer(str(finding.get("rule_id") or ""))
        ]
        return {
            "language": language,
            "filename": filename or DEFAULT_FILENAME.get(language, "snippet.py"),
            "original_code": original,
            "rewritten_code": current,
            "changed": current.strip() != original.strip(),
            "diff": self._diff(original, current, filename or DEFAULT_FILENAME.get(language, "snippet.py")),
            "applied": applied,
            "skipped": skipped,
            "notes": notes,
            "llm_used": llm_used,
            "before": {
                "overall_score": before["overall_score"],
                "risk_level": before["risk_level"],
                "findings": len(before["findings"]),
            },
            "after": {
                "overall_score": after["overall_score"],
                "risk_level": after["risk_level"],
                "findings": len(after["findings"]),
            },
            "remaining_findings": remaining,
            "review_after": after,
            "compile": after["compile"],
            "duration_seconds": round(time.perf_counter() - started, 3),
        }

    # -- internals ---------------------------------------------------------
    @staticmethod
    def _has_fixer(rule_id: str) -> bool:
        from repair.fixers import FIXERS

        return rule_id in FIXERS

    def _syntax_ok(self, code: str, language: str, filename: Optional[str] = None) -> bool:
        """Validates a patched snippet before it is accepted."""
        family = language_family(language)
        if family == "python":
            try:
                compile(code, filename or "snippet.py", "exec")
                return True
            except SyntaxError:
                return False
        if family == "js" and "typescript" not in str(language).lower():
            # node --check gives JavaScript patches the same safety net Python has.
            return bool(self.compile_check(code, "JavaScript", "snippet.js").get("ok"))
        return True

    @staticmethod
    def _diff(original: str, patched: str, name: str) -> str:
        return "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                patched.splitlines(keepends=True),
                fromfile=f"a/{name}",
                tofile=f"b/{name}",
            )
        )

    def _llm_rewrite(
        self,
        code: str,
        language: str,
        filename: Optional[str],
        review: Dict[str, object],
    ):
        """Asks the configured provider for a corrected full file."""
        if self.provider is None or not self.provider.available():
            return None, "no provider"
        findings = review.get("findings") or []
        listing = "\n".join(
            "- [{severity}] {rule} line {line}: {title}".format(
                severity=finding.get("severity"),
                rule=finding.get("rule_id"),
                line=finding.get("line_start"),
                title=finding.get("title"),
            )
            for finding in findings[:30]
        )
        prompt = (
            f"Rewrite this {language} file to fix the listed issues.\n"
            "Return ONLY the complete corrected file inside a single fenced code block.\n"
            "Keep the behaviour and the public interface identical.\n\n"
            f"Issues:\n{listing or '- none'}\n\n"
            f"File ({filename or 'snippet'}):\n{code}"
        )
        try:
            text = self.provider.generate(prompt, system="You are a senior engineer performing a careful refactor.", max_tokens=2000)
        except Exception as error:  # noqa: BLE001 - provider errors must never break the rewrite
            logger.info("LLM rewrite unavailable: %s", error)
            return None, str(error)
        return _extract_code_block(text), "ok"


def _extract_code_block(text: str) -> Optional[str]:
    """Pulls the first fenced code block (or the whole text) out of a reply."""
    if not text:
        return None
    fence = "```"
    if fence in text:
        start = text.find(fence)
        body_start = text.find("\n", start)
        end = text.find(fence, body_start + 1)
        if body_start != -1 and end != -1:
            return text[body_start + 1 : end].rstrip() + "\n"
    return text.strip() + "\n"

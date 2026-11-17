"""Compiler page: paste code, get a multi-agent review, get rewritten code."""
from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.playground_service import LANGUAGE_CHOICES, PlaygroundService, detect_language
from ui.widgets.common import (
    RISK_COLORS,
    SEVERITY_COLORS,
    make_table,
    page_header,
    primary_button,
    secondary_button,
    set_row,
    start_worker,
)

logger = logging.getLogger(__name__)

PLACEHOLDER = """# Paste any code here, then press "Analyze & Review" or "Rewrite Code".
# Nothing is executed - only parsed and analysed.
"""


class CompilerPage(QWidget):
    """Paste-and-go playground: compile check, agent review and code rewrite."""

    def __init__(self, playground_service: PlaygroundService, parent=None):
        super().__init__(parent)
        self.playground = playground_service
        self._review: Optional[Dict[str, object]] = None
        self._rewrite: Optional[Dict[str, object]] = None
        self._agents: List[Dict[str, object]] = []
        self._findings: List[Dict[str, object]] = []
        self.init_ui()

    # -- construction ------------------------------------------------------
    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        layout.addWidget(
            page_header(
                "Compiler",
                "Paste code → compile check → five agents review it → rewritten code you can copy back.",
            )
        )

        controls = QHBoxLayout()
        controls.setSpacing(8)
        controls.addWidget(QLabel("Language:"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("Auto detect")
        self.language_combo.addItems(LANGUAGE_CHOICES)
        self.language_combo.setMinimumWidth(150)
        controls.addWidget(self.language_combo)

        self.compile_button = secondary_button("Compile Check")
        self.compile_button.clicked.connect(self.compile_code)
        controls.addWidget(self.compile_button)

        self.review_button = primary_button("Analyze & Review")
        self.review_button.clicked.connect(self.run_review)
        controls.addWidget(self.review_button)

        self.rewrite_button = primary_button("Rewrite Code")
        self.rewrite_button.clicked.connect(self.run_rewrite)
        controls.addWidget(self.rewrite_button)

        self.llm_checkbox = QCheckBox("AI rewrite")
        self.llm_checkbox.setToolTip(
            "Ask the configured LLM for a full rewrite as well. Requires a reachable provider;\n"
            "the deterministic fixers always run first."
        )
        controls.addWidget(self.llm_checkbox)

        self.load_button = secondary_button("Load File…")
        self.load_button.clicked.connect(self.load_file)
        controls.addWidget(self.load_button)

        self.clear_button = secondary_button("Clear")
        self.clear_button.clicked.connect(self.clear_editor)
        controls.addWidget(self.clear_button)
        controls.addStretch()
        layout.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        splitter = QSplitter(Qt.Horizontal)

        # -- editor --------------------------------------------------------
        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(6)

        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("monospace", 10))
        self.editor.setPlaceholderText(PLACEHOLDER)
        self.editor.setTabStopDistance(32)
        self.editor.textChanged.connect(self._update_editor_status)
        editor_layout.addWidget(self.editor, stretch=1)

        self.editor_status = QLabel("0 lines · language: --")
        self.editor_status.setStyleSheet("color: #8b8b9c; font-size: 12px;")
        editor_layout.addWidget(self.editor_status)
        splitter.addWidget(editor_panel)

        # -- results -------------------------------------------------------
        self.tabs = QTabWidget()

        review_tab = QWidget()
        review_layout = QVBoxLayout(review_tab)
        review_layout.setSpacing(8)

        verdict = QHBoxLayout()
        self.score_label = QLabel("--")
        self.score_label.setStyleSheet("font-size: 40px; font-weight: 700; color: #ffffff;")
        self.risk_label = QLabel("risk: --")
        self.risk_label.setStyleSheet("font-size: 15px; color: #8b8b9c;")
        self.compile_label = QLabel("compile: --")
        self.compile_label.setStyleSheet("font-size: 12px; color: #8b8b9c;")
        verdict.addWidget(self.score_label)
        verdict.addWidget(self.risk_label)
        verdict.addWidget(self.compile_label)
        verdict.addStretch()
        review_layout.addLayout(verdict)

        self.summary_label = QLabel("Paste code and press 'Analyze & Review'.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color: #b9b9c9; font-size: 13px;")
        review_layout.addWidget(self.summary_label)

        self.agents_table = make_table(["Agent", "Score", "Findings", "Critical", "High"])
        self.agents_table.setMinimumHeight(150)
        self.agents_table.itemSelectionChanged.connect(self.show_agent_insights)
        review_layout.addWidget(self.agents_table)

        self.insights_box = QTextEdit()
        self.insights_box.setReadOnly(True)
        self.insights_box.setMinimumHeight(120)
        review_layout.addWidget(self.insights_box, stretch=1)
        self.tabs.addTab(review_tab, "Review")

        findings_tab = QWidget()
        findings_layout = QVBoxLayout(findings_tab)
        findings_layout.setSpacing(8)
        self.findings_table = make_table(["Severity", "Rule", "Line", "Title", "Category"])
        self.findings_table.itemSelectionChanged.connect(self.show_finding_detail)
        findings_layout.addWidget(self.findings_table, stretch=2)
        self.finding_detail = QTextEdit()
        self.finding_detail.setReadOnly(True)
        self.finding_detail.setMinimumHeight(110)
        findings_layout.addWidget(self.finding_detail, stretch=1)
        self.tabs.addTab(findings_tab, "Findings")

        rewrite_tab = QWidget()
        rewrite_layout = QVBoxLayout(rewrite_tab)
        rewrite_layout.setSpacing(8)

        rewrite_controls = QHBoxLayout()
        self.rewrite_status = QLabel("No rewrite yet.")
        self.rewrite_status.setStyleSheet("color: #b9b9c9; font-size: 12px;")
        self.rewrite_status.setWordWrap(True)
        rewrite_controls.addWidget(self.rewrite_status, stretch=1)

        self.copy_button = secondary_button("Copy Code")
        self.copy_button.clicked.connect(self.copy_rewritten)
        self.copy_button.setEnabled(False)
        rewrite_controls.addWidget(self.copy_button)

        self.save_button = secondary_button("Save As…")
        self.save_button.clicked.connect(self.save_rewritten)
        self.save_button.setEnabled(False)
        rewrite_controls.addWidget(self.save_button)
        rewrite_layout.addLayout(rewrite_controls)

        self.rewrite_tabs = QTabWidget()
        self.rewritten_view = QPlainTextEdit()
        self.rewritten_view.setReadOnly(True)
        self.rewritten_view.setFont(QFont("monospace", 10))
        self.rewrite_tabs.addTab(self.rewritten_view, "Rewritten code")

        self.diff_view = QPlainTextEdit()
        self.diff_view.setReadOnly(True)
        self.diff_view.setFont(QFont("monospace", 10))
        self.rewrite_tabs.addTab(self.diff_view, "Diff")

        self.applied_view = QTextEdit()
        self.applied_view.setReadOnly(True)
        self.rewrite_tabs.addTab(self.applied_view, "Applied fixes")

        rewrite_layout.addWidget(self.rewrite_tabs, stretch=1)
        self.tabs.addTab(rewrite_tab, "Rewrite")

        splitter.addWidget(self.tabs)
        splitter.setSizes([560, 620])
        layout.addWidget(splitter, stretch=1)

    # -- editor helpers ----------------------------------------------------
    def _language(self) -> str:
        selection = self.language_combo.currentText()
        if selection == "Auto detect":
            return detect_language(self.editor.toPlainText())
        return selection

    def _update_editor_status(self) -> None:
        text = self.editor.toPlainText()
        lines = len(text.splitlines())
        self.editor_status.setText(f"{lines} lines · language: {self._language()}")

    def set_code(self, code: str, language: Optional[str] = None) -> None:
        """Programmatic entry point (used by tests and the project pages)."""
        self.editor.setPlainText(code)
        if language and language in LANGUAGE_CHOICES:
            self.language_combo.setCurrentText(language)
        self._update_editor_status()

    def clear_editor(self) -> None:
        self.editor.clear()
        self._review = None
        self._rewrite = None
        self.agents_table.setRowCount(0)
        self.findings_table.setRowCount(0)
        self.insights_box.clear()
        self.rewritten_view.clear()
        self.diff_view.clear()
        self.applied_view.clear()
        self.score_label.setText("--")
        self.risk_label.setText("risk: --")
        self.compile_label.setText("compile: --")
        self.summary_label.setText("Paste code and press 'Analyze & Review'.")
        self.rewrite_status.setText("No rewrite yet.")
        self.copy_button.setEnabled(False)
        self.save_button.setEnabled(False)

    def load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open a source file", "", "Source files (*.py *.js *.ts *.java *.go *.rb *.php *.c *.cpp *.cs *.sh);;All files (*)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8", errors="ignore") as handle:
                code = handle.read()
        except OSError as error:
            QMessageBox.critical(self, "Cannot open file", str(error))
            return
        self.set_code(code, detect_language(code, path))
        self.editor_status.setText(
            f"{len(code.splitlines())} lines · language: {self._language()} · {os.path.basename(path)}"
        )

    # -- actions -----------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        for button in (self.compile_button, self.review_button, self.rewrite_button):
            button.setEnabled(not busy)
        if not busy:
            self.progress.setValue(0)

    def compile_code(self) -> None:
        code = self.editor.toPlainText()
        if not code.strip():
            QMessageBox.information(self, "Nothing to compile", "Paste some code first.")
            return
        result = self.playground.compile_check(code, self._language())
        self.compile_label.setText("compile: " + ("OK" if result["ok"] else "FAILED"))
        self.compile_label.setStyleSheet(
            "font-size: 12px; color: "
            + ("#30a46c" if result["ok"] else SEVERITY_COLORS["CRITICAL"])
        )
        QMessageBox.information(
            self,
            "Compile check passed" if result["ok"] else "Compile check failed",
            str(result["message"]),
        )

    def run_review(self) -> None:
        code = self.editor.toPlainText()
        if not code.strip():
            QMessageBox.information(self, "Nothing to review", "Paste some code first.")
            return
        language = self._language()
        self._set_busy(True)
        self.summary_label.setText("Running the agents…")
        self.tabs.setCurrentIndex(0)

        def task(progress):
            return self.playground.review_snippet(code, language, progress_callback=progress)

        start_worker(self, task, self._on_review_done, self._on_failed, self._on_progress)

    def run_rewrite(self) -> None:
        code = self.editor.toPlainText()
        if not code.strip():
            QMessageBox.information(self, "Nothing to rewrite", "Paste some code first.")
            return
        language = self._language()
        use_llm = self.llm_checkbox.isChecked()
        self._set_busy(True)
        self.rewrite_status.setText("Rewriting…")
        self.tabs.setCurrentIndex(2)

        def task(progress):
            return self.playground.rewrite_snippet(
                code, language, use_llm=use_llm, progress_callback=progress
            )

        start_worker(self, task, self._on_rewrite_done, self._on_failed, self._on_progress)

    def _on_progress(self, name: str, percent: int) -> None:
        self.progress.setValue(percent)

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        QMessageBox.critical(self, "Failed", message)

    # -- rendering ---------------------------------------------------------
    def _on_review_done(self, result: object) -> None:
        self._set_busy(False)
        self._review = dict(result or {})  # type: ignore[arg-type]
        self._render_review(self._review)

    def _render_review(self, review: Dict[str, object]) -> None:
        score = review.get("overall_score")
        risk = str(review.get("risk_level") or "--")
        self.score_label.setText(f"{score}" if score is not None else "--")
        self.risk_label.setText(f"risk: {risk}")
        self.risk_label.setStyleSheet(
            f"font-size: 15px; color: {RISK_COLORS.get(risk, '#8b8b9c')}; font-weight: 600;"
        )
        compile_result = review.get("compile") or {}
        ok = bool(compile_result.get("ok"))
        self.compile_label.setText("compile: " + ("OK" if ok else "FAILED"))
        self.compile_label.setStyleSheet(
            f"font-size: 12px; color: {'#30a46c' if ok else SEVERITY_COLORS['CRITICAL']}"
        )
        self.summary_label.setText(
            f"{review.get('summary') or ''} ({review.get('language')}, "
            f"{review.get('lines_of_code')} lines, {review.get('duration_seconds')}s)"
        )

        self._agents = list(review.get("agents") or [])  # type: ignore[arg-type]
        self.agents_table.setRowCount(len(self._agents))
        for index, agent in enumerate(self._agents):
            set_row(
                self.agents_table,
                index,
                [
                    agent.get("agent_name"),
                    agent.get("score"),
                    agent.get("findings_count"),
                    agent.get("critical_count"),
                    agent.get("high_count"),
                ],
            )
        if self._agents:
            self.agents_table.selectRow(0)
            self.show_agent_insights()

        self._findings = list(review.get("findings") or [])  # type: ignore[arg-type]
        self.findings_table.setRowCount(len(self._findings))
        for index, finding in enumerate(self._findings):
            set_row(
                self.findings_table,
                index,
                [
                    finding.get("severity"),
                    finding.get("rule_id"),
                    finding.get("line_start") or "-",
                    finding.get("title"),
                    finding.get("category"),
                ],
                colors=[SEVERITY_COLORS.get(str(finding.get("severity")))],
            )
        self.finding_detail.clear()

    def show_agent_insights(self) -> None:
        rows = self.agents_table.selectionModel().selectedRows() if self.agents_table.selectionModel() else []
        if not rows:
            return
        index = rows[0].row()
        if not (0 <= index < len(self._agents)):
            return
        agent = self._agents[index]
        lines = [f"{agent.get('agent_name')} — score {agent.get('score')}/100", ""]
        lines.append(str(agent.get("summary") or ""))
        lines.append("")
        for insight in agent.get("insights") or []:  # type: ignore[union-attr]
            lines.append(f"* {insight}")
        self.insights_box.setPlainText("\n".join(lines))

    def show_finding_detail(self) -> None:
        rows = (
            self.findings_table.selectionModel().selectedRows()
            if self.findings_table.selectionModel()
            else []
        )
        if not rows:
            return
        index = rows[0].row()
        if not (0 <= index < len(self._findings)):
            return
        finding = self._findings[index]
        lines = [
            f"[{finding.get('severity')}] {finding.get('title')} ({finding.get('rule_id')})",
            f"Line {finding.get('line_start')} · {finding.get('category')} · detector {finding.get('detector')}",
            "",
            str(finding.get("description") or ""),
        ]
        if finding.get("code_snippet"):
            lines.extend(["", "Code:", str(finding.get("code_snippet"))])
        if finding.get("suggestion"):
            lines.extend(["", f"Suggested fix: {finding.get('suggestion')}"])
        self.finding_detail.setPlainText("\n".join(lines))

    def _on_rewrite_done(self, result: object) -> None:
        self._set_busy(False)
        self._rewrite = dict(result or {})  # type: ignore[arg-type]
        payload = self._rewrite

        rewritten = str(payload.get("rewritten_code") or "")
        self.rewritten_view.setPlainText(rewritten)
        self.diff_view.setPlainText(str(payload.get("diff") or "No changes."))

        applied = list(payload.get("applied") or [])  # type: ignore[arg-type]
        lines = []
        for item in applied:
            lines.append(
                f"+ {item.get('rule_id')} (line {item.get('line')}, confidence {item.get('confidence')})"
                f"\n    {item.get('explanation')}"
            )
        for item in payload.get("skipped") or []:  # type: ignore[union-attr]
            lines.append(f"- skipped {item.get('rule_id')} at line {item.get('line')}: {item.get('reason')}")
        for note in payload.get("notes") or []:  # type: ignore[union-attr]
            lines.append(f"* {note}")
        if not lines:
            lines.append("No automatic fix was applicable; see the Findings tab for guidance.")
        self.applied_view.setPlainText("\n".join(lines))

        before = payload.get("before") or {}
        after = payload.get("after") or {}
        compile_result = payload.get("compile") or {}
        self.rewrite_status.setText(
            "{n} fix(es) applied · score {b} → {a} · {fb} → {fa} finding(s) · {c}".format(
                n=len(applied),
                b=before.get("overall_score"),
                a=after.get("overall_score"),
                fb=before.get("findings"),
                fa=after.get("findings"),
                c="compiles" if compile_result.get("ok") else "does NOT compile",
            )
        )
        self.copy_button.setEnabled(bool(rewritten.strip()))
        self.save_button.setEnabled(bool(rewritten.strip()))
        self.rewrite_tabs.setCurrentIndex(0)

        if payload.get("review_after"):
            self._review = dict(payload["review_after"])  # type: ignore[arg-type]
            self._render_review(self._review)

    # -- output ------------------------------------------------------------
    def copy_rewritten(self) -> None:
        code = self.rewritten_view.toPlainText()
        if not code.strip():
            return
        QGuiApplication.clipboard().setText(code)
        self.rewrite_status.setText("Rewritten code copied to the clipboard.")

    def save_rewritten(self) -> None:
        code = self.rewritten_view.toPlainText()
        if not code.strip():
            return
        default_name = str((self._rewrite or {}).get("filename") or "rewritten.py")
        path, _ = QFileDialog.getSaveFileName(self, "Save rewritten code", default_name)
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(code)
        except OSError as error:
            QMessageBox.critical(self, "Cannot save", str(error))
            return
        self.rewrite_status.setText(f"Saved to {path}")

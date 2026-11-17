# Changelog

## 2.1.2 — Per-language correctness in the Compiler

Asking "which languages does the compiler support?" and testing each one exposed two
defects in the language handling.

### Fixed

* **Python fixers were being applied to non-Python code.** A Ruby/Shell/PHP/Java snippet
  containing `password = "..."` was "fixed" into `password = os.getenv(...)`, i.e. Python
  syntax injected into another language. Every fixer now declares the language families
  it may touch (`FIXER_FAMILIES`); anything else gets a manual suggestion instead of a
  broken patch. JavaScript has its own secret fixer (`process.env.NAME`).
* **Valid TypeScript was reported as not compiling.** `node --check` refuses `.ts` files
  (`ERR_UNKNOWN_FILE_EXTENSION`), so every TypeScript snippet showed "compile: FAILED".
  TypeScript now goes through `tsc --noEmit` when the toolchain is installed, and
  otherwise reports "syntax check skipped" (like Java/Go/C). `node --check` errors that
  are purely about the file extension are also treated as skipped, never as failures.
* **JavaScript patches had no syntax safety net.** `_syntax_ok` returned True for every
  non-Python language, so a bad JS patch would be accepted. JavaScript patches are now
  validated with `node --check` before they are kept.
* `console.log` (`QUA103`) no longer maps to the Python `print` fixer; it is a manual
  suggestion, since a project logger is language specific.

### Verified per language

| Language | Review | Compile check | Auto-rewrite |
| --- | --- | --- | --- |
| Python | AST rules (40) | `compile()` | 21 fixers |
| JavaScript | regex rules (13) | `node --check` | `var`→`const`, `==`→`===`, `debugger`, `process.env` secret |
| TypeScript | regex rules | `tsc --noEmit` (or skipped) | `==`→`===`, `process.env` secret |
| Java, Go, Ruby, PHP, C, C++, C#, Shell | regex rules | skipped (no parser) | none — manual guidance |

* 180 tests (4 new), `ruff check .` clean, 45/45 external stress checks.

## 2.1.1 — Compiler module hardening (found by stress-testing it)

A 45-check stress run plus a GUI walkthrough of the Compiler module turned up three
real defects. All are fixed, with regression tests.

### Fixed

* **Rewritten file could crash on import.** The logging setup line
  (`logger = logging.getLogger(__name__)`) was inserted at line 2, i.e. *above*
  `import logging`, whenever the module started with a docstring or comments. The file
  compiled but raised `NameError` the moment it was imported. Imports and the logger are
  now always placed after the module docstring and after the last import.
* **A fix could delete an import another fix had just made necessary.** In a batched
  sweep, `import os` was removed as "unused" using an analysis taken *before*
  `os.system(...)` was rewritten into `os.getenv(...)`/`subprocess.run(...)`, leaving a
  file that referenced `os` without importing it. Deletion-style fixers (`BUG004`,
  unused imports) now run only on a freshly analysed source, alone.
* **Module docstring could end up in the middle of the file**, producing a duplicate
  docstring on the next rewrite (rewriting was not idempotent). The docstring fixer now
  checks the AST for an existing module docstring and always inserts before the imports.

### Improved

* **Batched rewriting.** Fixes are applied bottom-up within a sweep, so a patch that
  inserts or deletes lines only shifts lines already handled; a sweep stops early if a
  patch touches anything above its own line. A 719-line file with 481 fixable issues now
  finishes in **~6s instead of ~17s** (and in 2 sweeps instead of being capped at 15
  fixes). Typical snippets stay instant.
* Patch validation is no longer done twice per fix (the rewriter validates with
  `compile()`; the fixers can skip their internal re-parse).
* `max_passes` now limits *sweeps* (default 40) rather than individual fixes.

### Verified

* 45/45 checks in an external stress run: 20 bug-pattern snippets, empty input, syntax
  errors, clean code, CRLF + tabs + unicode, a 719-line file, idempotency, diff shape,
  language detection, Java/Go/C passthrough, `use_llm` degradation, `compile_check`.
* Rewritten modules are now **executed** in the tests (`exec`/`import`) to prove they do
  not reference anything they no longer import.
* 176 tests (4 new), `ruff check .` clean.

## 2.1.0 — Compiler page (paste → review → rewrite)

### Added

* **Compiler page** (`ui/widgets/compiler_page.py`, sidebar entry *Compiler*): paste code,
  compile check, five-agent review, one-click rewrite with diff and copy/save.
* `services/playground_service.py` — `PlaygroundService` reviews and rewrites a single
  snippet with no database and no project: `compile_check`, `review_snippet`,
  `rewrite_snippet`, plus language auto-detection from code or filename.
* **Iterative rewriter**: applies the highest-severity fixable finding, re-analyses, and
  repeats (up to 15 passes) so line numbers never go stale; every Python patch is
  validated with `compile()` and skipped if it would break the file.
* Optional *AI rewrite* checkbox: asks the LLM for a full-file rewrite and keeps it only
  when the returned code parses.
* CLI: `python run.py rewrite FILE [--diff] [--out] [--llm] [--language]` (reads stdin with
  `-`).
* Secret detection now recognises token *shapes* regardless of the variable name:
  Stripe (`sk_live_`/`sk_test_`), OpenAI (`sk-…`), Google (`AIza…`), AWS (`AKIA…`),
  GitHub (`ghp_…`), Slack (`xox…`) — and the rewriter can swap them for an environment
  lookup like any other hardcoded credential.
* 17 new tests (172 total).

### Fixed

* The module-docstring fixer refused to add a docstring whenever the file contained any
  triple-quoted string (e.g. a function docstring); it now only checks whether the first
  statement is already a docstring.
* The docstring fixers received no filename when used through the playground, producing
  `"""Module module."""` instead of the real module name.

## 2.0.0 — Phases 2–10 delivered

Everything that was `Pending` in the roadmap is now implemented, tested and wired into
the UI. Phase 1 code is unchanged in behaviour.

### Fixed (pre-existing Phase 1 defects)

* `database/models.py` declared `Base` **twice** and duplicated all ten model classes.
  The second registry silently won, so `Project.analysis_runs` (and its
  `back_populates`) pointed at a dead class. Now a single `Base` and one definition per
  table.
* Existing SQLite databases were never upgraded when new columns appeared. Startup now
  adds missing nullable columns (`DatabaseManager._apply_lightweight_migrations`).
* `datetime.utcnow()` deprecation warnings (Python 3.12+) replaced by
  `core.timeutils.utcnow()`.
* `GEMINI_MODEL="YOUR_SUPPORTED_GEMINI_MODEL"` in `.env` produced an HTTP 400 on every
  call; placeholder model names are now ignored, and a retired model name auto-switches
  to the replacement named in the API error.

### Added

**Phase 3 — static analysis**
* `analyzer/rules/` — rule registry plus 56 rules: 40 Python AST rules, 13 regex rules
  for JS/TS/Java/Go/Ruby/PHP/C-family, 3 project-level rules (duplication, missing and
  circular dependencies).
* `analyzer/complexity.py` — cyclomatic complexity, nesting, Halstead volume,
  maintainability index.
* `analyzer/duplicates.py` — shingled duplicate-block detection with maximal-block merge.
* `analyzer/dependencies.py` — stdlib/local/external resolution, missing packages,
  Tarjan SCC cycle detection.
* `analyzer/engine.py` — `StaticAnalysisEngine` (per file and per project).
* `services/analysis_service.py` — persists runs, findings, metrics, duplicate groups and
  dependencies; query API for the UI and reports.

**Phase 4 — LLM layer**
* `llm/base.py`, `llm/local_provider.py`, `llm/gemini_provider.py`, `llm/factory.py`,
  `llm/insights.py`. Gemini over plain REST (no SDK), key in a header, fast probe,
  process-wide health caching, deterministic fallback.

**Phase 5 — multi-agent review**
* Five agents (`agents/bug_agent.py`, `security_agent.py`, `performance_agent.py`,
  `quality_agent.py`, `documentation_agent.py`) on a shared `ReviewAgent` base with
  severity-weighted, capped scoring.
* `agents/orchestrator.py` — weighted aggregation, release-blocking score caps, risk
  levels, per-agent failure isolation.
* `services/review_service.py` — persists `ReviewSession` + one `AgentReview` per agent;
  trend, leaderboard, diff-scoped reviews.

**Phase 6/7 — repair and verification**
* `repair/fixers.py` — 22 template fixers, each validated by re-parsing the patched
  source; manual guidance for everything else.
* `repair/engine.py` — suggestion/apply/reject/revert with `.bak` backups.
* `verification/verifier.py` — syntax, structure and project test-suite checks persisted
  as `VerificationResult`.

**Phase 8 — quality intelligence**
* `reports/generator.py` — markdown, HTML and JSON reports; project quality summary.
* Risk Map and History pages with a score trend sparkline.

**Phase 9 — git intelligence**
* `analyzer/diff_parser.py` + `--diff` on the CLI; reviews can be scoped to changed lines.

**Phase 10 — finalisation**
* Headless CLI (`app/cli.py`): `analyze`, `review`, `report`, `fix`, `rules`, `agents`.
* Nine sidebar pages replace the placeholder screens; long operations run on worker
  threads so the GUI never blocks.
* 148 tests (was 22).

### Breaking changes

* `MainWindow` takes an optional `config` argument (backwards compatible).
* `agents/__init__.py` no longer exports a stub `ReviewAgent` with a throwing
  `run_review`; it exports the real base class and the five agents.
* `review_sessions` gained `analysis_run_id`, `risk_level`, `summary`, `provider`
  (auto-added to existing databases).

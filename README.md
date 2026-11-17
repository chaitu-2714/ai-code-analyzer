# AI Code Review & Automated Repair Platform

A modular, multi-agent desktop application for reviewing a codebase: static analysis,
five specialist review agents, automated repair suggestions, fix verification and
quality reporting — all of it runnable offline.

```bash
python run.py                          # desktop GUI (PySide6)
python run.py review ./my_project      # headless: analyse + review a folder
python run.py rewrite snippet.py       # paste-and-rewrite one file
```

---

## Phase Roadmap & Status

```text
Phase 1  — Project Foundation        ✓ Completed  (config, logging, SQLite schema, ingestion, GUI shell)
Phase 2  — Code Understanding        ✓ Completed  (AST extraction, imports, language + metadata detection)
Phase 3  — Static Analysis           ✓ Completed  (56 rules, complexity, duplication, dependency graph)
Phase 4  — Gemini Integration        ✓ Completed  (provider abstraction + offline fallback)
Phase 5  — Multi-Agent Review        ✓ Completed  (Bug, Security, Performance, Quality, Documentation)
Phase 6  — AI Code Repair            ✓ Completed  (22 template fixers + manual guidance)
Phase 7  — Fix Verification          ✓ Completed  (syntax check, node --check, project test suite)
Phase 8  — Quality Intelligence      ✓ Completed  (scores, risk map, trend, markdown/HTML/JSON reports)
Phase 9  — Git Intelligence          ✓ Completed  (unified-diff parsing, review scoped to changed lines)
Phase 10 — Finalization              ✓ Completed  (headless CLI, 180 tests, docs)
Phase 11 — Compiler Playground       ✓ Completed  (paste → compile → multi-agent review → rewrite)
```

---

## Compiler page — paste, review, rewrite

The sidebar entry **Compiler** is a playground for a single snippet. Paste code, pick a
language (or leave it on *Auto detect*), then:

**Language support**

| Language | Review | Compile check | Auto-rewrite |
| --- | --- | --- | --- |
| Python | AST rule pack (40 rules) | `compile()` — real | 21 template fixers |
| JavaScript | regex rule pack | `node --check` | `var`→`const`, `==`→`===`, `debugger`, secrets → `process.env` |
| TypeScript | regex rule pack | `tsc --noEmit` when installed, else skipped | `==`→`===`, secrets → `process.env` |
| Java, Go, Ruby, PHP, C, C++, C#, Shell | regex rule pack | skipped (no parser available) | none — manual guidance only |

Fixers are language gated, so a Python patch can never be injected into Ruby or PHP.


1. **Compile Check** — a real parse, not a guess: `compile()` for Python, `node --check`
   for JavaScript. **Pasted code is never executed**, only parsed and analysed.
2. **Analyze & Review** — the same five agents that review a project score the snippet and
   explain the findings (score, risk, per-agent table, per-agent insights, findings list).
3. **Rewrite Code** — the fixers sweep the file from the bottom up (so a patch that
   inserts or deletes lines only shifts lines already handled), re-analysing between
   sweeps and stopping a sweep early whenever a patch touches anything above its own
   line. Deletion-style fixers (unused imports) run alone on fresh analysis. You get the
   rewritten file, a unified diff, the list of applied fixes, the score before → after,
   and a final compile check. Copy it back or save it.

Typical result on a sloppy 10-line snippet: **6 fixes applied, score 65 → 99.8, risk
CRITICAL → LOW, code still compiles**. A 719-line file with 481 fixable issues is
rewritten in ~6s (2 sweeps). Every Python patch is validated with `compile()` before it is
kept; a patch that would break the file is skipped and reported. Imports and the logging
setup are always placed after the module docstring, and the rewritten module is executed
in the test suite to prove it does not reference anything it no longer imports.

*AI rewrite* (checkbox) additionally asks the configured LLM for a full-file rewrite. The
reply is accepted only if it parses; otherwise it is discarded and the deterministic
rewrite is kept.

The same engine is available headless:

```bash
python run.py rewrite snippet.py --diff        # show the patch
python run.py rewrite snippet.py --out fixed.py
cat snippet.py | python run.py rewrite - --language Python
```

---

## The five review agents

Each agent owns a slice of the findings, scores it 0–100 and writes a short narrative.
Weights are normalised automatically and sum to 1.0.

| Agent | Weight | Owns | What it looks for |
| --- | --- | --- | --- |
| **Bug Detection Agent** | 0.25 | `BUG`, `SYNTAX` | bare `except`, swallowed exceptions, mutable defaults, `return` in `finally`, self-assignment, syntax errors, unused imports |
| **Security Analysis Agent** | 0.25 | `SECURITY` | `eval`/`exec`, `shell=True`, `os.system`, unsafe deserialisation, `yaml.load`, hardcoded secrets, weak hashes, SQL string building, disabled TLS, XSS sinks, insecure `http://` |
| **Performance Analysis Agent** | 0.15 | `PERFORMANCE` | leaked file handles, quadratic string building, `range(len(...))`, triple-nested loops |
| **Code Quality Agent** | 0.20 | `QUALITY`, `DUPLICATION`, `DEPENDENCY` | long functions, parameter bloat, cyclomatic complexity, deep nesting, wildcard imports, `print`, missing type hints, duplicated blocks, missing/circular imports |
| **Documentation Agent** | 0.15 | `DOCUMENTATION` | module/class/function docstrings, comment ratio |

**Scoring.** Every finding carries a severity penalty (CRITICAL 20, HIGH 10, MEDIUM 4,
LOW 1.5, INFO 0.4) with diminishing returns, plus agent-specific metric penalties
(complexity, maintainability index, duplication, comment ratio). The overall score is
the weighted average, **capped at 65 when any CRITICAL finding exists** and at 80 when
three or more HIGH findings exist, so a dangerous release can never look clean.

**Risk levels.** `CRITICAL` (any critical finding, or score < 40), `HIGH` (< 60 or ≥ 5
high), `MODERATE` (< 80 or any high), `LOW` (otherwise).

### Offline by design

Agents always work. The narrative comes from the configured LLM provider when one is
reachable, and from the deterministic local analyser otherwise:

* `LLM_PROVIDER=auto` (default) — Gemini when `GEMINI_API_KEY` is set and reachable.
* `LLM_PROVIDER=local` — never touches the network.
* `LLM_PROVIDER=gemini` — Gemini only (still degrades gracefully on error).

A provider that fails once (probe, timeout, HTTP error) is disabled for the rest of the
process, so a blocked network costs one short probe instead of one timeout per agent.

---

## Static analysis (Phase 3)

* **56 rules** across `SYNTAX`, `BUG`, `SECURITY`, `PERFORMANCE`, `QUALITY`,
  `DOCUMENTATION`, `DUPLICATION`, `DEPENDENCY`. List them with `python run.py rules`.
* **Python** is analysed from the AST (scope-aware: unused imports, mutable defaults,
  SQL built by interpolation, secret assignments, nesting depth, complexity).
* **Other languages** (JS/TS, Java, Go, Ruby, PHP, C/C++, C#, Shell) use a regex/line
  pack that still covers secrets, injection sinks, XSS, loose equality, `var`,
  `console.log`, `debugger`, TODOs and long lines.
* **Complexity**: cyclomatic complexity per function, nesting depth, Halstead volume and
  the SEI maintainability index (non-Python uses keyword heuristics).
* **Duplication**: shingled normalised-line hashing with forward extension, then
  maximal-block de-duplication (identical blocks across files, ≥ 6 lines).
* **Dependencies**: stdlib vs local vs external resolution, missing packages and
  Tarjan SCC cycle detection.

Every finding is stored with file, line, column, code snippet, suggestion, confidence,
detector and status — nothing is recomputed on read.

---

## Automated repair (Phases 6–7)

`RepairEngine.suggest_for_finding()` produces a unified diff without touching the file.
22 rules have template fixers (e.g. bare `except` → `except Exception:`, `eval` →
`ast.literal_eval`, hardcoded secret → `os.getenv`, missing docstrings, `yaml.load` →
`yaml.safe_load`, `== None` → `is None`, mutable defaults → `None` + guard).
**Every Python patch is re-parsed before it is offered**, so a fixer can never emit a
file that no longer compiles. Findings without a safe template get a *manual* suggestion
with concrete guidance instead of a guess.

`apply()` writes the file, keeps a `.bak` copy, and `revert()` restores it. `FixVerifier`
then checks the patched source (syntax, structure) and, when asked, runs the project's own
`pytest` suite with a timeout.

---

## Reports (Phase 8)

`ReportGenerator` renders markdown, HTML (self-contained, dark theme) or JSON from any
review session: overall score, risk, per-agent scores, severity mix and the top findings
with locations and fixes.

---

## Git intelligence (Phase 9)

`analyzer/diff_parser.py` parses `git diff` output into per-file added-line maps, so a
review can be scoped to a pull request:

```bash
git diff origin/main > changes.diff
python run.py review --project 3 --diff changes.diff --report pr_review.md
```

---

## Project layout

```
app/            entry point (GUI + headless CLI dispatch)
agents/         base agent, five specialist agents, orchestrator
analyzer/       AST/import parsers, rules/, complexity, duplicates, dependencies, engine, diff parser
core/           config, constants, exceptions, logger, timeutils
database/       connection (+ schema upgrades), models, repositories
llm/            provider interface, local provider, Gemini provider, factory, insights
repair/         fixers + repair engine
reports/        markdown/HTML/JSON generator
services/       ingestion, analysis service, review service, playground (paste & rewrite)
ui/             main window, pages (compiler, analysis, reviews, issues, risk map, history, settings), styles
verification/   fix verifier
tests/          180 tests
```

---

## Setup

Prerequisites: **Python 3.12+** (3.14 also tested).

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                  # then edit
python run.py
```

Headless / CI machines can skip the GUI entirely — the CLI never imports PySide6:

```bash
python run.py analyze ./project            # import + analyse, print the worst findings
python run.py review  --project 1          # run the five agents
python run.py report  --project 1 --format html --out report.html
python run.py fix     --project 1 --apply --verify
python run.py rules | agents
```

---

## Configuration (`.env`)

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_NAME`, `APP_VERSION` | `AI Code Reviewer`, `1.0.0` | Window title / about |
| `DATABASE_URL` | `sqlite:///data/code_reviewer.db` | Any SQLAlchemy URL (SQLite supported) |
| `LOG_LEVEL`, `LOG_FILE` | `INFO`, `logs/application.log` | Logging |
| `DEBUG_MODE` | `True` | Verbose console output |
| `LLM_PROVIDER` | `auto` | `auto` \| `local` \| `gemini` |
| `GEMINI_API_KEY` | *(empty)* | Enables Gemini when set. **Never commit it.** |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Placeholder values are ignored; a retired model auto-switches to the one named in the API error |
| `GEMINI_TIMEOUT` | `15` | Seconds per request |
| `AGENTS_ENABLED` | `true` | Toggle multi-agent review |
| `MAX_FILE_SIZE_BYTES` | `1000000` | Files above this are not analysed |
| `COMPLEXITY_THRESHOLD` | `10` | Cyclomatic complexity limit per function |
| `LONG_FUNCTION_THRESHOLD` | `50` | Function length limit (lines) |
| `DUPLICATE_WINDOW_LINES` | `6` | Shingle size for duplication |
| `VERIFY_TIMEOUT_SECONDS` | `120` | Timeout for the project test suite |

Databases created by an earlier version are upgraded in place: new **nullable** columns
are added automatically at startup (`DatabaseManager._apply_lightweight_migrations`).

---

## Testing

```bash
QT_QPA_PLATFORM=offscreen pytest -q      # 180 tests, ~30s
ruff check .            # lint (config in ruff.toml)
```

Coverage: rule packs (Python + regex), complexity, duplication, dependencies, engine,
LLM layer (incl. HTTP failures and health caching), agents and scoring, analysis and
review services, repair fixers and apply/revert, verification, reports, diff parsing,
CLI, schema integrity, the compiler playground (snippet review + rewrite) and GUI page
wiring.

---

## Known limits

* Non-Python languages get regex-level analysis, not a full parser.
* Unused-import detection is module-scope only (a name used only inside `__all__` or a
  re-export may be reported).
* Maintainability index uses an approximated Halstead volume for Python and a
  line-based approximation elsewhere — compare it against itself over time, not against
  other tools.
* Template fixers are intentionally conservative; anything that would change semantics
  is returned as a manual suggestion.
* Gemini generation requires outbound HTTPS. When it is blocked the platform silently
  uses the offline provider (see `logs/application.log`).

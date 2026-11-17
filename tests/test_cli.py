"""Headless CLI: analyze, review, report, fix, rules and agents."""
import json

from app.cli import main


def run_cli(tmp_path, *args):
    db = f"sqlite:///{tmp_path / 'cli.db'}"
    return main(["--db", db, *args])


def test_rules_and_agents_commands(tmp_path, capsys):
    assert run_cli(tmp_path, "rules") == 0
    assert "rules registered" in capsys.readouterr().out

    assert run_cli(tmp_path, "agents") == 0
    assert "Bug Detection Agent" in capsys.readouterr().out


def test_analyze_review_and_report(tmp_path, sample_dir, capsys):
    assert run_cli(tmp_path, "analyze", str(sample_dir)) == 0
    output = capsys.readouterr().out
    assert "Analysis complete" in output
    assert "CRITICAL" in output

    report_path = tmp_path / "review.md"
    assert (
        run_cli(
            tmp_path, "review", "--project", "1", "--report", str(report_path), "--provider", "local"
        )
        == 0
    )
    review_output = capsys.readouterr().out
    assert "Review #1" in review_output
    assert "Security Analysis Agent" in review_output
    assert report_path.exists()

    assert run_cli(tmp_path, "report", "--project", "1", "--format", "json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project_id"] == 1


def test_fix_command_lists_suggestions(tmp_path, sample_dir, capsys):
    run_cli(tmp_path, "analyze", str(sample_dir))
    capsys.readouterr()
    assert run_cli(tmp_path, "fix", "--project", "1", "--limit", "5") == 0
    output = capsys.readouterr().out
    assert "suggestion(s)" in output
    assert "auto-patchable" in output


def test_review_with_json_flag(tmp_path, sample_dir, capsys):
    run_cli(tmp_path, "analyze", str(sample_dir))
    capsys.readouterr()
    assert run_cli(tmp_path, "review", "--project", "1", "--json", "--provider", "local") == 0
    output = capsys.readouterr().out
    json_blob = output[output.index("{") :]
    payload = json.loads(json_blob)
    assert len(payload["agents"]) == 5


def test_rewrite_command(tmp_path, capsys):
    source = tmp_path / "snippet.py"
    source.write_text("import os\ndef run(p, c=[]):\n    return eval(p)\n")
    target = tmp_path / "fixed.py"

    assert run_cli(tmp_path, "rewrite", str(source), "--out", str(target)) == 0
    output = capsys.readouterr().out
    assert "fix(es) applied" in output
    assert target.exists()

    fixed = target.read_text()
    assert "ast.literal_eval" in fixed
    assert "cache" not in fixed
    compile(fixed, "fixed.py", "exec")


def test_rewrite_command_diff_mode(tmp_path, capsys):
    source = tmp_path / "snippet.py"
    source.write_text("def f(p):\n    return eval(p)\n")
    assert run_cli(tmp_path, "rewrite", str(source), "--diff") == 0
    assert "--- a/snippet.py" in capsys.readouterr().out


def test_missing_path_returns_error_code(tmp_path, capsys):
    assert run_cli(tmp_path, "analyze", str(tmp_path / "does-not-exist")) == 2
    assert "does not exist" in capsys.readouterr().err


def test_zip_import(tmp_path, sample_dir, capsys):
    import shutil

    archive = shutil.make_archive(str(tmp_path / "sample_zip"), "zip", root_dir=sample_dir)
    assert run_cli(tmp_path, "analyze", archive) == 0
    assert "Imported" in capsys.readouterr().out

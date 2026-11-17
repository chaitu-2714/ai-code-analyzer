"""Application entry point.

Runs the desktop GUI by default.  Any command from ``app/cli.py`` (analyze,
review, report, fix, rules, agents) is dispatched to the headless CLI, so the
platform also works on servers and in CI::

    python run.py                      # desktop GUI
    python run.py analyze ./project    # headless static analysis
    python run.py rewrite file.py      # rewrite one file with the fixers
"""
import argparse
import sys

CLI_COMMANDS = {"analyze", "review", "report", "fix", "rewrite", "rules", "agents"}


def _split_cli_arguments(argv):
    """Splits ``--env``/``--db`` globals from the CLI subcommand arguments."""
    if not argv:
        return None
    for index, token in enumerate(argv):
        if token in CLI_COMMANDS:
            globals_ = argv[:index]
            return globals_ + argv[index:]
    return None


def main() -> None:
    argv = sys.argv[1:]
    cli_args = _split_cli_arguments(argv)
    if cli_args is not None:
        from app.cli import main as cli_main

        sys.exit(cli_main(cli_args))

    parser = argparse.ArgumentParser(description="AI Code Reviewer & Automated Repair Platform")
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Path to environment file (defaults to .env)",
    )
    args = parser.parse_args(argv)

    from app.application import AIReviewerApplication

    app = AIReviewerApplication(env_path=args.env)
    if not app.initialize():
        sys.exit(1)

    sys.exit(app.run())


if __name__ == "__main__":
    main()

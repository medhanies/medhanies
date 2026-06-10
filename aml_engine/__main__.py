"""Command-line interface.

    python -m aml_engine run      --seed 42 [--customers 200] [--days 90]
                                  [--out output/] [--format both]
                                  [--min-severity LOW] [--no-eval]
    python -m aml_engine generate --seed 42 --out output/transactions.csv
    python -m aml_engine detect   --input output/transactions.csv [--out output/]
    python -m aml_engine rules
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aml_engine import __version__
from aml_engine.engine import run_detection
from aml_engine.generator import generate_dataset
from aml_engine.models import Severity
from aml_engine.report import (
    export_all,
    render_console_report,
    render_rule_catalog,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aml-engine",
        description="Rules-based AML transaction flagging engine (synthetic data).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="generate data, run detection, print report")
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--customers", type=int, default=200)
    run.add_argument("--days", type=int, default=90)
    run.add_argument("--out", type=Path, default=None, help="export directory")
    run.add_argument("--format", choices=["csv", "json", "both"], default="both")
    run.add_argument(
        "--min-severity",
        type=lambda s: Severity(s.upper()),
        default=Severity.LOW,
        help="minimum alert tier shown in the console report",
    )
    run.add_argument(
        "--no-eval",
        action="store_true",
        help="suppress the planted-scenario validation section",
    )

    gen = sub.add_parser("generate", help="generate synthetic transactions to CSV")
    gen.add_argument("--seed", type=int, default=42)
    gen.add_argument("--customers", type=int, default=200)
    gen.add_argument("--days", type=int, default=90)
    gen.add_argument("--out", type=Path, required=True, help="output CSV path")

    det = sub.add_parser("detect", help="run detection on a transactions CSV")
    det.add_argument("--input", type=Path, required=True)
    det.add_argument("--out", type=Path, default=None, help="export directory")
    det.add_argument("--format", choices=["csv", "json", "both"], default="both")

    sub.add_parser("rules", help="print the rule catalog with citations")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    dataset = generate_dataset(seed=args.seed, n_customers=args.customers, days=args.days)
    result = run_detection(dataset.transactions, dataset.accounts, dataset.customers)
    print(
        render_console_report(
            dataset,
            result,
            min_severity=args.min_severity,
            show_eval=not args.no_eval,
        )
    )
    if args.out is not None:
        for path in export_all(dataset, result, args.out, args.format):
            print(f"wrote {path}")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    dataset = generate_dataset(seed=args.seed, n_customers=args.customers, days=args.days)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    dataset.write_transactions_csv(args.out)
    print(f"wrote {len(dataset.transactions)} transactions to {args.out}")
    return 0


def _cmd_detect(args: argparse.Namespace) -> int:
    from aml_engine.models import Dataset, read_transactions_csv

    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 2
    transactions = read_transactions_csv(args.input)
    # CSV input carries no customer/account master data, so entity-level
    # beneficial-ownership rules have nothing to evaluate; transaction-level
    # rules still run. The `run` command exercises the full catalog.
    dataset = Dataset(customers=[], accounts=[], transactions=transactions)
    result = run_detection(transactions, [], [])
    print(render_console_report(dataset, result, show_eval=False))
    if args.out is not None:
        for path in export_all(dataset, result, args.out, args.format):
            print(f"wrote {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    commands = {
        "run": _cmd_run,
        "generate": _cmd_generate,
        "detect": _cmd_detect,
        "rules": lambda _: (print(render_rule_catalog()), 0)[1],
    }
    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())

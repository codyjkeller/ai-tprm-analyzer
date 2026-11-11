"""Command line: python -m tprm analyze <vendor file>"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from tprm import __version__
from tprm.evaluate import FAIL, NEEDS_REVIEW, PASS, apply_guardrails
from tprm.llm import DISPLAY_NAMES, PROVIDERS, EvaluationError, evaluate_llm, make_complete_fn, resolve_model
from tprm.policy import PolicyError, load_policy
from tprm.report import STATUS_TEXT, build_record, write_reports
from tprm.rules import evaluate_rules
from tprm.scoring import score_findings
from tprm.vendor import VendorInputError, load_vendor

DEFAULT_POLICY = "policies/vendor_standards.yaml"
STATUS_STYLE = {PASS: "green", FAIL: "red", NEEDS_REVIEW: "yellow"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tprm",
        description="Assess a vendor's security answers against your policy.",
    )
    parser.add_argument("--version", action="version", version=f"ai-tprm-analyzer {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="Assess one vendor file and write a report.")
    analyze.add_argument("vendor_file", help="The vendor's answers: .json, .csv, .xlsx, .txt, .md or .pdf")
    analyze.add_argument("--policy", default=DEFAULT_POLICY, help=f"Policy file (default: {DEFAULT_POLICY})")
    analyze.add_argument(
        "--provider", choices=("rules",) + PROVIDERS, default=None,
        help="rules = offline keyword screen (default). anthropic / openai = AI review; "
             "the vendor's text is sent to that provider.",
    )
    analyze.add_argument("--model", default=None, help="Model name for AI review (or set TPRM_MODEL).")
    analyze.add_argument("--vendor-name", default=None, help="Vendor name to show in the report.")
    analyze.add_argument("--out", default="reports", help="Folder for report files (default: reports)")
    analyze.add_argument("--no-files", action="store_true", help="Print the result only; write no report files.")

    check = commands.add_parser("check-policy", help="Validate the policy file and list what it will check.")
    check.add_argument("--policy", default=DEFAULT_POLICY, help=f"Policy file (default: {DEFAULT_POLICY})")
    return parser


def run_check_policy(args, console: Console) -> int:
    policy = load_policy(args.policy)
    table = Table(title=f"{args.policy} is valid", box=box.SIMPLE_HEAD)
    for column in ("Framework", "Control", "Domain", "Weight", "Scored", "Critical"):
        table.add_column(column)
    for c in policy.controls:
        table.add_row(escape(c.framework), escape(c.id), escape(c.domain), str(c.weight),
                      "yes" if c.required else "no", "yes" if c.critical else "no")
    console.print(table)
    total = sum(c.weight for c in policy.scored_controls)
    console.print(f"{len(policy.controls)} controls from {len(policy.active_frameworks)} active framework(s). "
                  f"Total scored weight: {total}.")
    return 0


def run_analyze(args, console: Console) -> int:
    policy = load_policy(args.policy)
    submission = load_vendor(args.vendor_file, name=args.vendor_name)
    provider = args.provider or os.getenv("TPRM_PROVIDER", "").strip().lower() or "rules"
    if provider not in ("rules",) + PROVIDERS:
        raise EvaluationError(f"TPRM_PROVIDER is '{provider}'. Use rules, anthropic or openai.")

    model: Optional[str] = None
    if provider == "rules":
        console.print("[dim]Mode: offline keyword screen. Nothing leaves this computer.[/dim]")
        verdicts = evaluate_rules(policy, submission)
    else:
        model = resolve_model(provider, args.model)
        complete = make_complete_fn(provider, model)
        console.print(f"[yellow]Mode: AI review. Sending the vendor document text to {DISPLAY_NAMES[provider]} "
                      f"({escape(model)}).[/yellow]")
        with console.status("Waiting for the AI review..."):
            verdicts = evaluate_llm(policy, submission, complete)

    findings = apply_guardrails(verdicts, policy, submission)
    score = score_findings(findings, policy, keyword_screen_only=provider == "rules")
    record = build_record(policy, submission, findings, score, provider, model)

    table = Table(title=f"Vendor: {escape(submission.name)}", box=box.SIMPLE_HEAD, show_lines=False)
    table.add_column("Result")
    table.add_column("Control")
    table.add_column("Why", overflow="fold")
    order = {FAIL: 0, NEEDS_REVIEW: 1, PASS: 2}
    for f in sorted(findings, key=lambda item: order[item.status]):
        why = " ".join([f.rationale] + f.notes).strip()
        table.add_row(f"[{STATUS_STYLE[f.status]}]{STATUS_TEXT[f.status]}[/]",
                      escape(f"{f.control_id} {f.domain}"), escape(why))
    console.print(table)

    for warning in submission.warnings:
        console.print(f"[bold red]Warning:[/bold red] {escape(warning)}")
    color = "red" if score.failed else "yellow" if score.needs_review else "green"
    console.print(Panel(
        f"[bold {color}]{escape(score.rating)}[/bold {color}]\n"
        f"Score: {score.score} out of {score.max_score}\n{escape(score.summary)}",
        title="Result", expand=False,
    ))

    if not args.no_files:
        paths = write_reports(record, Path(args.out))
        console.print(f"Report for people:   {paths['markdown']}")
        console.print(f"Data for systems:    {paths['json']}  {paths['csv']}")
    console.print("[dim]This is decision support. A qualified person must review it before approving a vendor.[/dim]")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    console = Console()
    try:
        if args.command == "check-policy":
            return run_check_policy(args, console)
        return run_analyze(args, console)
    except (PolicyError, VendorInputError, EvaluationError) as error:
        Console(stderr=True).print(f"[bold red]Error:[/bold red] {escape(str(error))}")
        return 2


if __name__ == "__main__":
    sys.exit(main())

"""Builds the assessment record and writes it as JSON, Markdown and CSV."""
from __future__ import annotations

import csv
import html
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from tprm import __version__
from tprm.evaluate import FAIL, NEEDS_REVIEW, PASS, Finding
from tprm.llm import DISPLAY_NAMES
from tprm.policy import Policy
from tprm.scoring import Score
from tprm.vendor import VendorSubmission

STATUS_TEXT = {PASS: "Pass", FAIL: "Fail", NEEDS_REVIEW: "Needs review"}

DISCLAIMER = (
    "This report supports a decision; it does not make one. It reflects only what the vendor wrote in the "
    "document that was analyzed, and it has not verified that the vendor does what it says. A qualified "
    "person must review it before a vendor is approved or rejected."
)

METHOD_TEXT = {
    "rules": (
        "Offline keyword screen. The vendor's text was searched for the terms listed in the policy. "
        "Nothing was sent outside this computer. A keyword screen cannot understand meaning, so its "
        "passes should be confirmed by a person or by an AI review."
    ),
    "ai": (
        "AI review using {provider} model `{model}`. The vendor's text was sent to that provider. "
        "Every Pass and Fail quotes the vendor's own words, and each quote was checked by code against "
        "the document. AI verdicts can differ between runs."
    ),
}


def build_record(policy: Policy, submission: VendorSubmission, findings: list[Finding], score: Score,
                 provider: str, model: Optional[str], generated_at: Optional[datetime] = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc)
    return {
        "tool": {"name": "ai-tprm-analyzer", "version": __version__},
        "generated_at": generated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vendor": {"name": submission.name, "file": submission.path, "sha256": submission.sha256},
        "policy": {"file": policy.path, "sha256": policy.sha256, "active_frameworks": policy.active_frameworks},
        "method": {"evaluator": provider, "model": model},
        "result": asdict(score),
        "warnings": list(submission.warnings),
        "findings": [asdict(finding) for finding in findings],
        "disclaimer": DISCLAIMER,
    }


def neutralize_formula(value) -> str:
    """Stops spreadsheet tools from running a cell as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text


def _cell(value) -> str:
    """Makes vendor-supplied text safe inside a Markdown table."""
    text = html.escape(" ".join(str(value or "").split()), quote=False)
    return text.replace("|", "\\|").replace("`", "'") or "-"


def _method_sentence(record: dict) -> str:
    method = record["method"]
    if method["evaluator"] == "rules":
        return METHOD_TEXT["rules"]
    provider = DISPLAY_NAMES.get(method["evaluator"], method["evaluator"])
    return METHOD_TEXT["ai"].format(provider=provider, model=method["model"])


def to_markdown(record: dict) -> str:
    result, findings = record["result"], record["findings"]
    failed = [f for f in findings if f["status"] == FAIL]
    review = [f for f in findings if f["status"] == NEEDS_REVIEW]
    passed = [f for f in findings if f["status"] == PASS]

    lines = [
        f"# Vendor Risk Assessment: {_cell(record['vendor']['name'])}",
        "",
        "## Executive summary",
        "",
        "| | |",
        "| :--- | :--- |",
        f"| **Rating** | **{_cell(result['rating'])}** |",
        f"| **Score** | {result['score']} out of {result['max_score']} |",
        f"| **Score if every open item is confirmed** | {result['best_case_score']} out of {result['max_score']} |",
        f"| **Controls checked** | {len(findings)}: {result['passed']} passed, {result['failed']} failed, "
        f"{result['needs_review']} need review |",
        f"| **Standards applied** | {_cell(', '.join(record['policy']['active_frameworks']))} |",
        f"| **Assessed** | {record['generated_at']} (UTC) |",
        "",
        result["summary"],
        "",
    ]
    for warning in record["warnings"]:
        lines += [f"> **Warning:** {_cell(warning)}", ""]

    lines += ["### What to do next", ""]
    if failed:
        lines.append("Resolve these with the vendor before onboarding:")
        lines += [f"- **{_cell(f['control_id'])} {_cell(f['domain'])}:** {_cell(f['recommendation'])}" for f in failed]
        lines.append("")
    if review:
        lines.append("Ask the vendor for evidence, or check their document yourself:")
        lines += [f"- **{_cell(f['control_id'])} {_cell(f['domain'])}:** {_cell(f['recommendation'])}" for f in review]
        lines.append("")
    if not failed and not review:
        lines += ["No open items. Confirm the passes below against the vendor's document, "
                  "then record your decision.", ""]

    def table(title: str, rows: list[dict]) -> list[str]:
        if not rows:
            return []
        out = [f"### {title} ({len(rows)})", "",
               "| Control | Requirement | What the vendor wrote | Assessment |",
               "| :--- | :--- | :--- | :--- |"]
        for f in rows:
            tags = (" (critical)" if f["critical"] else "") + ("" if f["required"] else " (not scored)")
            assessment = " ".join([f["rationale"]] + f["notes"]).strip()
            quote = f"\"{_cell(f['evidence'])}\"" if f["evidence"] else "-"
            out.append(f"| {_cell(f['control_id'])} {_cell(f['domain'])}{tags}<br>weight {f['weight']} "
                       f"| {_cell(f['requirement'])} | {quote} | {_cell(assessment)} |")
        return out + [""]

    lines += ["## Findings", ""]
    keyword_only = record["method"]["evaluator"] == "rules"
    passed_title = "Passed the keyword screen - confirm each one" if keyword_only else "Passed"
    lines += table("Failed", failed) + table("Needs review", review) + table(passed_title, passed)

    lines += [
        "## How this report was produced",
        "",
        _method_sentence(record),
        "",
        "**How the score works:** each required control has a weight. The score is the share of that weight "
        "backed by evidence in the vendor's document. A control that needs review earns nothing until a person "
        "resolves it. If a control marked critical fails, the score is set to 0.",
        "",
        "**Audit trail**",
        "",
        f"- Tool: {record['tool']['name']} {record['tool']['version']}",
        f"- Vendor file: `{_cell(record['vendor']['file'])}` (SHA-256 `{record['vendor']['sha256']}`)",
        f"- Policy file: `{_cell(record['policy']['file'])}` (SHA-256 `{record['policy']['sha256']}`)",
        "",
        f"*{DISCLAIMER}*",
        "",
    ]
    return "\n".join(lines)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "vendor"


def write_reports(record: dict, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = record["generated_at"].replace("-", "").replace(":", "").replace("T", "-").rstrip("Z")
    base = out_dir / f"{slug(record['vendor']['name'])}_{stamp}"
    paths = {"markdown": base.with_suffix(".md"), "json": base.with_suffix(".json"), "csv": base.with_suffix(".csv")}

    paths["markdown"].write_text(to_markdown(record), encoding="utf-8")
    paths["json"].write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    with open(paths["csv"], "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(["Vendor", "Framework", "Control", "Domain", "Required", "Critical", "Weight",
                         "Status", "Evidence", "Assessment", "Recommendation"])
        for f in record["findings"]:
            writer.writerow([neutralize_formula(value) for value in (
                record["vendor"]["name"], f["framework"], f["control_id"], f["domain"],
                "Yes" if f["required"] else "No", "Yes" if f["critical"] else "No", f["weight"],
                STATUS_TEXT[f["status"]], f["evidence"], " ".join([f["rationale"]] + f["notes"]).strip(),
                f["recommendation"],
            )])
    return paths

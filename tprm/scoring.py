"""Turns checked findings into a score and a rating.

Score = starting_score x (weight of required controls that PASS) / (weight of
all required controls). Controls marked `required: false` are reported but
not scored. A control that needs review earns nothing until a person
resolves it, so the score never assumes the best.
"""
from __future__ import annotations

from dataclasses import dataclass

from tprm.evaluate import FAIL, NEEDS_REVIEW, PASS, Finding
from tprm.policy import Policy

INCOMPLETE_LABEL = "⏳ INCOMPLETE (Evidence Missing - Manual Review)"
KEYWORD_ONLY_LABEL = "🔎 KEYWORD SCREEN PASSED (Confirm Before Approving)"


@dataclass
class Score:
    score: int
    best_case_score: int
    max_score: int
    rating: str
    critical_failures: list[str]
    passed: int
    failed: int
    needs_review: int
    summary: str


def _scaled(earned: int, total: int, scale: int) -> int:
    return round(scale * earned / total) if total else 0


def score_findings(findings: list[Finding], policy: Policy, keyword_screen_only: bool = False) -> Score:
    scoring = policy.scoring
    scored = [f for f in findings if f.required]
    total = sum(f.weight for f in scored)
    earned = sum(f.weight for f in scored if f.status == PASS)
    possible = earned + sum(f.weight for f in scored if f.status == NEEDS_REVIEW)

    score = _scaled(earned, total, scoring.starting_score)
    best_case = _scaled(possible, total, scoring.starting_score)

    critical_failures = [f.control_id for f in findings if f.critical and f.status == FAIL]
    if critical_failures and scoring.critical_override:
        score = best_case = 0

    passed = sum(1 for f in findings if f.status == PASS)
    failed = sum(1 for f in findings if f.status == FAIL)
    needs_review = sum(1 for f in findings if f.status == NEEDS_REVIEW)
    unresolved_required = sum(1 for f in scored if f.status == NEEDS_REVIEW)

    thresholds = scoring.thresholds
    if failed == 0 and unresolved_required > 0:
        # Nothing has failed, but there is not enough evidence to rate the vendor.
        rating = INCOMPLETE_LABEL
    elif score >= thresholds.low_risk.min and keyword_screen_only:
        # Keyword matches alone never earn the best rating: a match on "MFA"
        # cannot tell whether MFA covers everyone.
        rating = KEYWORD_ONLY_LABEL
    elif score >= thresholds.low_risk.min:
        rating = thresholds.low_risk.label
    elif score >= thresholds.medium_risk.min:
        rating = thresholds.medium_risk.label
    else:
        rating = thresholds.high_risk.label

    if critical_failures and scoring.critical_override:
        summary = (f"A critical control failed ({', '.join(critical_failures)}), "
                   "so the score is set to 0 regardless of other results.")
    elif failed == 0 and unresolved_required == 0:
        summary = "Every required control is supported by evidence in the vendor's document."
    elif failed == 0:
        summary = (f"No control failed, but {unresolved_required} required control(s) have no clear evidence. "
                   f"If all of them are confirmed, the score would be {best_case}.")
    else:
        summary = f"{failed} control(s) failed and {needs_review} need a person to review."
        if needs_review:
            summary += f" If every item under review is confirmed, the score would be {best_case}."

    return Score(
        score=score, best_case_score=best_case, max_score=scoring.starting_score, rating=rating,
        critical_failures=critical_failures, passed=passed, failed=failed, needs_review=needs_review,
        summary=summary,
    )

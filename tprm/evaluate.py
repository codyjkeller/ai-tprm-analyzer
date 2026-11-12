"""Verdict types and the guardrails applied to every verdict, whoever produced it.

The guardrails are the safety net. An evaluator (keyword rules or an AI model)
proposes a verdict; the code below decides whether that verdict is allowed to
stand. No verdict counts as PASS or FAIL unless it quotes text that is really
in the vendor's document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from tprm.policy import Control, Policy
from tprm.vendor import VendorSubmission, normalize

PASS = "PASS"  # noqa: S105 (a status name, not a password)
FAIL = "FAIL"
NEEDS_REVIEW = "NEEDS_REVIEW"
STATUSES = (PASS, FAIL, NEEDS_REVIEW)

MAX_EVIDENCE_CHARS = 400


@dataclass
class RawVerdict:
    """What an evaluator proposes for one control, before guardrails."""

    control_key: str
    status: str
    evidence: str = ""
    rationale: str = ""
    recommendation: str = ""


@dataclass
class Finding:
    """The final, checked result for one control."""

    control_key: str
    control_id: str
    framework: str
    domain: str
    requirement: str
    weight: int
    required: bool
    critical: bool
    status: str
    evidence: str
    rationale: str
    recommendation: str
    notes: list[str] = field(default_factory=list)


def term_pattern(term: str) -> re.Pattern:
    """Matches a term as a whole word: 'DES' must not match 'describes'."""
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", flags=re.IGNORECASE)


def find_term(terms: list[str], text: str) -> Optional[str]:
    return next((term for term in terms if term_pattern(term).search(text)), None)


def evidence_is_in_document(evidence: str, submission: VendorSubmission) -> bool:
    quote = normalize(evidence).strip("\"'“”‘’ .…")
    return bool(quote) and quote in submission.normalized


def default_recommendation(control: Control, status: str) -> str:
    if status == PASS:
        return "None."
    expected = f" Expected: {', '.join(control.acceptable_answers)}." if control.acceptable_answers else ""
    if status == FAIL:
        return f"Require the vendor to meet {control.id} before onboarding.{expected}"
    return f"Ask the vendor for evidence of {control.id} ({control.domain}).{expected}"


def apply_guardrails(verdicts: list[RawVerdict], policy: Policy, submission: VendorSubmission) -> list[Finding]:
    """Turns proposed verdicts into findings, one per control in the policy."""
    by_key: dict[str, RawVerdict] = {}
    for verdict in verdicts:
        # Verdicts for controls that are not in the policy are dropped; the
        # first verdict for a control wins.
        if policy.control(verdict.control_key) and verdict.control_key not in by_key:
            by_key[verdict.control_key] = verdict

    findings = []
    for control in policy.controls:
        verdict = by_key.get(control.key)
        notes: list[str] = []
        if verdict is None:
            status, evidence, recommendation = NEEDS_REVIEW, "", ""
            rationale = "No verdict was returned for this control."
        else:
            status = verdict.status if verdict.status in STATUSES else NEEDS_REVIEW
            evidence = " ".join(verdict.evidence.split())[:MAX_EVIDENCE_CHARS]
            rationale = " ".join(verdict.rationale.split())
            recommendation = " ".join(verdict.recommendation.split())
            if verdict.status not in STATUSES:
                notes.append(f"Unrecognized status '{verdict.status}' was treated as needing review.")

        # Guardrail 1: PASS and FAIL must quote the vendor's own words.
        if status in (PASS, FAIL) and not evidence_is_in_document(evidence, submission):
            notes.append(f"Proposed {status} was not accepted: the quoted evidence is not in the vendor document.")
            status, evidence = NEEDS_REVIEW, ""

        # Guardrail 2: a PASS cannot stand while a forbidden term is present.
        if status == PASS:
            forbidden = find_term(control.forbidden_terms, submission.text)
            if forbidden:
                notes.append(f"Proposed PASS was not accepted: the document contains the forbidden term '{forbidden}'.")
                status = NEEDS_REVIEW

        findings.append(Finding(
            control_key=control.key,
            control_id=control.id,
            framework=control.framework,
            domain=control.domain,
            requirement=control.description,
            weight=control.weight,
            required=control.required,
            critical=control.critical,
            status=status,
            evidence=evidence,
            rationale=rationale,
            recommendation=(recommendation if recommendation and status != PASS
                            else default_recommendation(control, status)),
            notes=notes,
        ))
    return findings

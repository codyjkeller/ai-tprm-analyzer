"""Offline keyword screen. Runs with no API key and sends nothing anywhere.

For each control it looks for the policy's forbidden_terms and
acceptable_answers in the vendor's text. It cannot understand meaning, so it
is deliberately cautious: anything qualified, negated or absent is sent to a
human as NEEDS_REVIEW.
"""
from __future__ import annotations

import re
from typing import Optional

from tprm.evaluate import FAIL, NEEDS_REVIEW, PASS, RawVerdict, term_pattern
from tprm.policy import Control, Policy
from tprm.vendor import VendorSubmission

# Words that change the meaning of the sentence a keyword sits in.
QUALIFIERS = re.compile(
    r"\b(no|not|never|none|without|except|exempt|exempted|excluding|excluded|lack|lacks|lacking|unless|"
    r"partial|partially|some|planned|planning|roadmap|future|soon|pending|optional|cannot|"
    r"but|however|only|while|whereas|although|though|otherwise)\b|n't\b",
    flags=re.IGNORECASE,
)


# Labels added when the file was read: "[Page 3]", "[mfa_status]", "Answer:".
LABEL = re.compile(r"^(\[[^\]]*\]|Answer:)\s*")


def split_sentences(text: str) -> list[str]:
    """Returns the vendor's statements. Questions and labels are left out, so a
    keyword in "Do you enforce MFA?" is never mistaken for the vendor's answer."""
    sentences = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Question:"):
            continue
        line = LABEL.sub("", line)
        for part in re.split(r"(?<=[.!?;])\s+", line):
            part = part.strip()
            if part and not part.endswith("?"):
                sentences.append(part)
    return sentences


def first_sentence_with(terms: list[str], sentences: list[str], qualified: bool) -> Optional[tuple[str, str]]:
    """Returns (term, sentence) for the first sentence that mentions a term.

    qualified=False returns only plain statements; qualified=True returns only
    sentences that also contain a qualifier such as "not" or "except".
    """
    for term in terms:
        pattern = term_pattern(term)
        for sentence in sentences:
            if pattern.search(sentence) and bool(QUALIFIERS.search(sentence)) == qualified:
                return term, sentence
    return None


def evaluate_control(control: Control, sentences: list[str]) -> RawVerdict:
    hit = first_sentence_with(control.forbidden_terms, sentences, qualified=False)
    if hit:
        term, sentence = hit
        return RawVerdict(control.key, FAIL, sentence, f"The document mentions the forbidden term '{term}'.")

    hit = first_sentence_with(control.acceptable_answers, sentences, qualified=False)
    if hit:
        term, sentence = hit
        return RawVerdict(
            control.key, PASS, sentence,
            f"Keyword match on '{term}'. A keyword match does not prove the control covers everyone in scope.",
        )

    hit = (first_sentence_with(control.forbidden_terms, sentences, qualified=True)
           or first_sentence_with(control.acceptable_answers, sentences, qualified=True))
    if hit:
        term, sentence = hit
        return RawVerdict(
            control.key, NEEDS_REVIEW, sentence,
            f"'{term}' is mentioned with qualifying wording (for example \"not\" or \"except\"): \"{sentence[:200]}\"",
        )

    return RawVerdict(control.key, NEEDS_REVIEW, "", "The document does not address this control.")


def evaluate_rules(policy: Policy, submission: VendorSubmission) -> list[RawVerdict]:
    sentences = split_sentences(submission.text)
    return [evaluate_control(control, sentences) for control in policy.controls]

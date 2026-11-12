import pytest

from tprm.evaluate import FAIL, NEEDS_REVIEW, PASS, apply_guardrails
from tprm.rules import evaluate_rules, split_sentences


def statuses(policy, submission):
    findings = apply_guardrails(evaluate_rules(policy, submission), policy, submission)
    return {f.control_key.split(".")[1]: f for f in findings}


def test_clear_statements_pass_with_the_sentence_as_evidence(policy, make_submission):
    result = statuses(policy, make_submission("MFA enforced for all users. Transit uses AES-256. We run daily backups."))
    assert [result[k].status for k in ("mfa", "crypto", "backups")] == [PASS, PASS, PASS]
    assert result["mfa"].evidence == "MFA enforced for all users."
    assert "Keyword match" in result["mfa"].rationale


def test_forbidden_term_fails(policy, make_submission):
    result = statuses(policy, make_submission("We use DES encryption for legacy support."))
    assert result["crypto"].status == FAIL
    assert result["crypto"].evidence == "We use DES encryption for legacy support."


def test_forbidden_term_beats_acceptable_term(policy, make_submission):
    result = statuses(policy, make_submission("New systems use AES-256. Old systems use DES."))
    assert result["crypto"].status == FAIL


@pytest.mark.parametrize("text", [
    "The system is described in our design documents.",   # DES inside other words
    "Our DESIGN uses modern ciphers.",
    "See the des_config file.",
])
def test_forbidden_term_must_be_a_whole_word(policy, make_submission, text):
    assert statuses(policy, make_submission(text))["crypto"].status == NEEDS_REVIEW


@pytest.mark.parametrize("text", [
    "MFA enforced is not something we do today.",
    "MFA enforced for employees except contractors.",
    "MFA enforced is planned for next year.",
    "MFA enforced for staff, but vendors use passwords.",
    "We don't have MFA enforced.",
])
def test_qualified_statements_go_to_review_not_pass(policy, make_submission, text):
    result = statuses(policy, make_submission(text))["mfa"]
    assert result.status == NEEDS_REVIEW
    assert "qualifying wording" in result.rationale


def test_negated_forbidden_term_goes_to_review_not_fail(policy, make_submission):
    assert statuses(policy, make_submission("We do not use DES anywhere."))["crypto"].status == NEEDS_REVIEW


def test_silence_goes_to_review(policy, make_submission):
    result = statuses(policy, make_submission("We value security."))
    assert {f.status for f in result.values()} == {NEEDS_REVIEW}
    assert "does not address" in result["backups"].rationale


def test_keyword_in_a_question_is_not_an_answer(policy, tmp_path):
    from tprm.vendor import load_vendor

    path = tmp_path / "q.csv"
    path.write_text("Question,Answer\nIs MFA enforced?,No.\nDo you run daily backups?,Sometimes.\n", encoding="utf-8")
    result = statuses(policy, load_vendor(path))
    assert result["mfa"].status == NEEDS_REVIEW
    assert result["backups"].status == NEEDS_REVIEW


def test_keyword_in_a_json_field_name_is_not_an_answer(repo_root):
    from tprm.policy import load_policy
    from tprm.vendor import load_vendor

    policy = load_policy(repo_root / "policies" / "vendor_standards.yaml")
    submission = load_vendor(repo_root / "examples" / "vendor_response.json")
    findings = apply_guardrails(evaluate_rules(policy, submission), policy, submission)
    assert PASS not in {f.status for f in findings}


def test_split_sentences_drops_labels_and_questions():
    text = "[Page 1]\n[mfa_status] MFA enforced. Is that enough?\nQuestion: Encrypted?\nAnswer: Yes; AES-256."
    assert split_sentences(text) == ["MFA enforced.", "Yes;", "AES-256."]

from tprm.evaluate import FAIL, NEEDS_REVIEW, PASS, RawVerdict, apply_guardrails
from tprm.scoring import INCOMPLETE_LABEL, KEYWORD_ONLY_LABEL, score_findings

GOOD_TEXT = "MFA enforced for all users. Transit uses AES-256. We run daily backups."


def verdicts(mfa=PASS, crypto=PASS, backups=PASS):
    quotes = {"mfa": "MFA enforced for all users.", "crypto": "Transit uses AES-256.", "backups": "We run daily backups."}
    chosen = {"mfa": mfa, "crypto": crypto, "backups": backups}
    return [RawVerdict(f"alpha.{k}", s, quotes[k] if s != NEEDS_REVIEW else "", "because") for k, s in chosen.items()]


def run(policy, submission, raw, **kwargs):
    findings = apply_guardrails(raw, policy, submission)
    return {f.control_key.split(".")[1]: f for f in findings}, score_findings(findings, policy, **kwargs)


# --- guardrails ---

def test_one_finding_per_policy_control_in_policy_order(policy, make_submission):
    findings, _ = run(policy, make_submission(GOOD_TEXT), verdicts())
    assert list(findings) == ["mfa", "crypto", "backups", "intel"]
    assert findings["intel"].status == NEEDS_REVIEW          # no verdict returned
    assert "No verdict" in findings["intel"].rationale


def test_pass_with_invented_quote_is_not_accepted(policy, make_submission):
    raw = [RawVerdict("alpha.mfa", PASS, "MFA is enforced for every account worldwide.", "looks fine")]
    findings, _ = run(policy, make_submission(GOOD_TEXT), raw)
    assert findings["mfa"].status == NEEDS_REVIEW
    assert findings["mfa"].evidence == ""
    assert "not in the vendor document" in findings["mfa"].notes[0]


def test_pass_and_fail_without_a_quote_are_not_accepted(policy, make_submission):
    raw = [RawVerdict("alpha.mfa", PASS, "", "trust me"), RawVerdict("alpha.crypto", FAIL, "  ", "trust me")]
    findings, _ = run(policy, make_submission(GOOD_TEXT), raw)
    assert findings["mfa"].status == NEEDS_REVIEW
    assert findings["crypto"].status == NEEDS_REVIEW


def test_quote_matching_ignores_case_whitespace_and_outer_quotes(policy, make_submission):
    raw = [RawVerdict("alpha.mfa", PASS, '"mfa   ENFORCED for\nall users."', "ok")]
    findings, _ = run(policy, make_submission(GOOD_TEXT), raw)
    assert findings["mfa"].status == PASS


def test_pass_is_blocked_when_a_forbidden_term_is_present(policy, make_submission):
    submission = make_submission("Transit uses AES-256. Legacy links use DES.")
    raw = [RawVerdict("alpha.crypto", PASS, "Transit uses AES-256.", "ok")]
    findings, _ = run(policy, submission, raw)
    assert findings["crypto"].status == NEEDS_REVIEW
    assert "forbidden term 'DES'" in findings["crypto"].notes[0]


def test_unknown_controls_duplicates_and_bad_statuses(policy, make_submission):
    raw = [
        RawVerdict("alpha.made_up", PASS, "MFA enforced for all users.", "x"),
        RawVerdict("alpha.mfa", FAIL, "MFA enforced for all users.", "first"),
        RawVerdict("alpha.mfa", PASS, "MFA enforced for all users.", "second"),
        RawVerdict("alpha.crypto", "APPROVED", "Transit uses AES-256.", "x"),
    ]
    findings, _ = run(policy, make_submission(GOOD_TEXT), raw)
    assert "made_up" not in findings
    assert findings["mfa"].status == FAIL and findings["mfa"].rationale == "first"
    assert findings["crypto"].status == NEEDS_REVIEW
    assert "Unrecognized status 'APPROVED'" in findings["crypto"].notes[0]


def test_recommendations_are_filled_in(policy, make_submission):
    findings, _ = run(policy, make_submission(GOOD_TEXT), verdicts(crypto=FAIL, backups=NEEDS_REVIEW))
    assert findings["mfa"].recommendation == "None."
    assert findings["crypto"].recommendation.startswith("Require the vendor to meet A-2")
    assert findings["backups"].recommendation.startswith("Ask the vendor for evidence of A-3")


# --- scoring ---

def test_all_pass(policy, make_submission):
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts())
    assert (score.score, score.best_case_score, score.rating) == (100, 100, "LOW")
    assert (score.passed, score.failed, score.needs_review) == (3, 0, 1)   # optional control is unresolved


def test_optional_control_is_not_scored(policy, make_submission):
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts())
    assert score.score == 100


def test_failure_deducts_its_weight(policy, make_submission):
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts(backups=FAIL))
    assert (score.score, score.rating) == (80, "MEDIUM")


def test_heavier_failure_is_high_risk(policy, make_submission):
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts(crypto=FAIL))
    assert (score.score, score.rating) == (60, "HIGH")


def test_critical_failure_sets_score_to_zero(policy, make_submission):
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts(mfa=FAIL))
    assert (score.score, score.best_case_score, score.rating) == (0, 0, "HIGH")
    assert score.critical_failures == ["A-1"]
    assert "critical control failed" in score.summary


def test_critical_override_can_be_switched_off(write_policy, make_submission):
    from tests.conftest import POLICY_YAML
    from tprm.policy import load_policy

    policy = load_policy(write_policy(POLICY_YAML.replace("critical_override: true", "critical_override: false")))
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts(mfa=FAIL))
    assert score.score == 60


def test_missing_evidence_is_incomplete_not_a_rejection(policy, make_submission):
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts(crypto=NEEDS_REVIEW))
    assert (score.score, score.best_case_score, score.rating) == (60, 100, INCOMPLETE_LABEL)
    assert "would be 100" in score.summary


def test_failure_plus_open_items_reports_best_case(policy, make_submission):
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts(crypto=NEEDS_REVIEW, backups=FAIL))
    assert (score.score, score.best_case_score, score.rating) == (40, 80, "HIGH")


def test_keyword_screen_never_earns_the_best_rating(policy, make_submission):
    _, score = run(policy, make_submission(GOOD_TEXT), verdicts(), keyword_screen_only=True)
    assert (score.score, score.rating) == (100, KEYWORD_ONLY_LABEL)

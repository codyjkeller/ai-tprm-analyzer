import pytest

from tests.conftest import POLICY_YAML
from tprm.policy import PolicyError, load_policy


def test_loads_only_active_frameworks_with_namespaced_keys(policy):
    assert [c.key for c in policy.controls] == ["alpha.mfa", "alpha.crypto", "alpha.backups", "alpha.intel"]
    assert [c.key for c in policy.scored_controls] == ["alpha.mfa", "alpha.crypto", "alpha.backups"]
    assert policy.control("alpha.mfa").critical
    assert not policy.control("alpha.crypto").critical
    assert len(policy.sha256) == 64


def test_same_control_name_in_two_frameworks_does_not_collide(write_policy):
    policy = load_policy(write_policy(POLICY_YAML.replace('  - "alpha"', '  - "alpha"\n  - "beta"')))
    assert policy.control("alpha.mfa").id == "A-1"
    assert policy.control("beta.mfa").id == "B-1"


def test_shipped_policy_is_valid(repo_root):
    policy = load_policy(repo_root / "policies" / "vendor_standards.yaml")
    assert policy.active_frameworks == ["nist_800_53_r5", "cjis_policy"]
    assert sum(c.weight for c in policy.scored_controls) == 100


def test_every_framework_in_shipped_policy_is_valid(repo_root, tmp_path):
    import yaml

    document = yaml.safe_load((repo_root / "policies" / "vendor_standards.yaml").read_text(encoding="utf-8"))
    document["active_frameworks"] = list(document["frameworks"])
    path = tmp_path / "all.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    assert len(load_policy(path).controls) == 15


@pytest.mark.parametrize("change, message", [
    (lambda t: t.replace('  - "alpha"', '  - "gamma"'), "active framework 'gamma' is not defined"),
    (lambda t: t.replace("weight: 40\n      description: \"MFA", "weigth: 40\n      description: \"MFA"), "frameworks.alpha.mfa"),
    (lambda t: t.replace("weight: 20", "weight: -5"), "frameworks.alpha.backups.weight"),
    (lambda t: t.replace("low_risk: {min: 90", "low_risk: {min: 50"), "thresholds must descend"),
    (lambda t: t.replace('active_frameworks:\n  - "alpha"', "active_frameworks: []"), "at least one framework"),
    (lambda t: t + "\nextra_section: {}\n", "unknown top-level keys: extra_section"),
    (lambda t: "just a string", "mapping at the top level"),
    (lambda t: "a: [unclosed", "not valid YAML"),
])
def test_invalid_policy_is_rejected_with_a_clear_message(write_policy, change, message):
    with pytest.raises(PolicyError) as error:
        load_policy(write_policy(change(POLICY_YAML)))
    assert message in str(error.value)


def test_missing_policy_file(tmp_path):
    with pytest.raises(PolicyError, match="not found"):
        load_policy(tmp_path / "nope.yaml")


def test_unsafe_yaml_tags_are_not_executed(write_policy):
    with pytest.raises(PolicyError):
        load_policy(write_policy("frameworks: !!python/object/apply:os.system ['echo unsafe']"))

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

for _key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TPRM_PROVIDER", "TPRM_MODEL", "TPRM_MAX_CHARS"):
    os.environ.pop(_key, None)

from tprm.policy import load_policy  # noqa: E402
from tprm.vendor import load_vendor  # noqa: E402

POLICY_YAML = """
scoring_matrix:
  starting_score: 100
  thresholds:
    low_risk: {min: 90, label: "LOW"}
    medium_risk: {min: 70, label: "MEDIUM"}
    high_risk: {min: 0, label: "HIGH"}
  critical_override: true
active_frameworks:
  - "alpha"
frameworks:
  alpha:
    mfa:
      id: "A-1"
      domain: "Authentication"
      weight: 40
      description: "MFA for all accounts."
      acceptable_answers: ["MFA enforced"]
      critical_flag: "MFA not enforced"
    crypto:
      id: "A-2"
      domain: "Encryption"
      weight: 40
      description: "Strong encryption in transit."
      acceptable_answers: ["AES-256"]
      forbidden_terms: ["DES"]
    backups:
      id: "A-3"
      domain: "Backups"
      weight: 20
      description: "Daily backups."
      acceptable_answers: ["daily backups"]
    intel:
      id: "A-4"
      domain: "Threat Intel"
      required: false
      weight: 10
      description: "Threat feed."
      acceptable_answers: ["threat feed"]
  beta:
    mfa:
      id: "B-1"
      domain: "Other"
      weight: 10
      description: "Same control name as alpha.mfa."
"""


@pytest.fixture
def repo_root():
    return REPO_ROOT


@pytest.fixture
def write_policy(tmp_path):
    def _write(text=POLICY_YAML):
        path = tmp_path / "policy.yaml"
        path.write_text(text, encoding="utf-8")
        return path
    return _write


@pytest.fixture
def policy(write_policy):
    return load_policy(write_policy())


@pytest.fixture
def make_submission(tmp_path):
    def _make(text, filename="vendor.txt"):
        path = tmp_path / filename
        path.write_text(text, encoding="utf-8")
        return load_vendor(path)
    return _make

import json

import httpx
import pytest

from tprm import cli, connectors
from tprm.connectors import ConnectorError
from tprm.evaluate import FAIL, PASS, RawVerdict, apply_guardrails
from tprm.report import build_record
from tprm.scoring import score_findings


@pytest.fixture
def record(policy, make_submission):
    submission = make_submission("MFA enforced for all users. We use DES.")
    findings = apply_guardrails([
        RawVerdict("alpha.mfa", PASS, "MFA enforced for all users.", "ok"),
        RawVerdict("alpha.crypto", FAIL, "We use DES.", "Weak cipher.", "Move to AES-256."),
    ], policy, submission)
    return build_record(policy, submission, findings, score_findings(findings, policy), "rules", None)


class Recorder:
    """A stand-in for the remote system. Records every request it receives."""

    def __init__(self, responder):
        self.requests = []
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))
        self._responder = responder

    def _handle(self, request):
        self.requests.append(request)
        return self._responder(request)


@pytest.fixture
def atlassian(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_BASE_URL", "https://example.atlassian.net/")
    monkeypatch.setenv("ATLASSIAN_EMAIL", "analyst@example.com")
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "secret-token")
    monkeypatch.setenv("JIRA_PROJECT_KEY", "TPRM")


# --- Slack ---

def test_slack_summary_names_controls_but_not_vendor_quotes(record):
    text = connectors.slack_message(record)
    assert "*Vendor risk assessment: Vendor*" in text
    assert "*Failed:* A-2 Encryption" in text
    assert "*Needs review:* A-3 Backups, A-4 Threat Intel" in text
    assert "We use DES." not in text
    assert "Decision support only" in text


def test_slack_text_cannot_inject_mentions_or_links(record):
    record["vendor"]["name"] = "<!channel> <https://evil.example|click> & co"
    text = connectors.slack_message(record)
    assert "<!channel>" not in text and "<https://" not in text
    assert "&lt;!channel&gt;" in text and "&amp; co" in text


def test_post_to_slack(record, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/services/T/B/secret")
    slack = Recorder(lambda request: httpx.Response(200, text="ok"))
    connectors.post_to_slack(record, client=slack.client)
    request = slack.requests[0]
    assert str(request.url) == "https://hooks.slack.example/services/T/B/secret"
    assert json.loads(request.content)["text"].startswith("*Vendor risk assessment")


def test_slack_errors_do_not_reveal_the_webhook_address(record, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/services/T/B/secret")
    refused = Recorder(lambda request: httpx.Response(403, text="invalid_token"))
    with pytest.raises(ConnectorError) as error:
        connectors.post_to_slack(record, client=refused.client)
    assert "status 403" in str(error.value) and "secret" not in str(error.value)

    def unreachable(request):
        raise httpx.ConnectError("cannot connect to https://hooks.slack.example/services/T/B/secret")

    with pytest.raises(ConnectorError) as error:
        connectors.post_to_slack(record, client=Recorder(unreachable).client)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("value, message", [
    ("", "SLACK_WEBHOOK_URL is not set"),
    ("http://hooks.slack.example/x", "must start with https://"),
    ("https://", "not a valid address"),
])
def test_slack_address_is_required_and_must_be_https(record, monkeypatch, value, message):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", value)
    with pytest.raises(ConnectorError, match=message):
        connectors.post_to_slack(record, client=Recorder(lambda r: httpx.Response(200)).client)


# --- Jira ---

def test_create_jira_issue_and_attach_report(record, atlassian, tmp_path):
    report = tmp_path / "vendor.md"
    report.write_text("# report", encoding="utf-8")

    def respond(request):
        if request.url.path == "/rest/api/3/issue":
            return httpx.Response(201, json={"id": "1", "key": "TPRM-42"})
        return httpx.Response(200, json=[{"id": "9"}])

    jira = Recorder(respond)
    url = connectors.create_jira_issue(record, report, client=jira.client)
    assert url == "https://example.atlassian.net/browse/TPRM-42"

    create, attach = jira.requests
    assert create.headers["authorization"].startswith("Basic ")
    fields = json.loads(create.content)["fields"]
    assert fields["project"] == {"key": "TPRM"} and fields["issuetype"] == {"name": "Task"}
    assert fields["summary"].startswith("Vendor risk assessment: Vendor - ")
    assert fields["labels"] == ["tprm", "vendor-risk"]
    body = json.dumps(fields["description"])
    assert fields["description"]["type"] == "doc" and "A-2 Encryption: Move to AES-256." in body
    assert "We use DES." not in body

    assert attach.url.path == "/rest/api/3/issue/TPRM-42/attachments"
    assert attach.headers["x-atlassian-token"] == "no-check"
    assert b"# report" in attach.content


def test_jira_issue_type_can_be_changed_and_report_is_optional(record, atlassian, monkeypatch):
    monkeypatch.setenv("JIRA_ISSUE_TYPE", "Risk")
    jira = Recorder(lambda request: httpx.Response(201, json={"key": "TPRM-7"}))
    connectors.create_jira_issue(record, None, client=jira.client)
    assert len(jira.requests) == 1
    assert json.loads(jira.requests[0].content)["fields"]["issuetype"] == {"name": "Risk"}


@pytest.mark.parametrize("response, message", [
    (httpx.Response(401, json={}), "status 401. Check the e-mail address and API token."),
    (httpx.Response(404, json={}), "status 404"),
    (httpx.Response(201, json={"key": "../../admin"}), "did not return an issue key"),
])
def test_jira_failures_are_explained(record, atlassian, response, message):
    with pytest.raises(ConnectorError, match=message):
        connectors.create_jira_issue(record, None, client=Recorder(lambda request: response).client)


def test_missing_atlassian_settings_are_named(record, monkeypatch):
    for name in ("ATLASSIAN_BASE_URL", "ATLASSIAN_EMAIL", "ATLASSIAN_API_TOKEN", "JIRA_PROJECT_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConnectorError, match="ATLASSIAN_BASE_URL is not set"):
        connectors.create_jira_issue(record)


# --- Confluence ---

PAGE = ("<h1>Security</h1><p>MFA enforced for all users.</p><script>alert(1)</script>"
        "<table><tr><th>Topic</th><th>Answer</th></tr><tr><td>Transit</td><td>AES-256 &amp; TLS</td></tr></table>"
        "<ul><li>Daily backups</li></ul>")


def test_read_confluence_page(atlassian):
    wiki = Recorder(lambda request: httpx.Response(200, json={"title": "Acme Answers", "body": {"storage": {"value": PAGE}}}))
    title, text = connectors.read_confluence_page("https://example.atlassian.net/wiki/spaces/SEC/pages/12345/Acme", client=wiki.client)
    request = wiki.requests[0]
    assert request.url.path == "/wiki/api/v2/pages/12345" and request.url.params["body-format"] == "storage"
    assert title == "Acme Answers"
    assert text.splitlines() == ["Security", "MFA enforced for all users.", "Topic | Answer", "Transit | AES-256 & TLS", "Daily backups"]


def test_page_address_on_another_site_never_receives_credentials(atlassian):
    wiki = Recorder(lambda request: httpx.Response(200, json={"title": "t", "body": {"storage": {"value": "<p>x</p>"}}}))
    connectors.read_confluence_page("https://attacker.example/wiki/pages/999/x", client=wiki.client)
    assert wiki.requests[0].url.host == "example.atlassian.net"


@pytest.mark.parametrize("reference, expected", [
    ("12345", "12345"),
    (" https://x.atlassian.net/wiki/spaces/S/pages/678/Title ", "678"),
    ("https://x.atlassian.net/wiki/pages/viewpage.action?pageId=91011", "91011"),
])
def test_confluence_page_id(reference, expected):
    assert connectors.confluence_page_id(reference) == expected


def test_confluence_page_id_rejects_other_text():
    with pytest.raises(ConnectorError, match="page ID"):
        connectors.confluence_page_id("../../rest/api/3/myself")


# --- command line ---

def test_cli_reads_confluence_and_notifies(repo_root, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(repo_root)
    calls = {}
    monkeypatch.setattr(cli, "read_confluence_page", lambda ref: ("Acme Answers", "We use DES for transit."))
    monkeypatch.setattr(cli, "post_to_slack", lambda record: calls.setdefault("slack", record["vendor"]["name"]) and None)
    monkeypatch.setattr(cli, "create_jira_issue", lambda record, report: calls.setdefault("jira", report) and "https://x/browse/TPRM-1")
    code = cli.main(["analyze", "confluence:12345", "--slack", "--jira", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Vendor: Acme Answers" in out
    assert "Slack: summary posted" in out and "Jira: https://x/browse/TPRM-1" in out
    assert calls["slack"] == "Acme Answers" and calls["jira"].suffix == ".md"
    record = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert record["vendor"]["file"] == "Confluence page: Acme Answers"


def test_failed_notification_keeps_the_report_and_exits_3(repo_root, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(repo_root)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    code = cli.main(["analyze", "examples/weak_vendor.txt", "--slack", "--out", str(tmp_path)])
    assert code == 3
    assert "SLACK_WEBHOOK_URL is not set" in capsys.readouterr().err
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_nothing_is_sent_without_the_flags(repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)

    def fail(*args, **kwargs):
        raise AssertionError("a connector was called without its flag")

    for name in ("post_to_slack", "create_jira_issue", "read_confluence_page"):
        monkeypatch.setattr(cli, name, fail)
    assert cli.main(["analyze", "examples/weak_vendor.txt", "--no-files"]) == 0

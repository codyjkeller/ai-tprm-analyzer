"""Optional connections to Slack, Jira and Confluence (Atlassian Cloud).

Nothing here runs unless you ask for it on the command line. Credentials come
from environment variables (your .env file) and are never printed. Every
address must be HTTPS, requests time out, and redirects are not followed, so
a credential is only ever sent to the address you configured.
"""
from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from tprm.evaluate import FAIL, NEEDS_REVIEW

TIMEOUT_SECONDS = 20
MAX_LISTED_ITEMS = 10
LOCAL_HOSTS = ("127.0.0.1", "localhost")


class ConnectorError(Exception):
    """A connection is not configured, or the other system refused the request."""


def _setting(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, "").strip() or (default or "")
    if not value:
        raise ConnectorError(f"{name} is not set. Add it to your .env file (see .env.example).")
    return value


def _https(url: str, name: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" and parsed.hostname not in LOCAL_HOSTS:
        raise ConnectorError(f"{name} must start with https://")
    if not parsed.hostname:
        raise ConnectorError(f"{name} is not a valid address.")
    return url.rstrip("/")


def _client(client: Optional[httpx.Client]) -> httpx.Client:
    return client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)


def _check(response: httpx.Response, system: str) -> None:
    if response.status_code >= 300:
        hint = {401: " Check the e-mail address and API token.", 403: " The account lacks permission.",
                404: " Check the address, project key or page ID."}.get(response.status_code, "")
        raise ConnectorError(f"{system} answered with status {response.status_code}.{hint}")


def _send(system: str, call):
    try:
        return call()
    except httpx.HTTPError as error:
        # The error text can include the address, and a Slack webhook address is a secret.
        raise ConnectorError(f"Could not reach {system}: {type(error).__name__}.") from error


def _open_items(record: dict) -> tuple[list[dict], list[dict]]:
    findings = record["findings"]
    return ([f for f in findings if f["status"] == FAIL], [f for f in findings if f["status"] == NEEDS_REVIEW])


# --- Slack ---

def slack_escape(text: str) -> str:
    """Stops vendor-supplied text from creating links or @channel mentions."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_message(record: dict) -> str:
    """A short summary. It names controls but does not quote the vendor's document."""
    result = record["result"]
    failed, review = _open_items(record)
    lines = [
        f"*Vendor risk assessment: {slack_escape(record['vendor']['name'])}*",
        f"{slack_escape(result['rating'])} | Score {result['score']} of {result['max_score']} "
        f"| {result['passed']} passed, {result['failed']} failed, {result['needs_review']} need review",
        slack_escape(result["summary"]),
    ]
    for title, items in (("Failed", failed), ("Needs review", review)):
        if items:
            names = ", ".join(slack_escape(f"{f['control_id']} {f['domain']}") for f in items[:MAX_LISTED_ITEMS])
            more = f" and {len(items) - MAX_LISTED_ITEMS} more" if len(items) > MAX_LISTED_ITEMS else ""
            lines.append(f"*{title}:* {names}{more}")
    if record["warnings"]:
        lines.append(":warning: The document contains wording that looks like instructions to an AI reviewer.")
    lines.append("_Decision support only. A qualified person must review the full report._")
    return "\n".join(lines)


def post_to_slack(record: dict, client: Optional[httpx.Client] = None) -> None:
    url = _https(_setting("SLACK_WEBHOOK_URL"), "SLACK_WEBHOOK_URL")
    response = _send("Slack", lambda: _client(client).post(url, json={"text": slack_message(record)}))
    _check(response, "Slack")


# --- Atlassian (Jira and Confluence Cloud) ---

def _atlassian() -> tuple[str, tuple[str, str]]:
    base = _https(_setting("ATLASSIAN_BASE_URL"), "ATLASSIAN_BASE_URL")
    return base, (_setting("ATLASSIAN_EMAIL"), _setting("ATLASSIAN_API_TOKEN"))


def _paragraph(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _bullets(items: list[str]) -> dict:
    return {"type": "bulletList", "content": [{"type": "listItem", "content": [_paragraph(item)]} for item in items]}


def jira_issue_fields(record: dict, project_key: str, issue_type: str) -> dict:
    result = record["result"]
    failed, review = _open_items(record)
    content = [
        _paragraph(f"Rating: {result['rating']}"),
        _paragraph(f"Score: {result['score']} of {result['max_score']} "
                   f"(if every open item is confirmed: {result['best_case_score']})"),
        _paragraph(result["summary"]),
    ]
    for title, items in (("Failed", failed), ("Needs review", review)):
        if items:
            content.append(_paragraph(f"{title}:"))
            content.append(_bullets([f"{f['control_id']} {f['domain']}: {f['recommendation']}" for f in items]))
    for warning in record["warnings"]:
        content.append(_paragraph(f"Warning: {warning}"))
    content.append(_paragraph(f"Assessed {record['generated_at']} (UTC) with {record['tool']['name']} "
                              f"{record['tool']['version']}. {record['disclaimer']}"))
    return {
        "project": {"key": project_key},
        "issuetype": {"name": issue_type},
        "summary": f"Vendor risk assessment: {record['vendor']['name']} - {result['rating']}"[:250],
        "labels": ["tprm", "vendor-risk"],
        "description": {"type": "doc", "version": 1, "content": content},
    }


def create_jira_issue(record: dict, report: Optional[Path] = None, client: Optional[httpx.Client] = None) -> str:
    """Creates one Jira issue for the assessment, attaches the report, returns the issue address."""
    base, auth = _atlassian()
    fields = jira_issue_fields(record, _setting("JIRA_PROJECT_KEY"), _setting("JIRA_ISSUE_TYPE", "Task"))
    http = _client(client)

    response = _send("Jira", lambda: http.post(f"{base}/rest/api/3/issue", json={"fields": fields}, auth=auth))
    _check(response, "Jira")
    key = str(response.json().get("key", ""))
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", key):
        raise ConnectorError("Jira did not return an issue key.")

    if report and report.is_file():
        response = _send("Jira", lambda: http.post(
            f"{base}/rest/api/3/issue/{key}/attachments", auth=auth,
            headers={"X-Atlassian-Token": "no-check"},
            files={"file": (report.name, report.read_bytes(), "text/markdown")},
        ))
        _check(response, "Jira (attachment)")
    return f"{base}/browse/{key}"


class _TextExtractor(HTMLParser):
    """Turns Confluence page markup into plain text."""

    BLOCKS = {"p", "br", "li", "tr", "div", "h1", "h2", "h3", "h4", "h5", "h6", "table"}
    SKIPPED = {"script", "style"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIPPED:
            self._skipping += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIPPED and self._skipping:
            self._skipping -= 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skipping:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip(" |") for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def confluence_page_id(reference: str) -> str:
    """Accepts a page ID, or a page address copied from the browser."""
    reference = reference.strip()
    if reference.isdigit():
        return reference
    match = re.search(r"/pages/(\d+)", reference) or re.search(r"[?&]pageId=(\d+)", reference)
    if not match:
        raise ConnectorError("Give the Confluence page ID (a number) or the page's address from your browser.")
    return match.group(1)


def read_confluence_page(reference: str, client: Optional[httpx.Client] = None) -> tuple[str, str]:
    """Returns (title, text) of a Confluence page. Only the configured site is ever contacted."""
    base, auth = _atlassian()
    page_id = confluence_page_id(reference)
    response = _send("Confluence", lambda: _client(client).get(
        f"{base}/wiki/api/v2/pages/{page_id}", params={"body-format": "storage"}, auth=auth))
    _check(response, "Confluence")
    page = response.json()
    markup = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
    return str(page.get("title") or f"Confluence page {page_id}"), html_to_text(markup)

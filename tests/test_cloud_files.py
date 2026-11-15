"""Tests for reading vendor documents from Google Drive, SharePoint and OneDrive.

No real service is contacted: a stand-in records every request and replies.
"""
import base64
import json

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from tprm import cli, cloud_files
from tprm.connectors import ConnectorError

FILE_ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"
PDF_TEXT = b"Vendor: Acme Cloud Inc.\nMFA is enforced for all users.\n"


class Recorder:
    def __init__(self, responder):
        self.requests = []
        self.client = httpx.Client(transport=httpx.MockTransport(self._handle))
        self._responder = responder

    def _handle(self, request):
        self.requests.append(request)
        return self._responder(request)

    @property
    def urls(self):
        return [str(request.url) for request in self.requests]


def decode_part(part):
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


# --- Google Drive ---

@pytest.fixture(scope="module")
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def google(tmp_path, monkeypatch, private_key):
    pem = private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
    key_file = tmp_path / "service-account.json"
    # token_uri is deliberately wrong: the tool must ignore it and sign in at Google's own address.
    key_file.write_text(json.dumps({"client_email": "tprm@example.iam.gserviceaccount.com", "private_key": pem,
                                    "token_uri": "https://attacker.example/token"}))
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(key_file))


def google_drive(info, content=PDF_TEXT, status=200):
    def respond(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "google-token"})
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "secret detail"}})
        if request.url.path.endswith("/export") or request.url.params.get("alt") == "media":
            return httpx.Response(200, content=content)
        return httpx.Response(200, json=info)
    return Recorder(respond)


@pytest.mark.parametrize("reference", [
    FILE_ID,
    f"https://drive.google.com/file/d/{FILE_ID}/view?usp=sharing",
    f"https://docs.google.com/document/d/{FILE_ID}/edit",
    f"https://drive.google.com/open?id={FILE_ID}",
])
def test_google_file_id(reference):
    assert cloud_files.google_file_id(reference) == FILE_ID


@pytest.mark.parametrize("reference", ["", "abc", "https://drive.google.com/drive/my-drive", "../../etc/passwd"])
def test_google_file_id_rejects_other_text(reference):
    with pytest.raises(ConnectorError):
        cloud_files.google_file_id(reference)


def test_google_download(google, private_key):
    drive = google_drive({"id": FILE_ID, "name": "Acme answers.txt", "mimeType": "text/plain", "size": "54"})
    name, content = cloud_files.fetch_google_drive_file(FILE_ID, client=drive.client)
    assert (name, content) == ("Acme answers.txt", PDF_TEXT)

    sign_in, metadata, download = drive.requests
    assert str(sign_in.url) == "https://oauth2.googleapis.com/token"
    form = dict(pair.split("=", 1) for pair in sign_in.content.decode().split("&"))
    header, claims, signature = form["assertion"].split(".")
    assert decode_part(header) == {"alg": "RS256", "typ": "JWT"}
    claims = decode_part(claims)
    assert claims["iss"] == "tprm@example.iam.gserviceaccount.com"
    assert claims["scope"] == "https://www.googleapis.com/auth/drive.readonly"
    assert claims["aud"] == "https://oauth2.googleapis.com/token"
    assert claims["exp"] - claims["iat"] == 600
    private_key.public_key().verify(
        base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
        f"{header}.{form['assertion'].split('.')[1]}".encode(), padding.PKCS1v15(), hashes.SHA256())

    assert metadata.headers["authorization"] == "Bearer google-token"
    assert download.url.params["alt"] == "media"
    assert all(request.url.host in ("oauth2.googleapis.com", "www.googleapis.com") for request in drive.requests)
    assert all(request.method == "GET" for request in drive.requests[1:])


def test_google_doc_is_exported_as_text(google):
    drive = google_drive({"id": FILE_ID, "name": "Acme answers", "mimeType": "application/vnd.google-apps.document"})
    name, _ = cloud_files.fetch_google_drive_file(FILE_ID, client=drive.client)
    assert name == "Acme answers.txt"
    assert drive.requests[-1].url.path.endswith(f"/{FILE_ID}/export")
    assert drive.requests[-1].url.params["mimeType"] == "text/plain"


def test_google_sheet_is_exported_as_excel(google):
    drive = google_drive({"id": FILE_ID, "name": "Answers", "mimeType": "application/vnd.google-apps.spreadsheet"})
    name, _ = cloud_files.fetch_google_drive_file(FILE_ID, client=drive.client)
    assert name == "Answers.xlsx"


@pytest.mark.parametrize(("info", "message"), [
    ({"name": "deck", "mimeType": "application/vnd.google-apps.presentation"}, "cannot be read"),
    ({"name": "photo.png", "mimeType": "image/png", "size": "10"}, "not a supported file type"),
    ({"name": "big.pdf", "mimeType": "application/pdf", "size": str(26 * 1024 * 1024)}, "larger than 25 MB"),
])
def test_google_refuses_before_downloading(google, info, message):
    drive = google_drive(info)
    with pytest.raises(ConnectorError, match=message):
        cloud_files.fetch_google_drive_file(FILE_ID, client=drive.client)
    assert len(drive.requests) == 2  # sign-in and file details only


def test_google_not_shared_gives_a_useful_message_without_the_reply_body(google):
    drive = google_drive({}, status=404)
    with pytest.raises(ConnectorError) as error:
        cloud_files.fetch_google_drive_file(FILE_ID, client=drive.client)
    assert "Share the file with the service account" in str(error.value)
    assert "secret detail" not in str(error.value)


def test_google_needs_a_key_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    with pytest.raises(ConnectorError, match="GOOGLE_SERVICE_ACCOUNT_FILE is not set"):
        cloud_files.fetch_google_drive_file(FILE_ID)
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(bad))
    with pytest.raises(ConnectorError, match="service account key file"):
        cloud_files.fetch_google_drive_file(FILE_ID)
    bad.write_text(json.dumps({"client_email": "a@b", "private_key": "not a key"}))
    with pytest.raises(ConnectorError, match="could not be used"):
        cloud_files.fetch_google_drive_file(FILE_ID)


def test_google_sign_in_failure(google):
    drive = Recorder(lambda request: httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(ConnectorError, match="Google sign-in failed with status 400"):
        cloud_files.fetch_google_drive_file(FILE_ID, client=drive.client)


# --- SharePoint and OneDrive ---

SITE_FILE = "https://contoso.sharepoint.com/sites/Vendors/Shared%20Documents/Acme/answers.txt"
SHARE_LINK = "https://contoso.sharepoint.com/:t:/s/Vendors/EaBcDeFgHiJkLmNoPqRsTuVw?e=abc123"


@pytest.fixture
def microsoft(monkeypatch):
    monkeypatch.setenv("MS_TENANT_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setenv("MS_CLIENT_ID", "client-id")
    monkeypatch.setenv("MS_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("MS_CLOUD", raising=False)


def microsoft_365(item=None, graph_host="graph.microsoft.com", redirect=True, library="Shared%20Documents"):
    item = item or {"id": "item-1", "name": "answers.txt", "size": 54, "file": {},
                    "parentReference": {"driveId": "drive-1"}}

    def respond(request):
        host, path = request.url.host, request.url.path
        if host.startswith("login."):
            return httpx.Response(200, json={"access_token": "ms-token"})
        if host == "download.example":
            return httpx.Response(200, content=PDF_TEXT)
        assert host == graph_host
        if path.endswith("/content"):
            if redirect:
                return httpx.Response(302, headers={"location": "https://download.example/file?tempauth=abc"})
            return httpx.Response(200, content=PDF_TEXT)
        if path.endswith("/drives"):
            return httpx.Response(200, json={"value": [
                {"id": "drive-other", "webUrl": "https://contoso.sharepoint.com/sites/Vendors/Archive"},
                {"id": "drive-1", "webUrl": f"https://contoso.sharepoint.com/sites/Vendors/{library}"},
            ]})
        if "/root:/" in path or "/shares/" in path:
            return httpx.Response(200, json=item)
        if "/sites/" in path:
            return httpx.Response(200, json={"id": "site-1"})
        return httpx.Response(404, json={})
    return Recorder(respond)


def test_sharepoint_download_by_file_address(microsoft):
    m365 = microsoft_365()
    name, content = cloud_files.fetch_sharepoint_file(SITE_FILE, client=m365.client)
    assert (name, content) == ("answers.txt", PDF_TEXT)

    sign_in = m365.requests[0]
    assert str(sign_in.url) == ("https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555"
                                "/oauth2/v2.0/token")
    assert b"grant_type=client_credentials" in sign_in.content
    assert b"scope=https%3A%2F%2Fgraph.microsoft.com%2F.default" in sign_in.content
    assert m365.urls[1] == "https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com:/sites/Vendors"
    assert m365.urls[2].startswith("https://graph.microsoft.com/v1.0/sites/site-1/drives")
    assert m365.urls[3] == "https://graph.microsoft.com/v1.0/drives/drive-1/root:/Acme/answers.txt"
    assert m365.urls[4] == "https://graph.microsoft.com/v1.0/drives/drive-1/items/item-1/content"
    assert all(request.method == "GET" for request in m365.requests[1:])


def test_token_is_not_sent_to_the_download_address(microsoft):
    m365 = microsoft_365()
    cloud_files.fetch_sharepoint_file(SITE_FILE, client=m365.client)
    download = m365.requests[-1]
    assert download.url.host == "download.example"
    assert "authorization" not in download.headers
    assert all(request.headers["authorization"] == "Bearer ms-token" for request in m365.requests[1:-1])


def test_sharepoint_download_without_a_redirect(microsoft):
    m365 = microsoft_365(redirect=False)
    assert cloud_files.fetch_sharepoint_file(SITE_FILE, client=m365.client)[1] == PDF_TEXT


def test_download_address_must_be_https(microsoft):
    def respond(request):
        if request.url.path.endswith("/content"):
            return httpx.Response(302, headers={"location": "http://download.example/file"})
        return microsoft_365()._responder(request)
    with pytest.raises(ConnectorError, match="not HTTPS"):
        cloud_files.fetch_sharepoint_file(SITE_FILE, client=Recorder(respond).client)


def test_sharepoint_sharing_link(microsoft):
    m365 = microsoft_365()
    name, _ = cloud_files.fetch_sharepoint_file(SHARE_LINK, client=m365.client)
    assert name == "answers.txt"
    token = m365.urls[1].split("/shares/")[1].split("/")[0]
    assert token.startswith("u!")
    assert base64.urlsafe_b64decode(token[2:] + "=" * (-len(token[2:]) % 4)).decode() == SHARE_LINK
    assert m365.urls[2] == "https://graph.microsoft.com/v1.0/drives/drive-1/items/item-1/content"


def test_onedrive_for_work_address(microsoft):
    address = "https://contoso-my.sharepoint.com/personal/ana_contoso_com/Documents/answers.txt"

    def respond(request):
        if request.url.path.endswith("/drives") and request.url.host.startswith("graph."):
            return httpx.Response(200, json={"value": [
                {"id": "drive-1", "webUrl": "https://contoso-my.sharepoint.com/personal/ana_contoso_com/Documents"}]})
        return microsoft_365()._responder(request)
    m365 = Recorder(respond)
    cloud_files.fetch_sharepoint_file(address, client=m365.client)
    assert m365.urls[1] == ("https://graph.microsoft.com/v1.0/sites/contoso-my.sharepoint.com:"
                            "/personal/ana_contoso_com")
    assert m365.urls[3] == "https://graph.microsoft.com/v1.0/drives/drive-1/root:/answers.txt"


def test_us_government_cloud(microsoft, monkeypatch):
    monkeypatch.setenv("MS_CLOUD", "usgov")
    m365 = microsoft_365(graph_host="graph.microsoft.us", library="Shared%20Documents")

    def respond(request):
        if request.url.path.endswith("/drives") and request.url.host.startswith("graph."):
            return httpx.Response(200, json={"value": [
                {"id": "drive-1", "webUrl": "https://agency.sharepoint.us/sites/Vendors/Shared%20Documents"}]})
        return m365._responder(request)
    gov = Recorder(respond)
    cloud_files.fetch_sharepoint_file("https://agency.sharepoint.us/sites/Vendors/Shared%20Documents/answers.txt",
                                      client=gov.client)
    assert gov.urls[0].startswith("https://login.microsoftonline.us/")
    assert b"graph.microsoft.us" in gov.requests[0].content
    with pytest.raises(ConnectorError, match="sharepoint.us"):
        cloud_files.fetch_sharepoint_file(SITE_FILE, client=gov.client)


@pytest.mark.parametrize(("address", "message"), [
    ("https://attacker.example/sites/Vendors/Shared%20Documents/a.txt", "SharePoint or OneDrive address"),
    ("http://contoso.sharepoint.com/sites/Vendors/Shared%20Documents/a.txt", "SharePoint or OneDrive address"),
    ("https://contoso.sharepoint.com.attacker.example/sites/V/a.txt", "SharePoint or OneDrive address"),
    ("https://contoso.sharepoint.com/sites/Vendors/_layouts/15/Doc.aspx?sourcedoc=%7B1%7D", "displays the file"),
])
def test_sharepoint_rejects_other_addresses_before_any_request(microsoft, address, message):
    m365 = microsoft_365()
    with pytest.raises(ConnectorError, match=message):
        cloud_files.fetch_sharepoint_file(address, client=m365.client)
    assert m365.requests == []


def test_sharepoint_address_outside_every_library(microsoft):
    with pytest.raises(ConnectorError, match="document library"):
        cloud_files.fetch_sharepoint_file("https://contoso.sharepoint.com/sites/Vendors/Lists/Tasks/a.txt",
                                          client=microsoft_365().client)


@pytest.mark.parametrize(("item", "message"), [
    ({"id": "i", "name": "Acme", "folder": {}, "parentReference": {"driveId": "d"}}, "folder"),
    ({"id": "i", "name": "a.docx", "file": {}, "size": 5, "parentReference": {"driveId": "d"}}, "not a supported"),
    ({"id": "i", "name": "a.pdf", "file": {}, "size": 30 * 1024 * 1024, "parentReference": {"driveId": "d"}},
     "larger than 25 MB"),
])
def test_sharepoint_refuses_before_downloading(microsoft, item, message):
    m365 = microsoft_365(item=item)
    with pytest.raises(ConnectorError, match=message):
        cloud_files.fetch_sharepoint_file(SITE_FILE, client=m365.client)
    assert not any(url.endswith("/content") for url in m365.urls)


def test_microsoft_settings_are_checked(microsoft, monkeypatch):
    monkeypatch.setenv("MS_CLOUD", "moon")
    with pytest.raises(ConnectorError, match="MS_CLOUD"):
        cloud_files.fetch_sharepoint_file(SITE_FILE)
    monkeypatch.delenv("MS_CLOUD")
    monkeypatch.setenv("MS_TENANT_ID", "tenant/../../evil")
    with pytest.raises(ConnectorError, match="MS_TENANT_ID"):
        cloud_files.fetch_sharepoint_file(SITE_FILE, client=microsoft_365().client)
    monkeypatch.delenv("MS_TENANT_ID")
    with pytest.raises(ConnectorError, match="MS_TENANT_ID is not set"):
        cloud_files.fetch_sharepoint_file(SITE_FILE)


def test_sharepoint_permission_error(microsoft):
    def respond(request):
        if request.url.host.startswith("login."):
            return httpx.Response(200, json={"access_token": "t"})
        return httpx.Response(403, json={"error": {"message": "secret detail"}})
    with pytest.raises(ConnectorError) as error:
        cloud_files.fetch_sharepoint_file(SITE_FILE, client=Recorder(respond).client)
    assert "read access to this site" in str(error.value)
    assert "secret detail" not in str(error.value)


# --- shared ---

def test_downloaded_file_is_read_like_a_local_one_and_removed():
    submission = cloud_files.load_cloud_vendor("../../Acme answers.txt", PDF_TEXT, "Google Drive")
    assert submission.name == "Acme Cloud Inc."
    assert submission.path == "Google Drive: ../../Acme answers.txt"
    assert "MFA is enforced" in submission.text
    assert len(submission.sha256) == 64


def test_cli_reads_from_google_drive_and_sharepoint(repo_root, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr(cli, "fetch_google_drive_file", lambda ref: ("Acme answers.txt", b"We use DES for transit."))
    monkeypatch.setattr(cli, "fetch_sharepoint_file", lambda ref: ("Beta answers.txt", b"We use DES for transit."))
    assert cli.main(["analyze", f"gdrive:{FILE_ID}", "--out", str(tmp_path / "g")]) == 0
    assert "Vendor: Acme Answers" in capsys.readouterr().out
    record = json.loads(next((tmp_path / "g").glob("*.json")).read_text(encoding="utf-8"))
    assert record["vendor"]["file"] == "Google Drive: Acme answers.txt"
    assert cli.main(["analyze", f"sharepoint:{SITE_FILE}", "--out", str(tmp_path / "m")]) == 0
    assert "Vendor: Beta Answers" in capsys.readouterr().out
    assert cli.main(["analyze", f"onedrive:{SITE_FILE}", "--no-files"]) == 0


def test_cloud_readers_are_not_called_for_a_local_file(repo_root, monkeypatch):
    monkeypatch.chdir(repo_root)

    def fail(*args, **kwargs):
        raise AssertionError("a cloud reader was called for a local file")

    monkeypatch.setattr(cli, "fetch_google_drive_file", fail)
    monkeypatch.setattr(cli, "fetch_sharepoint_file", fail)
    assert cli.main(["analyze", "examples/weak_vendor.txt", "--no-files"]) == 0

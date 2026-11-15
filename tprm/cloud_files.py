"""Optional: read a vendor's document from Google Drive, SharePoint or OneDrive.

Nothing here runs unless the vendor file on the command line starts with
gdrive: or sharepoint:. Both use credentials an administrator sets up once
(a Google service account, a Microsoft app registration), so the tool can
only read what has been shared with that account.

Access is read-only. Tokens are sent only to Google's or Microsoft's own
API addresses, never to an address taken from the document link.
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote, urlparse

import httpx

from tprm.connectors import ConnectorError, _client, _send, _setting
from tprm.vendor import MAX_FILE_BYTES, SUPPORTED_EXTENSIONS, VendorSubmission, load_vendor

GOOGLE_SIGN_IN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_DRIVE_API = "https://www.googleapis.com/drive/v3/files"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
# Google's own formats have no file to download, so they are converted on the way out.
GOOGLE_EXPORTS = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet":
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
}

# Microsoft runs separate services for US government tenants (GCC High).
MICROSOFT_CLOUDS = {
    "global": ("https://login.microsoftonline.com", "https://graph.microsoft.com", (".sharepoint.com",)),
    "usgov": ("https://login.microsoftonline.us", "https://graph.microsoft.us", (".sharepoint.us",)),
}
REDIRECTS = (301, 302, 303, 307, 308)
MB = 1024 * 1024


def _check(response: httpx.Response, system: str, not_found: str) -> None:
    if response.status_code < 300:
        return
    hint = {
        401: " The credentials were not accepted.",
        403: f" The account is not allowed to read this. {not_found}",
        404: f" Nothing was found. {not_found}",
    }.get(response.status_code, "")
    raise ConnectorError(f"{system} answered with status {response.status_code}.{hint}")


def _json(response: httpx.Response, system: str) -> dict:
    try:
        body = response.json()
    except ValueError as error:
        raise ConnectorError(f"{system} sent a reply that could not be read.") from error
    if not isinstance(body, dict):
        raise ConnectorError(f"{system} sent a reply that could not be read.")
    return body


def _token(response: httpx.Response, system: str) -> dict[str, str]:
    if response.status_code >= 300:
        raise ConnectorError(f"{system} sign-in failed with status {response.status_code}. "
                             "Check the credentials in your .env file.")
    token = _json(response, system).get("access_token")
    if not token:
        raise ConnectorError(f"{system} sign-in did not return an access token.")
    return {"Authorization": f"Bearer {token}"}


def _check_type_and_size(name: str, size, system: str) -> None:
    extension = Path(name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ConnectorError(f"'{name}' in {system} is not a supported file type. "
                             f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}")
    if size is not None and int(size) > MAX_FILE_BYTES:
        raise ConnectorError(f"'{name}' in {system} is larger than {MAX_FILE_BYTES // MB} MB.")


def _content(response: httpx.Response, name: str, system: str) -> bytes:
    if len(response.content) > MAX_FILE_BYTES:
        raise ConnectorError(f"'{name}' in {system} is larger than {MAX_FILE_BYTES // MB} MB.")
    return response.content


# --- Google Drive ---

def google_file_id(reference: str) -> str:
    """Accepts a file ID, or a file's address copied from the browser."""
    reference = reference.strip()
    match = (re.search(r"/d/([A-Za-z0-9_-]{10,})", reference) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})", reference)
             or re.fullmatch(r"([A-Za-z0-9_-]{10,})", reference))
    if not match:
        raise ConnectorError("Give the Google Drive file ID or the file's address from your browser.")
    return match.group(1)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _google_assertion(key_file: str, now: Optional[float] = None) -> str:
    """Builds the signed sign-in request for a Google service account."""
    try:
        key = json.loads(Path(key_file).expanduser().read_text(encoding="utf-8"))
        email, private_key = key["client_email"], key["private_key"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ConnectorError("GOOGLE_SERVICE_ACCOUNT_FILE must point to a service account key file (JSON) "
                             "downloaded from Google Cloud.") from error
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError as error:  # pragma: no cover - cryptography is in requirements.txt
        raise ConnectorError("Reading from Google Drive needs the 'cryptography' package: "
                             "pip install -r requirements.txt") from error
    issued = int(now if now is not None else time.time())
    claims = {"iss": email, "scope": GOOGLE_SCOPE, "aud": GOOGLE_SIGN_IN_URL, "iat": issued, "exp": issued + 600}
    unsigned = (_b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode()) + "."
                + _b64url(json.dumps(claims).encode()))
    try:
        signer = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
        signature = signer.sign(unsigned.encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    except (ValueError, TypeError, AttributeError) as error:
        raise ConnectorError("The private key in the Google service account key file could not be used.") from error
    return f"{unsigned}.{_b64url(signature)}"


def fetch_google_drive_file(reference: str, client: Optional[httpx.Client] = None) -> tuple[str, bytes]:
    """Returns (file name, content) of one Google Drive file shared with the service account."""
    file_id = google_file_id(reference)
    assertion = _google_assertion(_setting("GOOGLE_SERVICE_ACCOUNT_FILE"))
    http = _client(client)
    headers = _token(_send("Google", lambda: http.post(GOOGLE_SIGN_IN_URL, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})), "Google")

    not_found = "Share the file with the service account's e-mail address (Viewer is enough)."
    response = _send("Google Drive", lambda: http.get(
        f"{GOOGLE_DRIVE_API}/{file_id}", headers=headers,
        params={"fields": "id,name,mimeType,size", "supportsAllDrives": "true"}))
    _check(response, "Google Drive", not_found)
    info = _json(response, "Google Drive")
    name, mime_type = str(info.get("name") or file_id), str(info.get("mimeType") or "")

    if mime_type in GOOGLE_EXPORTS:
        export_type, extension = GOOGLE_EXPORTS[mime_type]
        name = f"{name}{extension}"
        response = _send("Google Drive", lambda: http.get(
            f"{GOOGLE_DRIVE_API}/{file_id}/export", headers=headers, params={"mimeType": export_type}))
    elif mime_type.startswith("application/vnd.google-apps."):
        raise ConnectorError(f"'{name}' is a Google {mime_type.rsplit('.', 1)[-1]}, which cannot be read. "
                             "Use a Google Doc, a Google Sheet or an uploaded file.")
    else:
        _check_type_and_size(name, info.get("size"), "Google Drive")
        response = _send("Google Drive", lambda: http.get(
            f"{GOOGLE_DRIVE_API}/{file_id}", headers=headers, params={"alt": "media", "supportsAllDrives": "true"}))
    _check(response, "Google Drive", not_found)
    return name, _content(response, name, "Google Drive")


# --- SharePoint and OneDrive (Microsoft 365) ---

def _microsoft_cloud() -> tuple[str, str, tuple[str, ...]]:
    cloud = os.getenv("MS_CLOUD", "").strip().lower() or "global"
    if cloud not in MICROSOFT_CLOUDS:
        raise ConnectorError(f"MS_CLOUD is '{cloud}'. Use one of: {', '.join(MICROSOFT_CLOUDS)}.")
    return MICROSOFT_CLOUDS[cloud]


def _sharepoint_address(reference: str, host_suffixes: tuple[str, ...]) -> tuple[str, str, str]:
    """Checks a SharePoint or OneDrive address. Returns (address, host, decoded path)."""
    reference = reference.strip()
    parsed = urlparse(reference)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host.endswith(host_suffixes):
        raise ConnectorError("Give the file's SharePoint or OneDrive address, starting with https:// and "
                             f"ending in {' or '.join(host_suffixes)} before the first slash.")
    path = unquote(parsed.path)
    if "/_layouts/" in path.lower():
        raise ConnectorError("That is the address of the page that displays the file. In SharePoint, open the "
                             "file's details and copy its path, or use 'Copy link'.")
    return reference, host, path


def _site_path(path: str) -> str:
    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2 and parts[0].lower() in ("sites", "teams", "personal"):
        return f"/{parts[0]}/{parts[1]}"
    return ""


def fetch_sharepoint_file(reference: str, client: Optional[httpx.Client] = None) -> tuple[str, bytes]:
    """Returns (file name, content) of one file in SharePoint or OneDrive for work."""
    login, graph, host_suffixes = _microsoft_cloud()
    address, host, path = _sharepoint_address(reference, host_suffixes)
    tenant = _setting("MS_TENANT_ID")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", tenant):
        raise ConnectorError("MS_TENANT_ID must be your tenant ID or domain name.")
    http = _client(client)
    headers = _token(_send("Microsoft", lambda: http.post(f"{login}/{tenant}/oauth2/v2.0/token", data={
        "grant_type": "client_credentials", "client_id": _setting("MS_CLIENT_ID"),
        "client_secret": _setting("MS_CLIENT_SECRET"), "scope": f"{graph}/.default"})), "Microsoft")
    api = f"{graph}/v1.0"
    not_found = "Check the address and that the app registration has been given read access to this site."

    def get(url: str, **params) -> dict:
        response = _send("Microsoft 365", lambda: http.get(url, headers=headers, params=params or None))
        _check(response, "Microsoft 365", not_found)
        return _json(response, "Microsoft 365")

    if path.startswith("/:"):
        # A sharing link ("Copy link"). Microsoft looks the file up from the whole link.
        item = get(f"{api}/shares/u!{_b64url(address.encode('utf-8'))}/driveItem")
        drive_id = str((item.get("parentReference") or {}).get("driveId") or "")
    else:
        site_path = _site_path(path)
        site = get(f"{api}/sites/{host}:{quote(site_path)}" if site_path else f"{api}/sites/{host}")
        drives = get(f"{api}/sites/{site.get('id')}/drives", **{"$select": "id,webUrl"}).get("value") or []
        full = f"https://{host}{path}".lower()
        matches = [(unquote(str(d.get("webUrl") or "")).rstrip("/"), str(d.get("id") or "")) for d in drives]
        matches = [(url, drive) for url, drive in matches if url and drive and full.startswith(url.lower() + "/")]
        if not matches:
            raise ConnectorError(f"The address does not point into a document library of that site. {not_found}")
        library, drive_id = max(matches, key=lambda match: len(match[0]))
        relative = f"https://{host}{path}"[len(library) + 1:]
        item = get(f"{api}/drives/{drive_id}/root:/{quote(relative)}")

    name = str(item.get("name") or "")
    if not drive_id or not item.get("id") or "file" not in item:
        raise ConnectorError("That address is a folder or could not be opened as a file. Give the address of one file.")
    _check_type_and_size(name, item.get("size"), "Microsoft 365")

    response = _send("Microsoft 365", lambda: http.get(f"{api}/drives/{drive_id}/items/{item['id']}/content",
                                                      headers=headers))
    if response.status_code in REDIRECTS:
        # Microsoft answers with a short-lived download address. It needs no
        # token, so none is sent to it.
        location = response.headers.get("location", "")
        if urlparse(location).scheme != "https":
            raise ConnectorError("Microsoft 365 sent a download address that is not HTTPS.")
        response = _send("Microsoft 365", lambda: http.get(location))
    _check(response, "Microsoft 365", not_found)
    return name, _content(response, name, "Microsoft 365")


# --- shared ---

def load_cloud_vendor(name: str, content: bytes, origin: str, vendor_name: Optional[str] = None) -> VendorSubmission:
    """Reads a downloaded file the same way as a local one, then removes the local copy."""
    safe_name = re.sub(r"[^\w.\- ]", "_", Path(name).name).lstrip(".") or "vendor"
    with tempfile.TemporaryDirectory(prefix="tprm-") as folder:
        path = Path(folder) / safe_name
        path.write_bytes(content)
        submission = load_vendor(path, name=vendor_name)
    submission.path = f"{origin}: {name}"
    return submission

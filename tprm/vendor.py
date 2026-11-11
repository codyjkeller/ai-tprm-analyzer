"""Reads a vendor's submission (questionnaire answers or a document) into text."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

SUPPORTED_EXTENSIONS = (".json", ".csv", ".xlsx", ".txt", ".md", ".pdf")
MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_CHARS = 400_000

# Phrases that suggest the document is trying to steer an AI reviewer.
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
    r"disregard\s+.{0,40}(instructions|rules|controls)",
    r"system\s+prompt",
    r"you\s+are\s+(now\s+)?(an?|the)\s+(ai|assistant|auditor|language\s+model|reviewer)",
    r"(mark|rate|score|treat|consider)\s+(all|every|each)\s+.{0,40}(pass|compliant|satisf)",
    r"(respond|reply|output|return)\s+(only\s+)?(with\s+)?.{0,20}\bPASS\b",
]


class VendorInputError(Exception):
    """The vendor file is missing, unsupported, too large, or unreadable."""


@dataclass
class VendorSubmission:
    name: str
    path: str
    text: str
    sha256: str
    warnings: list[str] = field(default_factory=list)

    @property
    def normalized(self) -> str:
        return normalize(self.text)


def normalize(text: str) -> str:
    """Lowercases and collapses whitespace, for comparing quotes with the source."""
    return re.sub(r"\s+", " ", text).strip().lower()


def max_chars() -> int:
    try:
        return int(os.getenv("TPRM_MAX_CHARS", DEFAULT_MAX_CHARS))
    except ValueError:
        return DEFAULT_MAX_CHARS


def _flatten(value, prefix: str = "") -> list[str]:
    """Turns nested JSON into '[key] value' lines. Bracketed text is a label, not an answer."""
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            lines.extend(_flatten(item, f"{prefix}{key}" if not prefix else f"{prefix} / {key}"))
        return lines
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return [f"[{prefix}] {', '.join(str(item) for item in value)}"]
        lines = []
        for index, item in enumerate(value, 1):
            lines.extend(_flatten(item, f"{prefix} [{index}]"))
        return lines
    return [f"[{prefix}] {value}"]


def _read_json(path: Path) -> tuple[Optional[str], str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise VendorInputError(f"{path} is not valid JSON: {error}") from error
    name = None
    if isinstance(data, dict):
        profile = data.get("vendor_profile")
        if isinstance(profile, dict) and profile.get("name"):
            name = str(profile["name"])
        if isinstance(data.get("answers"), dict):
            data = data["answers"]
    return name, "\n".join(_flatten(data))


def _rows_to_text(rows: list[list]) -> str:
    """Formats questionnaire rows. Uses Question/Answer columns when present."""
    rows = [["" if cell is None else str(cell).strip() for cell in row] for row in rows]
    rows = [row for row in rows if any(row)]
    if not rows:
        return ""
    header = [cell.lower() for cell in rows[0]]
    question_col = next((i for i, cell in enumerate(header) if "question" in cell), None)
    answer_col = next((i for i, cell in enumerate(header) if "answer" in cell or "response" in cell), None)
    lines = []
    if question_col is not None and answer_col is not None:
        for row in rows[1:]:
            question = row[question_col] if question_col < len(row) else ""
            answer = row[answer_col] if answer_col < len(row) else ""
            if question or answer:
                lines.append(f"Question: {question}\nAnswer: {answer}")
        return "\n\n".join(lines)
    return "\n".join(" | ".join(cell for cell in row if cell) for row in rows)


def _read_csv(path: Path) -> str:
    try:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            return _rows_to_text(list(csv.reader(handle)))
    except (UnicodeDecodeError, csv.Error) as error:
        raise VendorInputError(f"{path} could not be read as CSV: {error}") from error


def _read_xlsx(path: Path) -> str:
    try:
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as error:
        raise VendorInputError(f"{path} could not be read as an Excel workbook: {error}") from error
    sections = []
    for sheet in workbook.worksheets:
        body = _rows_to_text([list(row) for row in sheet.iter_rows(values_only=True)])
        if body:
            sections.append(f"[Sheet: {sheet.title}]\n{body}")
    return "\n\n".join(sections)


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, 1)]
    except Exception as error:
        raise VendorInputError(f"{path} could not be read as a PDF: {error}") from error
    return "\n\n".join(f"[Page {number}]\n{text.strip()}" for number, text in pages if text.strip())


def find_injection_phrases(text: str) -> list[str]:
    found = []
    for pattern in INJECTION_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            found.append(re.sub(r"\s+", " ", match.group(0))[:80])
    return found


def load_vendor(path: Union[str, Path], name: Optional[str] = None) -> VendorSubmission:
    path = Path(path)
    if not path.is_file():
        raise VendorInputError(f"Vendor file not found: {path}")
    extension = path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise VendorInputError(
            f"Unsupported file type '{extension or path.name}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    if path.stat().st_size > MAX_FILE_BYTES:
        raise VendorInputError(f"{path} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.")

    detected_name = None
    if extension == ".json":
        detected_name, text = _read_json(path)
    elif extension == ".csv":
        text = _read_csv(path)
    elif extension == ".xlsx":
        text = _read_xlsx(path)
    elif extension == ".pdf":
        text = _read_pdf(path)
    else:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise VendorInputError(f"{path} is not UTF-8 text: {error}") from error

    text = text.strip()
    if not text:
        hint = " Scanned PDFs have no text layer; run OCR first." if extension == ".pdf" else ""
        raise VendorInputError(f"No text could be read from {path}.{hint}")
    limit = max_chars()
    if len(text) > limit:
        # Refuse instead of cutting: a partial read could miss the one
        # sentence that fails a control.
        raise VendorInputError(
            f"{path} contains {len(text):,} characters; the limit is {limit:,}. "
            "Split the document or raise TPRM_MAX_CHARS."
        )

    if not detected_name:
        # A first line such as "Vendor: Acme Cloud Inc." names the vendor.
        labelled = re.match(r"\s*(?:\[[^\]]*\]\s*)?Vendor(?: name)?:\s*(\S[^\n]{0,100})", text, flags=re.IGNORECASE)
        if labelled:
            detected_name = labelled.group(1).strip()

    warnings = []
    phrases = find_injection_phrases(text)
    if phrases:
        quoted = "; ".join(f'"{phrase}"' for phrase in phrases)
        warnings.append(
            "The document contains wording that looks like instructions to an AI reviewer "
            f"({quoted}). Read the document yourself before relying on this assessment."
        )

    return VendorSubmission(
        name=name or detected_name or path.stem.replace("_", " ").replace("-", " ").title(),
        path=str(path),
        text=text,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        warnings=warnings,
    )

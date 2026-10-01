"""Documents a company uploads about itself, for onboarding without a usable website (WEB.md
"Onboarding").

Only the text is kept. The file is read in memory, its text saved as JSON under
DATA_DIR/uploads/<pass>/, and the file itself is never written anywhere. Each pass has its own
folder and a document is only ever loaded from the caller's own, so no pass can read another's.

A document is the company's own words, but private: nothing AI can read. Its claims are verified
word for word like a page's (onboarding_model.page_span), and a claim found only in documents is
marked private_only, which drift.classify reads as a messaging gap.

Formats: PDF (pypdf, text layer only: a scan has none and is refused, there is no OCR), Word .docx
(the standard library: a .docx is a zip of XML), and plain text or Markdown, pasted text included.
"""
import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree

import reports
from schemas import utc_now

MAX_BYTES = 10 * 1024 * 1024   # per file
MAX_FILES = 5                  # per onboarding
MAX_CHARS = 30_000             # kept per document; a page keeps 12,000 (fetching.MAX_CHARS)
MAX_PDF_PAGES = 200
MAX_XML_BYTES = 50 * 1024 * 1024  # a .docx's document.xml, unpacked: refuses a zip bomb unread
KINDS = {".pdf": "pdf", ".docx": "docx", ".txt": "text", ".md": "text", ".markdown": "text"}
ACCEPTED = "PDF, Word (.docx), text (.txt) or Markdown (.md)"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class Unreadable(ValueError):
    """A document we cannot take, in words the user can act on."""


def kind_of(filename: str, data: bytes) -> str:
    """By extension, checked against the first bytes: a renamed file is refused, not misread."""
    kind = KINDS.get(Path(filename).suffix.lower())
    if kind == "pdf" and data.startswith(b"%PDF"):
        return kind
    if kind == "docx" and data.startswith(b"PK"):
        return kind
    if kind == "text" and b"\x00" not in data[:4096]:
        return kind
    raise Unreadable(f"{filename} is not a document we can read. Use {ACCEPTED}.")


def _pdf(filename: str, data: bytes) -> str:
    from pypdf import PdfReader   # lazy: only an upload needs it
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise Unreadable(f"{filename} is password-protected. Upload a copy without a password.")
        parts, total = [], 0
        for page in reader.pages[:MAX_PDF_PAGES]:
            parts.append(page.extract_text() or "")
            total += len(parts[-1])
            if total > MAX_CHARS * 2:
                break
    except Unreadable:
        raise
    except Exception as e:  # pypdf raises many kinds on a damaged file
        raise Unreadable(f"{filename} could not be opened as a PDF ({type(e).__name__}).") from e
    return "\n".join(parts)


def _docx(filename: str, data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_XML_BYTES:
                raise Unreadable(f"{filename} is too large once unpacked.")
            root = ElementTree.fromstring(z.read(info))
    except Unreadable:
        raise
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
        raise Unreadable(f"{filename} could not be opened as a Word document.") from e
    return "\n".join("".join(t.text or "" for t in p.iter(f"{W}t")) for p in root.iter(f"{W}p"))


def extract(filename: str, data: bytes) -> str:
    """-> the document's readable text, whitespace collapsed like a page's, capped at MAX_CHARS."""
    if len(data) > MAX_BYTES:
        raise Unreadable(f"{filename} is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    kind = kind_of(filename, data)
    raw = (_pdf(filename, data) if kind == "pdf" else _docx(filename, data) if kind == "docx"
           else data.decode("utf-8-sig", errors="replace"))
    text = " ".join(raw.split())[:MAX_CHARS]
    if not text:
        raise Unreadable(f"{filename} has no text we can read" + (
            " (it looks like scanned images). Export it with its text, or paste the words instead."
            if kind == "pdf" else "."))
    return text


def folder(pass_id: Optional[str]) -> Path:
    """This pass's own folder. A hash of its id, so no id can name a path outside uploads/."""
    name = hashlib.sha256(pass_id.encode()).hexdigest()[:16] if pass_id else "local"
    return reports.DATA / "uploads" / name


def save(pass_id: Optional[str], filename: str, data: bytes) -> dict:
    """Reads the file and keeps its text only. -> {id, filename, chars}."""
    name = Path(filename or "document").name[:120] or "document"
    text = extract(name, data)
    doc = dict(id=uuid.uuid4().hex[:10], filename=name, chars=len(text), text=text,
               created_at=utc_now())
    folder(pass_id).mkdir(parents=True, exist_ok=True)
    (folder(pass_id) / f"{doc['id']}.json").write_text(json.dumps(doc))
    return {k: doc[k] for k in ("id", "filename", "chars")}


def load(pass_id: Optional[str], ids: list[str]) -> list[dict]:
    """The caller's own documents, in the order asked. An id that is not in this pass's folder is
    unknown, whoever else may have uploaded it."""
    if len(ids) > MAX_FILES:
        raise Unreadable(f"At most {MAX_FILES} documents can be read at once.")
    out = []
    for doc_id in dict.fromkeys(ids):
        path = folder(pass_id) / f"{doc_id}.json"
        if not reports.ID.fullmatch(doc_id) or not path.exists():
            raise Unreadable("One of the documents is no longer available. Upload it again.")
        out.append(json.loads(path.read_text()))
    return out


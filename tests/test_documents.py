"""Uploaded documents: what is read, what is refused in words a user can act on, and that each pass
only ever reads its own. The sample files are built here, byte for byte, so nothing binary is committed."""
import io
import zipfile

import pytest

import documents
import reports
from documents import Unreadable


def make_pdf(*lines: str) -> bytes:
    """A one-page PDF whose text layer holds `lines`; with none, a page with no text, like a scan."""
    ops = " ".join(f"({t}) Tj 0 -16 Td" for t in lines)
    stream = f"BT /F1 12 Tf 72 720 Td {ops} ET".encode() if lines else b""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)


def make_docx(*paragraphs: str) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{w}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "DATA", tmp_path)
    return tmp_path


def test_a_pdf_is_read_from_its_text_layer():
    text = documents.extract("positioning.pdf", make_pdf("Harbor Loom bakes sourdough for cafes",
                                                         "and delivers before 6am every day."))
    assert "Harbor Loom bakes sourdough for cafes" in text and "delivers before 6am" in text


def test_a_word_document_and_plain_text_are_read():
    assert documents.extract("about.docx", make_docx("We make bread.", "We deliver early.")) == \
        "We make bread. We deliver early."
    assert documents.extract("notes.md", "# About\n\nWe  make\tbread.".encode()) == "# About We make bread."


def test_a_scanned_pdf_says_so_and_asks_for_text():
    with pytest.raises(Unreadable, match="looks like scanned images"):
        documents.extract("brand-deck.pdf", make_pdf())


@pytest.mark.parametrize("name,data,words", [
    ("photo.png", b"\x89PNG\r\n", "not a document we can read"),
    ("renamed.pdf", b"\x89PNG\r\n", "not a document we can read"),    # the extension is checked against the bytes
    ("broken.docx", b"PK\x03\x04 not a zip", "could not be opened as a Word document"),
    ("big.txt", b"a" * (documents.MAX_BYTES + 1), "larger than 10 MB"),
])
def test_what_cannot_be_read_is_refused_in_plain_words(name, data, words):
    with pytest.raises(Unreadable, match=words):
        documents.extract(name, data)


def test_a_long_document_is_capped():
    assert len(documents.extract("long.txt", b"word " * 20_000)) == documents.MAX_CHARS


def test_only_the_text_is_kept_in_the_passes_own_folder(data_dir):
    doc = documents.save("pass-a", "positioning.pdf", make_pdf("Harbor Loom bakes sourdough for cafes"))
    stored = list((data_dir / "uploads").rglob("*"))
    assert [p.suffix for p in stored if p.is_file()] == [".json"]                  # no copy of the PDF
    assert documents.load("pass-a", [doc["id"]])[0]["text"] == "Harbor Loom bakes sourdough for cafes"


def test_no_pass_can_read_another_passes_document():
    doc = documents.save("pass-a", "plan.txt", b"Our secret plan.")
    for other in ("pass-b", None):
        with pytest.raises(Unreadable, match="no longer available"):
            documents.load(other, [doc["id"]])


def test_a_document_id_cannot_walk_out_of_the_folder():
    with pytest.raises(Unreadable):
        documents.load("pass-a", ["../../access"])
    assert documents.folder("../../etc").parent == reports.DATA / "uploads"


def test_at_most_five_documents_are_read_at_once():
    ids = [documents.save(None, f"d{i}.txt", b"text")["id"] for i in range(documents.MAX_FILES + 1)]
    with pytest.raises(Unreadable, match="At most 5"):
        documents.load(None, ids)

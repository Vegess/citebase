"""Text extraction for uploads: PDF, Word (.docx), Markdown and plain text.

Word files are read with the standard library (a .docx is a zip of XML), so
there's no extra dependency. Headings come out as "## Heading" lines, which the
heading-aware chunker recognises, and table rows as "cell | cell" lines.
Zip bombs are refused by checking the declared uncompressed size first.
"""
import io
import re
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_DOCX_XML = 40 * 1024 * 1024
_INVISIBLE = re.compile(r"[​-‍⁠﻿]")


class ExtractionError(ValueError):
    """Shown to the user as-is."""


def kind_of(raw: bytes, filename: str) -> str:
    name = filename.lower()
    if raw.startswith(b"%PDF-"):
        return "pdf"
    if raw.startswith(b"PK\x03\x04"):
        return "docx" if name.endswith(".docx") or _is_docx(raw) else "unsupported"
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        return "unsupported"
    return "markdown" if name.endswith((".md", ".markdown")) else "text"


def _is_docx(raw: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            return "word/document.xml" in z.namelist()
    except zipfile.BadZipFile:
        return False


def _pdf(raw: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ExtractionError("This PDF is password-protected. Upload an unlocked copy.")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except PdfReadError:
        raise ExtractionError("This PDF looks damaged and couldn't be read.")


def _paragraph_text(p) -> str:
    parts = []
    for node in p.iter():
        if node.tag == W + "t" and node.text:
            parts.append(node.text)
        elif node.tag in (W + "tab",):
            parts.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return "".join(parts).strip()


def _docx(raw: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > MAX_DOCX_XML:
                raise ExtractionError("This Word file is too large to read.")
            xml = z.read(info)
    except (zipfile.BadZipFile, KeyError):
        raise ExtractionError("This Word file looks damaged and couldn't be read.")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise ExtractionError("This Word file looks damaged and couldn't be read.")
    body = root.find(W + "body")
    lines: list[str] = []
    for block in (body if body is not None else []):
        if block.tag == W + "p":
            text = _paragraph_text(block)
            if not text:
                continue
            style = block.find(f"{W}pPr/{W}pStyle")
            style_name = (style.get(W + "val") or "").lower() if style is not None else ""
            if style_name.startswith("heading") or style_name == "title":
                lines.append(f"\n## {text}")
            elif block.find(f"{W}pPr/{W}numPr") is not None:
                lines.append(f"- {text}")
            else:
                lines.append(text)
        elif block.tag == W + "tbl":
            for row in block.iter(W + "tr"):
                cells = [" ".join(_paragraph_text(p) for p in cell.iter(W + "p")).strip() for cell in row.iter(W + "tc")]
                if any(cells):
                    lines.append(" | ".join(cells))
            lines.append("")
    return "\n".join(lines)


_MD_LINK = re.compile(r"!?\[([^\]]*)\]\(([^)]*)\)")


def _markdown(text: str) -> str:
    # Keep headings (the chunker reads "#" lines); turn [text](url) into "text (url)".
    return _MD_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})" if m.group(1) else "", text)


def extract(raw: bytes, filename: str) -> str:
    kind = kind_of(raw, filename)
    if kind == "pdf":
        text = _pdf(raw)
    elif kind == "docx":
        text = _docx(raw)
    elif kind == "markdown":
        text = _markdown(raw.decode("utf-8"))
    elif kind == "text":
        text = raw.decode("utf-8")
    else:
        raise ExtractionError("Upload a PDF, Word (.docx), Markdown or plain-text file.")
    return _INVISIBLE.sub("", text)

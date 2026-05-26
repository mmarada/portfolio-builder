"""
Parse PDF or DOCX resume into plain text.
"""
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def parse_resume(path: Path | str) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Resume not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(path)
    elif suffix in (".docx", ".doc"):
        return _parse_docx(path)
    else:
        return path.read_text(encoding="utf-8", errors="replace")


def _parse_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        return "\n".join(pages).strip()
    except Exception as e:
        log.error("PDF parse error: %s", e)
        return ""


def _parse_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception as e:
        log.error("DOCX parse error: %s", e)
        return ""


def find_resume(resume_dir: Path) -> Path | None:
    """Return the first PDF/DOCX found in resume_dir."""
    for ext in ("*.pdf", "*.docx", "*.doc", "*.txt"):
        matches = list(resume_dir.glob(ext))
        if matches:
            return matches[0]
    return None

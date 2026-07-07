"""
PRD Parser — reads .md/.txt/.docx/.pdf files and returns plain text.

All format-specific dependencies are lazy-loaded so the framework works
even if only openpyxl + openai are installed.
"""

from pathlib import Path
from typing import Optional


def read_prd(file_path: str) -> str:
    """Read a PRD/document file and return its plain text content.

    Supports: .md, .txt, .docx (python-docx), .pdf (pdfplumber).
    Returns empty string on unsupported formats with a warning.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"PRD file not found: {file_path}")

    suffix = path.suffix.lower()

    if suffix in (".md", ".txt", ".markdown"):
        return path.read_text(encoding="utf-8")

    if suffix == ".docx":
        return _read_docx(path)

    if suffix == ".pdf":
        return _read_pdf(path)

    # Fallback: try reading as text
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"⚠️  无法解析 {file_path}，格式不支持: {suffix}")
        return ""


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except ImportError:
        raise ImportError(
            "读取 .docx 需要安装 python-docx: pip install python-docx"
        )


def _read_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages)
    except ImportError:
        raise ImportError(
            "读取 .pdf 需要安装 pdfplumber: pip install pdfplumber"
        )


def load_scope(module: str, context_dir: Optional[str] = None) -> Optional[str]:
    """Load scope.md for a module if it exists.

    scope.md declares what is OUT of scope for this team's testing,
    preventing the reviewer from flagging missing coverage on out-of-scope items.
    See [[mall-liuhuo-test-scope]].
    """
    if context_dir:
        base = Path(context_dir)
    else:
        base = Path(__file__).parent.parent / "context"
    scope_path = base / module / "scope.md"
    if scope_path.exists():
        return scope_path.read_text(encoding="utf-8")
    return None


def load_glossary(module: str, context_dir: Optional[str] = None) -> Optional[str]:
    """Load glossary.md for a module if it exists.

    Glossary provides domain-specific enums/terms to prevent LLM hallucination.
    See [[mall-liuhuo-strategy-config-prd]] for examples.
    """
    if context_dir:
        base = Path(context_dir)
    else:
        base = Path(__file__).parent.parent / "context"
    gloss_path = base / module / "glossary.md"
    if gloss_path.exists():
        return gloss_path.read_text(encoding="utf-8")
    return None

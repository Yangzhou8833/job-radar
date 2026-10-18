"""Turn the CV you put in profile/ into plain text for /setup to read.

    python radar.py cv-extract              # newest CV in profile/ -> profile/cv.txt
    python radar.py cv-extract path/to/cv.pdf

Supports .pdf (pypdf if installed, else the `pdftotext` command), .docx (read directly,
no extra package), and .md / .txt. The text stays in profile/, which is git-ignored.
"""
import glob
import os
import re
import shutil
import subprocess
import zipfile

from . import config

CV_TYPES = (".pdf", ".docx", ".md", ".txt")


def find_cv():
    files = [p for p in glob.glob(os.path.join(config.PROFILE_DIR, "*"))
             if p.lower().endswith(CV_TYPES) and os.path.basename(p) not in ("cv.txt", "README.md")]
    return max(files, key=os.path.getmtime) if files else None


def pdf_text(path):
    try:
        from pypdf import PdfReader
        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    except ImportError:
        pass
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"], capture_output=True)
        if r.returncode == 0:
            return r.stdout.decode("utf-8", "replace")
    raise SystemExit("Cannot read PDFs here: run `pip install pypdf`, or save your CV as .docx or .txt")


def docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    import html
    return html.unescape(text)


def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        text = pdf_text(path)
    elif ext == ".docx":
        text = docx_text(path)
    elif ext in (".md", ".txt"):
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    else:
        raise SystemExit(f"Unsupported CV type {ext}; use one of {', '.join(CV_TYPES)}")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def cli(args):
    path = args.path or find_cv()
    if not path:
        raise SystemExit("No CV found. Put your CV (.pdf, .docx, .md or .txt) in the profile/ folder first.")
    text = extract(path)
    if len(text) < 200:
        raise SystemExit(f"Only {len(text)} characters came out of {path}; is it a scanned image? Try a .docx or .txt export.")
    out = os.path.join(config.PROFILE_DIR, "cv.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"{config.rel(path)} -> {config.rel(out)} ({len(text)} characters)")

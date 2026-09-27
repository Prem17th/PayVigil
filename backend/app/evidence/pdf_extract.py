"""Resource-limited child process. Never runs in the API interpreter."""

import json
import sys


def main():
    import resource

    try:
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        kind = resource.RLIMIT_AS if sys.platform.startswith("linux") else resource.RLIMIT_DATA
        resource.setrlimit(kind, (192 * 1024 * 1024, 192 * 1024 * 1024))
    except (OSError, ValueError):
        # Never silently parse without memory protection on unsupported hosts.
        sys.exit(3)
    raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
    print(json.dumps(parse_pdf(raw)))


def parse_pdf(raw):
    """Pure parsing step; runtime calls it only after resource limits succeed."""
    from io import BytesIO
    from pypdf import PdfReader

    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("oversize")
    reader = PdfReader(BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 20:
        raise ValueError("unsupported")
    pages, total = [], 0
    for number, page in enumerate(reader.pages, 1):
        content = page.extract_text() or ""
        total += len(content)
        if total > 40_000 or not content.strip():
            raise ValueError("scanned or oversized")
        pages.append({"page": number, "text": content})
    return pages


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(2)

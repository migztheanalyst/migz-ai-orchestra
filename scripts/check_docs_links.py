#!/usr/bin/env python3
from pathlib import Path
from urllib.parse import unquote
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def main():
    broken = []
    for doc in sorted(ROOT.rglob("*.md")):
        if ".git" in doc.parts:
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        for raw in LINK.findall(text):
            target = raw.strip().split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            target = unquote(target)
            path = (doc.parent / target).resolve()
            if not path.exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    if broken:
        print("DOC_LINK_CHECK: FAIL")
        print("\n".join(broken))
        return 1
    print("DOC_LINK_CHECK: PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

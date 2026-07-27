"""Regression guard for issue #1335 — PR review screenshots were committed into
docs/ (docs/a11y/*.png from #738, docs/gallery-314-*.png from #644) where they
served no purpose: nothing in the repo referenced them, so they just showed up
as "random images" in the doc folder.

This test fails if any image under docs/ is orphaned — present in the tree but
referenced by no tracked text file. The intended doc assets (the README hero
image and the feature preview clips) are referenced, so they pass; a stray
screenshot dropped in by a future PR would not.
"""
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
# Files a referenced image name could legitimately appear in.
TEXT_EXTS = {".md", ".html", ".htm", ".js", ".ts", ".css", ".py", ".sh",
             ".json", ".yml", ".yaml", ".txt"}


def _tracked(paths_under):
    """Git-tracked files under a path, or None if git isn't available."""
    try:
        out = subprocess.run(
            ["git", "ls-files", paths_under],
            cwd=REPO, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [REPO / line for line in out.stdout.splitlines() if line.strip() and (REPO / line).exists()]


def test_no_orphan_images_in_docs():
    docs_dir = REPO / "docs"
    docs_images = [p for p in docs_dir.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    if not docs_images:
        pytest.skip("docs/ contains no images")

    all_tracked = _tracked(".") or [p for p in REPO.rglob("*") if p.is_file()]
    haystack = []
    for p in all_tracked:
        if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            haystack.append(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    blob = "\n".join(haystack)

    orphans = [
        str(img.relative_to(REPO))
        for img in docs_images
        if img.name not in blob
    ]
    assert not orphans, (
        "unreferenced image(s) committed under docs/ — likely PR screenshots "
        f"added by accident (see #1335): {orphans}"
    )

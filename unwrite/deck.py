"""Deck directory: the sealed draft, its sentence segments, and the paragraph memos."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

STANCES = {"asserted": "断定", "hedged": "ぼかし", "speculative": "推測", "cited": "引用"}
DROP_REASONS = ("filler", "signpost", "restatement", "meta")
ATOM_KEYS = ("numbers", "eqs", "refs", "labels", "terms")

SEALED = ".sealed"
FORMAT = 1  # version of deck.json / memos.json


class Deck:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    # paths
    @property
    def sealed(self) -> Path:
        return self.root / SEALED

    @property
    def meta_path(self) -> Path:
        return self.root / "deck.json"

    @property
    def segments_path(self) -> Path:
        return self.sealed / "segments.json"

    @property
    def memos_path(self) -> Path:
        return self.root / "memos.json"

    @property
    def qa_path(self) -> Path:
        return self.sealed / "qa.json"

    # io
    def exists(self) -> bool:
        return self.meta_path.exists() and self.segments_path.exists()

    def meta(self) -> dict:
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def segments(self) -> list[dict]:
        return json.loads(self.segments_path.read_text(encoding="utf-8"))

    def raw_memos(self) -> dict:
        if not self.memos_path.exists():
            return {"unwrite": FORMAT, "memos": [], "dropped": []}
        return json.loads(self.memos_path.read_text(encoding="utf-8"))

    def memos(self) -> list[dict]:
        from .memo import normalize_memo
        return [normalize_memo(m) for m in self.raw_memos().get("memos", [])]

    def write_memos(self, memos: list[dict], dropped: list[dict]) -> None:
        _write_json(self.memos_path, {"unwrite": FORMAT, "memos": memos, "dropped": dropped}, indent=1)

    def qa(self) -> list[dict] | None:
        if not self.qa_path.exists():
            return None
        return json.loads(self.qa_path.read_text(encoding="utf-8"))

    def macros(self) -> dict:
        return self.meta().get("macros", {})

    def create(self, source_path: Path, text: str, fmt: str, segments: list[dict],
               title: str = "", macros: dict | None = None, paper: str = "") -> None:
        self.sealed.mkdir(parents=True, exist_ok=True)
        (self.sealed / f"source{source_path.suffix or '.txt'}").write_text(text, encoding="utf-8")
        _write_json(self.segments_path, segments)
        deck_id = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        _write_json(self.meta_path, {
            "unwrite": FORMAT, "id": deck_id, "title": title or source_path.stem,
            "source": str(source_path), "paper": paper, "format": fmt,
            "segments": len(segments), "macros": macros or {},
        })


def _write_json(path: Path, obj, indent: int = 2) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")

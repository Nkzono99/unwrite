"""Workspace: a separate directory holding the fragmented copy of a paperops draft.

    <ws>/unwrite.json   where the draft came from
    <ws>/deck/             paragraph memos, sealed snapshot of the draft
    <ws>/manuscript/       main.tex etc. copied; numbers.tex / refs.bib symlinked to the draft;
                           section files replaced by skeletons (headings, math, figures, memos as comments)
    <ws>/figures ->        symlink to the draft's figures/
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

from .deck import Deck
from .segment import segment
from .texsrc import expand_inputs, number_macros, read_paper_toml

LINKED = {"numbers.tex", "refs.bib"}  # stay in sync with the draft (results get re-analysed)
SKIP_DIRS = {"en", "build", "sections"}


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


CONFIG = "unwrite.json"


def default_out(paper: Path) -> Path:
    """<paper>-fragments next to the draft project."""
    paper = paper.resolve()
    return paper.parent / f"{paper.name}-fragments"


def init_workspace(paper: Path, out: Path | None = None) -> Deck:
    paper = paper.resolve()
    out = (out or default_out(paper)).resolve()
    if out == paper or paper in out.parents:
        raise SystemExit(f"{out} は下書きの中にある（下書きの外に作る）")
    info = read_paper_toml(paper)
    main = paper / info["main"]
    if not main.exists():
        raise SystemExit(f"main が見つからない: {main}")
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} は空ではない")
    out.mkdir(parents=True, exist_ok=True)

    # sealed snapshot of the draft
    text = expand_inputs(main)
    full = "\n".join(p.read_text(encoding="utf-8") for p in sorted(main.parent.rglob("*.tex"))
                     if "en" not in p.relative_to(main.parent).parts[:1])
    macros = number_macros(full)
    segs = segment(text, "tex")
    deck = Deck(out / "deck")
    deck.create(main, text, "tex", segs, title=info.get("title") or paper.name,
                macros=macros, paper=str(paper))

    # manuscript copy
    src_ms = main.parent
    dst_ms = out / "manuscript"
    dst_ms.mkdir()
    for p in src_ms.iterdir():
        if p.name in SKIP_DIRS or p.name.startswith("."):
            continue
        target = dst_ms / p.name
        if p.name in LINKED:
            os.symlink(p, target)
        elif p.is_file():
            shutil.copy2(p, target)
    (dst_ms / "sections").mkdir(exist_ok=True)
    fig = paper / "figures"
    if fig.exists():
        os.symlink(fig, out / "figures")
    _write_json(out / CONFIG, {
        "unwrite": 1, "paper": str(paper), "main": info["main"],
        "created": date.today().isoformat(), "deck": "deck",
    })
    (out / ".gitignore").write_text("deck/.sealed/\nbuild/\n", encoding="utf-8")
    return deck


def load_workspace(ws: Path) -> tuple[dict, Deck]:
    cfg = json.loads((ws / CONFIG).read_text(encoding="utf-8"))
    return cfg, Deck(ws / cfg.get("deck", "deck"))


def _blank_caption(raw: str, notes: list[str]) -> str:
    m = re.search(r"\\caption\*?(?:\[[^\]]*\])?\{", raw)
    if not m:
        return raw + ("\n" + "\n".join(notes) if notes else "")
    depth, end = 0, len(raw)
    for i in range(m.end() - 1, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    body = "\n".join(notes) if notes else "% （メモなし）"
    return raw[:m.end()] + "\n" + body + "\n" + raw[end:]


HEADER = [
    "% unwrite skeleton",
    "% 段落ごとのメモ（言いたいこと・材料・流れ）を見て、その下に自分の文で書く。メモは書き終えたら消してよい。",
    "% [ ] ¶n は書き終えたら [x]、捨てたら [-] にしてよい。引用[?] は確かめたら 引用[ok]、誤りなら 引用[NG] に。",
    "% ⟨ ⟩ の中は逐語で使うもの（数値マクロ=値、式、引用、参照）。",
]


def write_skeleton(ws: Path, force: bool = False) -> list[Path]:
    """Write manuscript/sections/*.tex: headings, math, figures verbatim; each paragraph slot carries
    its memo as TeX comments."""
    from .memo import memo_tex

    cfg, deck = load_workspace(ws)
    segs = deck.segments()
    macros = deck.macros()
    memo_by_slot = {m["slot"]: m for m in deck.memos()}
    if not memo_by_slot:
        raise SystemExit(f"{deck.memos_path} にメモが無い（先にメモを作って lint を通す）")
    float_slot: dict[str, str] = {}  # figure caption -> the paragraph memo that describes it
    for m in memo_by_slot.values():
        for it in m["items"]:
            for sid in it["source"]:
                float_slot.setdefault(sid, m["slot"])

    def notes_for(key: str | None) -> list[str]:
        if key in memo_by_slot:
            return memo_tex(memo_by_slot[key], macros)
        if key in float_slot:
            return [f"% （この図の説明の材料は ¶{float_slot[key]} のメモにある）"]
        return []

    files: dict[str, list[str]] = {}
    last_slot: dict[str, str] = {}
    last_para: dict[str, int] = {}
    for s in segs:
        f = s.get("file") or ""
        if not f:
            continue
        out = files.setdefault(f, [])
        if s["kind"] == "heading":
            if s.get("raw"):
                out += ["", s["raw"]]
        elif s["kind"] == "sentence":
            slot = s.get("slot") or s["id"]
            if last_slot.get(f) != slot:
                label = f"¶{s['para']}" + "（式・図の後の続き）" * (last_para.get(f) == s["para"])
                body = notes_for(s.get("slot"))
                rule = "─" * max(4, 40 - len(label))
                out += ["", f"% ── {label} {rule}"] + (body or ["% （情報なしとして除いた文だけの段落）"]) + [""]
                last_slot[f] = slot
                last_para[f] = s["para"]
        elif s["kind"] == "math":
            out += ["", s["text"], ""]
        elif s["kind"] == "float":
            out += ["", _blank_caption(s.get("raw", s["text"]), notes_for(s["id"])), ""]

    written = []
    ms = ws / "manuscript"
    record_path = deck.root / "skeleton.json"
    record = json.loads(record_path.read_text(encoding="utf-8")) if record_path.exists() else {}
    for f, lines in files.items():
        path = ms / f
        if path.exists() and not force:
            now = hashlib.sha1(path.read_bytes()).hexdigest()
            if record.get(f) != now:
                print(f"skip {f}: 骨組みから書き換えられている（--force で上書き）")
                continue
        path.parent.mkdir(parents=True, exist_ok=True)
        body = HEADER + lines
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(body)).rstrip() + "\n"
        path.write_text(text, encoding="utf-8")
        record[f] = hashlib.sha1(text.encode("utf-8")).hexdigest()
        written.append(path)
    _write_json(record_path, record)
    return written

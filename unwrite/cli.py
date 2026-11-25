"""unwrite command line."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .deck import Deck
from .lint import lint, summarize
from .segment import CONTENT_KINDS, detect_format, segment


def _target(path: str) -> tuple[Path | None, Deck]:
    """Accept a workspace (unwrite.json) or a deck directory (deck.json)."""
    from .workspace import CONFIG, load_workspace
    p = Path(path)
    if (p / CONFIG).exists():
        _, deck = load_workspace(p)
        return p, deck
    deck = Deck(p)
    if not deck.exists():
        raise SystemExit(f"{p} は workspace でも deck でもない")
    return None, deck


def _secs(arg: str | None) -> set[int] | None:
    if not arg:
        return None
    out: set[int] = set()
    for part in arg.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        else:
            out.add(int(part))
    return out


def cmd_init(a):
    from .workspace import default_out, init_workspace
    out = Path(a.out) if a.out else default_out(Path(a.paper))
    deck = init_workspace(Path(a.paper), out)
    segs = deck.segments()
    n = sum(1 for s in segs if s["kind"] in CONTENT_KINDS)
    nsec = max((s["sec"] for s in segs), default=0)
    print(f"workspace: {out}  (節 {nsec}, 内容の文 {n}, 数値マクロ {len(deck.macros())})")
    print("次: LLM が段落メモを作り（skill unwrite）、lint を通してから skeleton。原文の表示は `unwrite segments` だけで行う。")


def cmd_split(a):
    src = Path(a.source)
    fmt = detect_format(src)
    if fmt == "tex":
        from .texsrc import expand_inputs, number_macros
        text = expand_inputs(src)
        macros = number_macros(text)
    else:
        text = src.read_text(encoding="utf-8")
        macros = {}
    deck = Deck(a.out)
    if deck.raw_memos().get("memos") and not a.force:
        raise SystemExit(f"{deck.memos_path} にメモがある（--force で作り直す）")
    segs = segment(text, fmt)
    deck.create(src, text, fmt, segs, macros=macros)
    n = sum(1 for s in segs if s["kind"] in CONTENT_KINDS)
    print(f"deck: {a.out}  (内容の文 {n}, 見出し {len(segs) - n})")


def cmd_segments(a):
    _, deck = _target(a.target)
    secs = _secs(a.section)
    covered = set()
    if a.todo:
        data = deck.raw_memos()
        covered = {sid for m in data.get("memos", []) for sid in m.get("source", [])}
        covered |= {sid for d in data.get("dropped", []) for sid in d.get("source", [])}
    last_slot = None
    for s in deck.segments():
        if secs is not None and s.get("sec") not in secs:
            continue
        if s["kind"] == "heading":
            mark = "#" * max(1, s.get("level", 1))
            print(f"\n{s['id']} {mark} [sec {s.get('sec')}] {s['text']}")
            continue
        if s["id"] in covered:
            continue
        if s.get("slot") and s["slot"] != last_slot:
            last_slot = s["slot"]
            print(f"--- ¶{last_slot}")
        print(f"{s['id']} [{s['kind']} ¶{s.get('slot', s['para'])}] {s['text']}")


def cmd_lint(a):
    _, deck = _target(a.target)
    if a.part:
        data, qa = json.loads(Path(a.part).read_text(encoding="utf-8")), None
    else:
        data, qa = deck.raw_memos(), deck.qa()
    issues = lint(deck.segments(), data, deck.macros(), _secs(a.section), qa=qa)
    if a.json:
        print(json.dumps([i.__dict__ for i in issues], ensure_ascii=False, indent=1))
    else:
        for lvl in ("error", "warn", "info"):
            for i in issues:
                if i.level == lvl and (lvl != "info" or a.verbose):
                    print(i)
        print(summarize(issues))
    sys.exit(1 if any(i.level == "error" for i in issues) else 0)


def cmd_merge(a):
    _, deck = _target(a.target)
    memos, dropped, seen = [], [], set()
    for f in a.parts:
        part = json.loads(Path(f).read_text(encoding="utf-8"))
        for m in part.get("memos", []):
            if str(m.get("slot")) in seen:
                raise SystemExit(f"段落の重複: ¶{m.get('slot')} ({f})")
            seen.add(str(m.get("slot")))
            memos.append(m)
        dropped += part.get("dropped", [])
    order = {s["slot"]: i for i, s in reversed(list(enumerate(deck.segments()))) if s.get("slot")}
    memos.sort(key=lambda m: order.get(str(m.get("slot")), 10 ** 9))
    deck.write_memos(memos, dropped)
    print(f"merged {len(memos)} memos, {len(dropped)} dropped -> {deck.memos_path}")


def cmd_memos(a):
    from .memo import memos_text
    _, deck = _target(a.target)
    sys.stdout.write(memos_text(deck.memos(), deck.macros()))


def cmd_skeleton(a):
    from .workspace import write_skeleton
    for p in write_skeleton(Path(a.workspace), force=a.force):
        print(f"wrote {p}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="unwrite",
                                 description="AI 草稿を段落ごとのメモに砕き、メモをコメントで入れた原稿の骨組みを別ディレクトリに作る")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="paperops の論文から workspace を作る（下書きは封印し、書き込まない）")
    p.add_argument("paper")
    p.add_argument("-o", "--out", help="workspace（省略時は下書きの隣の <paper>-fragments）")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("split", help="1 ファイルの草稿から deck だけを作る（workspace・骨組みは作らない）")
    p.add_argument("source"); p.add_argument("-o", "--out", required=True)
    p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_split)

    p = sub.add_parser("segments", help="[LLM 用] 封印した原文を文 ID・段落付きで表示する")
    p.add_argument("target"); p.add_argument("--section", help="節番号 (例 2 / 3-4 / 1,5)")
    p.add_argument("--todo", action="store_true", help="まだどのメモにも dropped にも無い文だけ")
    p.set_defaults(fn=cmd_segments)

    p = sub.add_parser("lint", help="memos.json（か部分ファイル）を検査する")
    p.add_argument("target"); p.add_argument("--section"); p.add_argument("--part", help="部分ファイルを検査する")
    p.add_argument("--json", action="store_true"); p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_lint)

    p = sub.add_parser("merge", help="部分ファイルを memos.json にまとめる")
    p.add_argument("target"); p.add_argument("parts", nargs="+"); p.set_defaults(fn=cmd_merge)

    p = sub.add_parser("memos", help="メモをテキストで表示する（原文を含まない。盲検 QA 用）")
    p.add_argument("target"); p.set_defaults(fn=cmd_memos)

    p = sub.add_parser("skeleton", help="workspace の原稿に骨組み（見出し・式・図はそのまま、段落にメモのコメント）を書く")
    p.add_argument("workspace"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_skeleton)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()

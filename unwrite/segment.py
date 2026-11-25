"""Split a LaTeX / Markdown draft into segments (sentences, display math, floats, headings)."""
from __future__ import annotations

import re
from pathlib import Path

from .textutil import plain, strip_tex_comments, tokenize

CONTENT_KINDS = ("sentence", "math", "float")  # must be covered by memos or dropped

_TEX_HEADING = re.compile(
    r"^\s*\\(part|chapter|section|subsection|subsubsection|paragraph)\*?\s*(?:\[[^\]]*\])?\s*\{(.*)\}\s*$"
)
_TEX_BEGIN = re.compile(r"^\\begin\{(\w+)(\*?)\}")
_TEX_END = re.compile(r"^\\end\{(\w+)\*?\}")
_MATH_ENVS = {"equation", "align", "gather", "multline", "eqnarray", "displaymath", "math", "flalign"}
_FLOAT_ENVS = {"figure", "table", "algorithm", "lstlisting", "verbatim", "minted", "wrapfigure"}
_DROP_MARKER_ENVS = {"itemize", "enumerate", "description", "abstract", "center", "quote", "quotation"}

_ABBREV = [
    "e.g.", "i.e.", "et al.", "Fig.", "Figs.", "Eq.", "Eqs.", "Ref.", "Refs.", "Sec.", "Secs.",
    "Tab.", "cf.", "vs.", "etc.", "approx.", "No.", "resp.", "Ch.", "Dr.", "Prof.", "Ref.", "Appx.",
]
_PROTECT = re.compile(r"\$[^$]*\$|\\\(.*?\\\)|\\[a-zA-Z]+\*?(?:\[[^\]]*\])*\{[^}]*\}")
_SPLIT = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z0-9\\(\[\"'`\ue000\u3040-\u30ff\u4e00-\u9fff])|(?<=[。．！？])\s*"
)


def detect_format(path: Path) -> str:
    return "tex" if path.suffix.lower() in (".tex", ".ltx") else "md"


def _balanced_arg(s: str, start: int) -> str:
    """Return the {...} argument starting at s[start] == '{'."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start + 1:i]
    return s[start + 1:]


def _caption(block: str) -> str | None:
    m = re.search(r"\\caption\*?(?:\[[^\]]*\])?\{", block)
    if not m:
        return None
    labels = " ".join(re.findall(r"\\label\{[^}]*\}", block))
    return (_balanced_arg(block, m.end() - 1) + " " + labels).strip()


def split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    saved: list[str] = []

    def keep(m: re.Match) -> str:
        saved.append(m.group(0))
        return f"\ue000{len(saved) - 1}\ue001"

    t = _PROTECT.sub(keep, text)
    for ab in _ABBREV:
        t = t.replace(ab, ab.replace(".", "\ue002"))
    parts = [p.strip() for p in _SPLIT.split(t) if p and p.strip()]
    out = []
    for p in parts:
        p = p.replace("\ue002", ".")
        p = re.sub(r"\ue000(\d+)\ue001", lambda m: saved[int(m.group(1))], p)
        out.append(p)
    return out


_LEVELS = {"part": 0, "chapter": 0, "section": 1, "subsection": 2, "subsubsection": 3, "paragraph": 4}


def _tex_blocks(text: str) -> list[tuple]:
    """Blocks: (kind, text[, extra]). kinds: heading, para, math, float, file, endfile."""
    text = strip_tex_comments(text)
    m = re.search(r"\\begin\{document\}(.*?)\\end\{document\}", text, re.S)
    if m:
        text = m.group(1)
    text = re.sub(r"\\(maketitle|tableofcontents|newpage|clearpage|appendix)\b", "", text)
    text = re.sub(r"\\bibliography(style)?\{[^}]*\}", "", text)
    lines = text.split("\n")
    blocks: list[tuple] = []
    para: list[str] = []
    cjk = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text))
    cont = [False]  # text right after display math (no blank line) continues the same paragraph

    def flush():
        if para:
            blocks.append(("para", " ".join(para), {"cont": cont[0]}))
            para.clear()
        cont[0] = False

    def collect(i: int, end_pat: re.Pattern, first_rest: str) -> tuple[list[str], int]:
        got = [lines[i]]
        if end_pat.search(first_rest):
            return got, i + 1
        j = i + 1
        while j < len(lines):
            got.append(lines[j])
            if end_pat.search(lines[j]):
                return got, j + 1
            j += 1
        return got, j

    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if not s:
            flush()
            cont[0] = False
            i += 1
            continue
        fm = re.match(r"^\\unwritefile\{([^}]*)\}$", s)
        if fm:
            flush()
            blocks.append(("file", fm.group(1)))
            i += 1
            continue
        if s == "\\unwriteendfile":
            flush()
            blocks.append(("endfile", ""))
            i += 1
            continue
        lm = re.match(r"^\\label\{[^}]*\}$", s)
        if lm and not para and blocks and blocks[-1][0] == "heading":
            blocks[-1][2]["raw"] = (blocks[-1][2].get("raw", "") + " " + s).strip()
            i += 1
            continue
        h = _TEX_HEADING.match(line)
        if h:
            flush()
            blocks.append(("heading", h.group(2).strip(), {"level": _LEVELS[h.group(1)], "raw": s}))
            i += 1
            continue
        b = _TEX_BEGIN.match(s)
        env = b.group(1) if b else None
        if env == "abstract":
            flush()
            blocks.append(("heading", "要旨" if cjk else "Abstract", {"level": 1, "raw": "", "abstract": True}))
            rest = s[b.end():].strip()
            if rest:
                para.append(rest)
            i += 1
            continue
        if env in _MATH_ENVS or s.startswith("\\[") or s.startswith("$$"):
            flush()
            if env:
                end_pat = re.compile(r"\\end\{" + re.escape(env) + r"\*?\}")
                rest = s[b.end():]
            elif s.startswith("\\["):
                end_pat, rest = re.compile(r"\\\]"), s[2:]
            else:
                end_pat, rest = re.compile(r"\$\$"), s[2:]
            got, i = collect(i, end_pat, rest)
            blocks.append(("math", "\n".join(x.rstrip() for x in got)))
            cont[0] = True
            continue
        if env in _FLOAT_ENVS:
            flush()
            end_pat = re.compile(r"\\end\{" + re.escape(env) + r"\*?\}")
            got, i = collect(i, end_pat, s[b.end():])
            whole = "\n".join(x.rstrip() for x in got)
            blocks.append(("float", _caption(whole) or whole, {"raw": whole}))
            continue
        if env in _DROP_MARKER_ENVS or _TEX_END.match(s):
            flush()
            rest = s[b.end():].strip() if b else ""
            if rest:
                para.append(rest)
            i += 1
            continue
        if s.startswith("\\item"):
            flush()
            para.append(re.sub(r"^\\item(\[[^\]]*\])?\s*", "", s))
            i += 1
            continue
        para.append(s)
        i += 1
    flush()
    return blocks


def _md_blocks(text: str) -> list[tuple]:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    lines = text.split("\n")
    blocks: list[tuple] = []
    para: list[str] = []

    def flush():
        if para:
            blocks.append(("para", " ".join(para)))
            para.clear()

    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            flush()
            i += 1
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", s)
        if h:
            flush()
            blocks.append(("heading", h.group(2).strip(), {"level": len(h.group(1)), "raw": s}))
            i += 1
            continue
        if s.startswith("```") or s.startswith("$$"):
            flush()
            fence = s[:3] if s.startswith("```") else "$$"
            got = [s]
            if fence == "$$" and s.count("$$") >= 2:
                i += 1
            else:
                i += 1
                while i < len(lines):
                    got.append(lines[i].strip())
                    if lines[i].strip().startswith(fence) or (fence == "$$" and "$$" in lines[i]):
                        i += 1
                        break
                    i += 1
            blocks.append(("math" if fence == "$$" else "float", "\n".join(got)))
            continue
        if s.startswith("|"):
            flush()
            got = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                got.append(lines[i].strip())
                i += 1
            blocks.append(("float", "\n".join(got)))
            continue
        if re.match(r"^([-*+]|\d+\.)\s+", s):
            flush()
            para.append(re.sub(r"^([-*+]|\d+\.)\s+", "", s))
            i += 1
            continue
        if s.startswith(">"):
            s = s.lstrip(">").strip()
        para.append(s)
        i += 1
    flush()
    return blocks


def segment(text: str, fmt: str) -> list[dict]:
    """Segments with structure: sec (top-level section index), section/sub titles, para, file."""
    blocks = _tex_blocks(text) if fmt == "tex" else _md_blocks(text)
    segs: list[dict] = []
    para = 0
    sec = 0
    section = ""
    sub = ""
    files: list[str] = [""]
    top = min((b[2]["level"] for b in blocks if b[0] == "heading"), default=1)
    for blk in blocks:
        kind, body = blk[0], blk[1]
        extra = blk[2] if len(blk) > 2 else {}
        if kind == "file":
            files.append(body)
            continue
        if kind == "endfile":
            if len(files) > 1:
                files.pop()
            continue
        base = {"file": files[-1]}
        if kind == "heading":
            level = extra.get("level", 1)
            if level <= top:
                sec += 1
                section, sub = body, ""
            else:
                sub = body
            segs.append({**base, "kind": "heading", "level": level, "raw": extra.get("raw", ""),
                         "para": para, "sec": sec, "section": section, "sub": sub, "text": body})
            continue
        if kind == "para":
            if not extra.get("cont") or para == 0:
                para += 1
            for sent in split_sentences(body):
                bare = sent
                for _ in range(4):  # strip commands with arguments, then bare brace groups
                    bare = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})*", " ", bare)
                    bare = re.sub(r"\{[^{}]*\}", " ", bare)
                has_text = any(t.kind in ("word", "cjk") for t in tokenize(plain(bare)))
                segs.append({**base, "kind": "sentence" if has_text else "control", "para": para,
                             "sec": sec, "section": section, "sub": sub, "text": sent})
            continue
        seg = {**base, "kind": kind, "para": para, "sec": sec, "section": section, "sub": sub, "text": body}
        if "raw" in extra:
            seg["raw"] = extra["raw"]
        segs.append(seg)
    assign_slots(segs)
    width = max(3, len(str(len(segs))))
    out = []
    for n, s in enumerate(segs, 1):
        out.append({"id": f"s{n:0{width}d}", **s})
    return out


def assign_slots(segs: list[dict]) -> None:
    """A slot is the run of sentences of one paragraph between display math / figures / headings.
    Labels: "3" for paragraph 3, "3b", "3c" for its continuations after an equation or figure."""
    seen: dict[int, int] = {}
    prev_break = True
    current = None
    for s in segs:
        if s["kind"] in ("math", "float", "heading"):
            prev_break = True
            s.pop("slot", None)
            continue
        if s["kind"] != "sentence":
            s.pop("slot", None)
            continue
        if prev_break or current is None or current[0] != s["para"]:
            n = seen.get(s["para"], 0)
            seen[s["para"]] = n + 1
            current = (s["para"], f"{s['para']}" + ("" if n == 0 else "bcdefghij"[n - 1]))
            prev_break = False
        s["slot"] = current[1]

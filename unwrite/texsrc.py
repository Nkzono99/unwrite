"""Read LaTeX sources: \\input expansion with file markers, number macros, paperops projects."""
from __future__ import annotations

import re
from pathlib import Path

from .textutil import strip_tex_comments

FILE_BEGIN = "\\unwritefile"   # marker line: \unwritefile{relative/path.tex}
FILE_END = "\\unwriteendfile"
_INPUT_RE = re.compile(r"\\(?:input|include)\{([^}]+)\}")
_NEWCMD_RE = re.compile(
    r"\\(?:re)?(?:new|provide)command\*?\s*\{?\\([a-zA-Z]+)\}?\s*\{((?:[^{}]|\{[^{}]*\})*)\}"
)


def _resolve(base: Path, name: str) -> Path | None:
    p = base / name
    for cand in (p, p.with_name(p.name + ".tex")):
        if cand.is_file():
            return cand
    return None


def expand_inputs(main: Path) -> str:
    """Inline \\input / \\include recursively (comments stripped), wrapping each file in markers."""
    main = main.resolve()
    root = main.parent

    def walk(path: Path, depth: int) -> str:
        text = strip_tex_comments(path.read_text(encoding="utf-8"))
        if depth > 8:
            return text

        def sub(m: re.Match) -> str:
            target = _resolve(root, m.group(1).strip())
            if target is None:
                return m.group(0)
            rel = target.relative_to(root).as_posix() if target.is_relative_to(root) else target.name
            body = walk(target, depth + 1)
            return f"\n{FILE_BEGIN}{{{rel}}}\n{body}\n{FILE_END}\n"

        return _INPUT_RE.sub(sub, text)

    return walk(main, 0)


def number_macros(text: str) -> dict[str, str]:
    """Argument-less macros whose body contains a digit and is short: values to keep as atoms."""
    out: dict[str, str] = {}
    for m in _NEWCMD_RE.finditer(text):
        # macros with arguments ({\foo}[1]{...}) do not match: the body brace must follow directly
        name, body = m.group(1), m.group(2).strip()
        if re.search(r"\d", body) and len(body) <= 40 and "#" not in body:
            out[name] = body
    return out


def read_paper_toml(paper: Path) -> dict:
    """Minimal reader for paperops paper.toml (main, lang, title)."""
    path = paper / "paper.toml"
    info = {"main": "manuscript/main.tex", "lang": "", "title": paper.name}
    if not path.exists():
        return info
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib  # Python >= 3.11
        data = tomllib.loads(text)
        sec = data.get("paper", {})
        info.update({k: sec[k] for k in ("main", "lang", "title") if k in sec})
        return info
    except ModuleNotFoundError:
        pass
    for key in ("main", "lang", "title"):
        m = re.search(rf'^\s*{key}\s*=\s*"([^"]*)"', text, re.M)
        if m:
            info[key] = m.group(1)
    return info

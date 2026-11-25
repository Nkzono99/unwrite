"""Paragraph memos: for each paragraph slot, what it wants to say, the material it must carry, and how
it connects to its neighbours. Written for a human to read and then write the paragraph in their own words.

memos.json:
{
  "unwrite": 1,
  "memos": [
    {"slot": "3", "point": "...", "role": "...",
     "items": [{"text": "...", "atoms": {...}, "stance": "asserted", "source": ["s012"]}],
     "source": ["s010", "s011", ...]}
  ],
  "dropped": [{"source": ["s099"], "reason": "signpost"}]
}
"""
from __future__ import annotations

import re

from .deck import ATOM_KEYS, STANCES


def normalize_memo(m: dict) -> dict:
    items = []
    for it in m.get("items") or []:
        atoms = it.get("atoms") or {}
        items.append({"text": it.get("text", "") or "", "stance": it.get("stance", "asserted"),
                      "atoms": {k: list(atoms.get(k) or []) for k in ATOM_KEYS},
                      "source": list(it.get("source") or []), "verify": it.get("verify", "unchecked")})
    return {"slot": str(m.get("slot", "")), "point": m.get("point", "") or "", "role": m.get("role", "") or "",
            "items": items, "source": list(m.get("source") or [])}


def all_atoms(memos: list[dict]) -> set[str]:
    out: set[str] = set()
    for m in memos:
        for it in m["items"]:
            for k in ATOM_KEYS:
                out.update(str(x) for x in it["atoms"][k])
    return out


def one(s) -> str:
    """One line: comments in TeX and list items in Markdown must not break."""
    return " ".join(str(s).split())


def mtext(s: str, macros: dict) -> str:
    """Replace number macros with their values for reading."""
    return re.sub(r"\\([a-zA-Z]+)(\{\})?", lambda m: macros.get(m.group(1), m.group(0)), one(s))


def atoms_tex(c: dict, macros: dict) -> list[str]:
    """Atoms as the TeX the writer would type."""
    out: list[str] = []
    for x in map(one, c["atoms"]["numbers"]):
        names = [n for n in re.findall(r"\\([a-zA-Z]+)", str(x)) if n in macros]
        if names:
            out.append(", ".join(f"\\{n}{{}}={macros[n]}" for n in names))
        else:
            out.append(str(x))
    out += [x if x.startswith("$") else f"${x}$" for x in map(one, c["atoms"]["eqs"])]
    if c["atoms"]["refs"]:
        out.append("\\citep{" + ",".join(c["atoms"]["refs"]) + "}")
    out += [f"\\ref{{{x}}}" for x in c["atoms"]["labels"]]
    return out


# --- rendering -------------------------------------------------------------------------

def memo_tex(m: dict, macros: dict) -> list[str]:
    L = [f"% [ ] ¶{m['slot']} 言いたいこと: {mtext(m['point'], macros)}"]
    if m["items"]:
        L.append("%   材料:")
    for it in m["items"]:
        tag = "" if it["stance"] == "asserted" else f"（{STANCES.get(it['stance'], it['stance'])}）"
        line = f"%     - {mtext(it['text'], macros)}{tag}"
        at = atoms_tex(it, macros)
        if it["atoms"]["refs"]:
            at.append({"ok": "引用[ok]", "wrong": "引用[NG]"}.get(it["verify"], "引用[?]"))
        if at:
            line += "   ⟨" + "  ".join(at) + "⟩"
        L.append(line)
    if m["role"]:
        L.append(f"%   流れ: {mtext(m['role'], macros)}")
    return L


def memos_text(memos: list[dict], macros: dict) -> str:
    """Plain text for a blind reader (no source)."""
    out = []
    for m in memos:
        out += [ln[2:] if ln.startswith("% ") else ln.lstrip("%") for ln in memo_tex(m, macros)]
        out.append("")
    return "\n".join(out)

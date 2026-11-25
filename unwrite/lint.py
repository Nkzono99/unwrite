"""Mechanical checks on memos.json: schema, coverage, atoms, copying of the draft's wording, QA."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .deck import ATOM_KEYS, DROP_REASONS, STANCES
from .memo import all_atoms, mtext, normalize_memo, one
from .segment import CONTENT_KINDS
from .textutil import (
    cite_keys, label_keys, macros_used, mask, nfkc, norm_ws, numbers_loose, numbers_strict, tokenize,
)

# a memo restates content; it must not reproduce the draft's sentences
N_LAT, N_CJK = 10, 20
LIMITS = {"point": 160, "role": 120, "item": 90}  # characters

EVAL_EN = [
    "crucial", "pivotal", "paramount", "delve", "delves", "intricate", "tapestry", "landscape",
    "realm", "underscore", "underscores", "showcase", "showcases", "noteworthy", "remarkable",
    "remarkably", "groundbreaking", "comprehensive", "seamless", "seamlessly", "leverage",
    "leverages", "harness", "unprecedented", "invaluable", "profound", "holistic", "multifaceted",
    "nuanced", "vital", "shed light", "sheds light", "plays a role", "key role", "highlight",
    "highlights", "elucidate", "elucidates",
]
EVAL_JA = [
    "重要な役割", "鍵となる", "鍵を握る", "不可欠", "極めて", "非常に", "顕著", "画期的", "革新的",
    "包括的", "多角的", "様々な", "さまざまな", "興味深い", "注目すべき", "重要", "深い洞察",
    "示唆に富む", "可能性を秘め", "新たな知見", "浮き彫り", "明らかにする",
]


@dataclass
class Issue:
    level: str  # error | warn | info
    where: str
    code: str
    msg: str

    def __str__(self) -> str:
        return f"{self.level.upper():5} {self.where:8} {self.code:22} {self.msg}"


def _has_word(text_lower: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", text_lower) is not None


def lint(segments: list[dict], data: dict, macros: dict | None = None,
         secs: set[int] | None = None, qa: list[dict] | None = None) -> list[Issue]:
    """Check memos. macros: number macros (name -> value). secs: restrict coverage to these sections.
    qa: graded QA round trip (.sealed/qa.json), reported when given."""
    macros = macros or {}
    issues: list[Issue] = []

    def add(level, where, code, msg):
        issues.append(Issue(level, where, code, msg))

    seg_by_id = {s["id"]: s for s in segments}
    in_scope = [s for s in segments if s["kind"] in CONTENT_KINDS and (secs is None or s.get("sec") in secs)]
    slots_in_scope = {s["slot"] for s in in_scope if s.get("slot")}
    memos = [normalize_memo(m) for m in data.get("memos", [])]
    dropped = data.get("dropped", []) or []

    # --- schema & slot mapping ----------------------------------------------------
    by_slot: dict[str, dict] = {}
    covered: dict[str, str] = {}
    for m in memos:
        w = f"¶{m['slot']}"
        if m["slot"] in by_slot:
            add("error", w, "memo.slot", "同じ段落のメモが 2 つある")
        by_slot[m["slot"]] = m
        if not m["point"].strip():
            add("error", w, "memo.point", "言いたいこと（point）が空")
        if not m["items"]:
            add("warn", w, "memo.items", "材料（items）が無い")
        for sid in m["source"]:
            seg = seg_by_id.get(sid)
            if seg is None:
                add("error", w, "memo.source", f"'{sid}' は存在しない文 ID")
                continue
            if seg.get("slot") and seg["slot"] != m["slot"]:
                add("error", w, "memo.source", f"'{sid}' は ¶{seg['slot']} の文")
            covered[sid] = m["slot"]
        for k, it in enumerate(m["items"]):
            for sid in it["source"]:
                if sid not in m["source"] and sid in seg_by_id and seg_by_id[sid]["kind"] == "sentence":
                    add("error", f"{w}.{k}", "memo.source", f"item の source '{sid}' がメモの source に無い")
            if it["stance"] not in STANCES:
                add("error", f"{w}.{k}", "memo.stance", f"stance は {sorted(STANCES)} のどれか")
    dropped_ids = set()
    for k, d in enumerate(dropped):
        if d.get("reason") not in DROP_REASONS:
            add("error", f"drop#{k}", "drop.reason", f"reason は {list(DROP_REASONS)} のどれか")
        dropped_ids.update(d.get("source") or [])
    for s in in_scope:
        if s["kind"] == "sentence" and s["id"] not in covered and s["id"] not in dropped_ids:
            add("error", s["id"], "coverage", f"¶{s.get('slot')} の文がどのメモにも dropped にも無い")
    item_srcs = {sid for m in memos for it in m["items"] for sid in it["source"]}
    for s in in_scope:
        if s["kind"] == "float" and s["id"] not in item_srcs:
            add("error", s["id"], "coverage", "図表の caption がどの材料の source にも無い（図を説明する段落のメモに入れる）")
    for slot in sorted(slots_in_scope - set(by_slot), key=lambda x: (len(x), x)):
        sids = [s["id"] for s in in_scope if s.get("slot") == slot]
        if not all(x in dropped_ids for x in sids):
            add("error", f"¶{slot}", "memo.missing", "この段落のメモが無い")

    # --- atoms: verbatim and completeness ---------------------------------------------
    full_raw = "\n".join(s["text"] for s in segments)
    for m in memos:
        src = "\n".join(seg_by_id[x]["text"] for x in m["source"] if x in seg_by_id)
        # math / floats that sit right after the slot may also be referenced
        src_all = src + "\n" + full_raw
        got_nums, got_refs, got_labels, got_macros = set(), set(), set(), set()
        for k, it in enumerate(m["items"]):
            w = f"¶{m['slot']}.{k}"
            for a in it["atoms"]["numbers"]:
                used = macros_used(str(a), macros)
                for name in used - macros_used(src_all, macros):
                    add("error", w, "atoms.numbers", f"マクロ '\\{name}' が草稿に無い")
                if not used and numbers_loose(str(a)) - numbers_loose(src_all):
                    add("error", w, "atoms.numbers", f"数値 '{a}' が草稿に無い")
            for a in it["atoms"]["eqs"]:
                if norm_ws(a) not in norm_ws(src_all):
                    add("error", w, "atoms.eqs", f"式 '{one(a)[:40]}' が草稿に逐語で無い")
            for a in it["atoms"]["refs"]:
                if a not in cite_keys(src_all):
                    add("error", w, "atoms.refs", f"引用 '{a}' が草稿に無い")
            for a in it["atoms"]["labels"]:
                if a not in label_keys(src_all):
                    add("error", w, "atoms.labels", f"ラベル '{a}' が草稿に無い")
            for key in ATOM_KEYS:
                for a in it["atoms"][key]:
                    got_nums |= numbers_loose(str(a))
                    got_macros |= macros_used(str(a), macros)
            got_refs |= set(it["atoms"]["refs"])
            got_labels |= set(it["atoms"]["labels"])
        w = f"¶{m['slot']}"
        for n in sorted(_needed_numbers(src) - got_nums):
            add("error", w, "atoms.lost", f"数値 '{n}' がどの材料の atoms にも無い")
        for name in sorted(macros_used(src, macros) - got_macros):
            add("error", w, "atoms.lost", f"数値マクロ '\\{name}' がどの材料の atoms にも無い")
        for r in sorted(cite_keys(src) - got_refs):
            add("error", w, "atoms.lost", f"引用 '{r}' がどの材料の atoms.refs にも無い")
        for r in sorted(label_keys(src) - got_labels):
            add("error", w, "atoms.lost", f"ラベル '{r}' がどの材料の atoms.labels にも無い")
    for sid in dropped_ids:
        seg = seg_by_id.get(sid)
        if seg and (numbers_strict(seg["text"]) or cite_keys(seg["text"]) or label_keys(seg["text"])
                    or macros_used(seg["text"], macros)):
            add("error", sid, "atoms.dropped", "数値・引用・ラベルを含む文を dropped にしている")

    # --- wording ----------------------------------------------------------------------
    masks = frozenset(all_atoms(memos))
    src_keys = {k for s in segments if s["kind"] in CONTENT_KINDS
                for _, _, k in memo_windows(tokenize(mask(s["text"], masks)))}
    for m in memos:
        texts = [("point", m["point"]), ("role", m["role"])]
        texts += [(f"item{k}", it["text"]) for k, it in enumerate(m["items"])]
        for name, text in texts:
            w = f"¶{m['slot']}"
            limit = LIMITS["item" if name.startswith("item") else name]
            if len(one(mtext(text, macros))) > limit:
                add("warn", w, "memo.length", f"{name} が長い（{limit} 字まで）")
            toks = tokenize(mask(str(text), masks))
            hits = [("" if key[0] == "C" else " ").join(t.text for t in toks[i:i + n])
                    for i, n, key in memo_windows(toks) if key in src_keys and not _nominal(toks[i:i + n])]
            if hits:
                add("error", w, "memo.copy", f"{name} が草稿の文をそのまま写している: '{hits[0]}'")
            low = nfkc(mask(str(text), masks)).lower()
            for word in EVAL_EN:
                if _has_word(low, word):
                    add("warn", w, "memo.eval", f"{name} に評価語・AI 語彙 '{word}'")
            for word in EVAL_JA:
                if word in text and word not in ("重要",):
                    add("warn", w, "memo.eval", f"{name} に評価語・AI 語彙 '{word}'")

    # --- QA ----------------------------------------------------------------------
    if qa is None:
        add("info", "qa", "qa.missing", "QA 往復が未実施（.sealed/qa.json が無い）")
    else:
        graded = [q for q in qa if "ok" in q]
        failed = [q for q in graded if not q.get("ok")]
        if len(graded) < len(qa):
            add("warn", "qa", "qa.ungraded", f"未採点の質問が {len(qa) - len(graded)} 件")
        if failed:
            add("warn", "qa", "qa.failed", f"メモだけでは答えられない質問が {len(failed)}/{len(graded)} 件")
        else:
            add("info", "qa", "qa.pass", f"QA {len(graded)}/{len(graded)} 件合格")

    return issues


_INLINE_MATH = re.compile(r"\$[^$]*\$")


def _needed_numbers(text: str) -> set[str]:
    """Numbers a memo must carry. Zero and single digits that occur only inside inline math
    (exponents, indices, ordinals in formulas) are not quantities to keep."""
    outside = numbers_strict(_INLINE_MATH.sub(" ", text))
    need = numbers_strict(text)
    need = {n for n in need if n in outside or not re.fullmatch(r"\d", n)}
    return need - {"0"}


_HIRA = re.compile(r"[\u3041-\u309f]")


def _nominal(run) -> bool:
    """A run whose only hiragana are の/と is a (long) noun phrase, e.g. 三次元の粒子計算と光電子の放出モデル."""
    cjk = [t.text for t in run if t.kind == "cjk"]
    if len(cjk) < len(run) / 2:
        return False  # Latin text: no noun-phrase exemption
    return all(h in "のと" for h in cjk if _HIRA.match(h))


def memo_windows(toks):
    """Windows of weight >= N_CJK where a CJK character weighs 1 and a word or number weighs 2
    (pure Latin text: N_LAT words). Deterministic per start, so equal sequences give equal keys."""
    n = len(toks)
    for i in range(n):
        w = 0
        latin = 0
        for j in range(i, n):
            t = toks[j]
            if t.kind == "brk":
                break
            w += 1 if t.kind == "cjk" else 2
            latin += t.kind != "cjk"
            if (latin == j - i + 1 and latin >= N_LAT) or w >= N_CJK:
                run = toks[i:j + 1]
                kind = "L" if latin == len(run) else ("C" if latin == 0 else "M")
                yield i, len(run), (kind,) + tuple(x.text for x in run)
                break


def summarize(issues: list[Issue]) -> str:
    n = {lvl: sum(1 for i in issues if i.level == lvl) for lvl in ("error", "warn", "info")}
    return f"errors {n['error']}, warnings {n['warn']}, info {n['info']}"

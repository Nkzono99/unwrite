import copy
import json
import shutil
from pathlib import Path

import pytest

from unwrite.cli import main
from unwrite.lint import lint
from unwrite.memo import memos_text
from unwrite.segment import split_sentences
from unwrite.workspace import default_out, init_workspace, write_skeleton

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def ws(tmp_path):
    out = tmp_path / "ws"
    deck = init_workspace(FIX / "paper", out)
    shutil.copy(FIX / "paper_memos.json", deck.memos_path)
    return out, deck


def codes(issues, level="error"):
    return {(i.where, i.code) for i in issues if i.level == level}


def test_split_sentences_keeps_abbrev_and_math():
    s = split_sentences("See Fig. 2 and Zhao et al. (2021). The value $x = 1. y$ holds. 次の文。最後の文。")
    assert s == ["See Fig. 2 and Zhao et al. (2021).", "The value $x = 1. y$ holds.", "次の文。", "最後の文。"]


def test_segments_structure(ws):
    out, deck = ws
    segs = deck.segments()
    heads = [s["text"] for s in segs if s["kind"] == "heading"]
    assert heads == ["Abstract", "Introduction", "Method", "Results"]
    math = [s for s in segs if s["kind"] == "math"][0]
    after = segs[segs.index(math) + 1]
    assert after["para"] == math["para"]  # text after display math continues the paragraph
    assert {s["file"] for s in segs} >= {"sections/intro.tex", "sections/method.tex"}
    assert deck.macros() == {"floorPot": "-30", "wallPot": "-50"}
    cfg = json.loads((out / "unwrite.json").read_text())
    assert cfg["main"] == "manuscript/main.tex"


def test_good_memos_pass(ws):
    _, deck = ws
    issues = lint(deck.segments(), deck.raw_memos(), deck.macros())
    assert codes(issues) == set(), [str(i) for i in issues]


def test_lint_catches_violations(ws):
    _, deck = ws
    bad = copy.deepcopy(deck.raw_memos())
    bad["memos"][4]["items"][0]["text"] = "the crater floor charges more negatively as the crater radius increases"
    bad["memos"][4]["items"][1]["atoms"]["numbers"] = ["10"]
    del bad["memos"][3]
    got = codes(lint(deck.segments(), bad, deck.macros()))
    assert ("¶4", "memo.copy") in got
    assert ("¶4", "atoms.lost") in got
    assert ("¶3b", "memo.missing") in got


def test_section_filter(ws):
    _, deck = ws
    data = deck.raw_memos()
    secs = {s["slot"] for s in deck.segments() if s.get("sec") == 3 and s.get("slot")}
    part = {"memos": [m for m in data["memos"] if m["slot"] in secs], "dropped": []}
    assert part["memos"]
    assert codes(lint(deck.segments(), part, deck.macros(), secs={3})) == set()


def test_qa_reported(ws):
    _, deck = ws
    qa = [{"q": "x", "a": "y", "ok": True}, {"q": "z", "a": "w", "ok": False}]
    issues = lint(deck.segments(), deck.raw_memos(), deck.macros(), qa=qa)
    assert ("qa", "qa.failed") in codes(issues, "warn")


def test_memos_text_has_no_source(ws):
    _, deck = ws
    text = memos_text(deck.memos(), deck.macros())
    assert "¶4" in text and "s017" not in text
    for s in deck.segments():
        if s["kind"] == "sentence" and len(s["text"]) > 30:
            assert s["text"] not in text


def test_skeleton(ws):
    out, _ = ws
    write_skeleton(out)
    sec = out / "manuscript" / "sections"
    res = (sec / "results.tex").read_text()
    assert res.startswith("% unwrite skeleton")
    assert "% [ ] ¶4 言いたいこと: クレーターが大きいほど" in res
    assert "\\floorPot{}=-30" in res
    method = (sec / "method.tex").read_text()
    assert "\\begin{equation}" in method and "% ── ¶3" in method
    assert "plays a crucial role" not in (sec / "intro.tex").read_text()
    assert (out / "manuscript" / "numbers.tex").is_symlink()

    # skeleton refuses to overwrite a section the human edited
    (sec / "results.tex").write_text(res + "\nLarger craters reach \\floorPot{}~V.\n")
    write_skeleton(out)
    assert "Larger craters" in (sec / "results.tex").read_text()


def test_skeleton_needs_memos(tmp_path):
    out = tmp_path / "ws"
    init_workspace(FIX / "paper", out)
    with pytest.raises(SystemExit):
        write_skeleton(out)


def test_default_out_is_beside_the_draft(tmp_path):
    paper = tmp_path / "mypaper"
    shutil.copytree(FIX / "paper", paper)
    assert default_out(paper) == tmp_path / "mypaper-fragments"
    main(["init", str(paper)])
    assert (tmp_path / "mypaper-fragments" / "unwrite.json").exists()
    with pytest.raises(SystemExit):
        init_workspace(paper, paper / "inside")


def test_merge_orders_parts(ws, tmp_path):
    out, deck = ws
    data = deck.raw_memos()
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(json.dumps({"memos": data["memos"][3:], "dropped": data["dropped"]}))
    b.write_text(json.dumps({"memos": data["memos"][:3], "dropped": []}))
    main(["merge", str(out), str(a), str(b)])
    merged = deck.raw_memos()
    assert [m["slot"] for m in merged["memos"]] == [m["slot"] for m in data["memos"]]
    assert merged["unwrite"] == 1

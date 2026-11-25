# unwrite 設計

unwrite は、AI が書いた論文草稿を**段落ごとのメモ**に砕き、
メモを TeX コメントとして入れた**原稿の骨組み**を別ディレクトリに作る道具である。
人間はメモだけを見て自分の文章で書く。メモは「書くための材料」としてだけ働き、
AI の言い回し・文の組み立て・修辞が人間の文章に移らないようにしつつ、論文に要る情報は落とさない。

対象は論文草稿（LaTeX、日本語・英語。Markdown は `split` で deck だけ作れる）。式・引用・数値が多いことを前提にする。

名前は、書かれた文章を「書く前」の状態（段落ごとの言いたいことと材料）に戻すことから。

**責務はフラグメント化だけ**（2026-11-25 改名・縮小）。前身の humpiler（human compiler）は
書いた後の照合（`check`）・カード盤の表示（`board` / `serve`）・命題カード方式も持っていたが、
使い勝手のために「草稿 → メモ入りの骨組み」までに絞った。書いた原稿の検査は unwrite の外で行う。

---

## 1. 何を壊し、何を残すか

| 層 | 例 | unwrite での扱い |
|---|---|---|
| 語・言い回し | 「重要な役割を果たす」、delve、三つ並べる癖 | メモに草稿の文を写さない（`memo.copy`）。決まり文句・評価語を警告する（`memo.eval`）。名詞句は分野の語彙なので原文のまま使ってよい |
| 文の組み立て | 段落の中の文の順、接続詞でつなぐ流れ | 段落を「言いたいこと・材料・流れ」に分解する。文の順はメモに残らない |
| 内容 | 主張・根拠・条件・数値・引用 | 残す。数値・引用キー・ラベル・式は **atoms** として原文から逐語で持つ |

**論文の構成（節・小節・段落の並び）は残す。** 構成は著者と相談して決めたもの（paperops の BRIEF の段落骨子）で、
AI の文体ではない。メモは段落（slot）ごとに作り、骨組みも草稿と同じ順に並ぶ。

## 2. 全体の流れ

### 2.0 paperops との関係（基本の運用）

paperops の project（`paper.toml`, `manuscript/`, `figures/`, `BRIEF.md`）を**下書き**とみなし、
メモ入りの原稿は別ディレクトリの **workspace** に作る。下書きの project には書き込まない。
出力先は `-o` で指定し、省略すると下書きの隣の `<paper>-fragments/` になる（下書きの中は拒否する）。

```
<ws>/unwrite.json      下書きの場所
<ws>/deck/                memos.json, skeleton.json, .sealed/（下書きの展開済み TeX と文分割, qa.json）
<ws>/manuscript/          main.tex・preamble.tex は複製、numbers.tex・refs.bib は下書きへの symlink、
                          sections/*.tex は骨組み（見出し・式・図はそのまま、段落はメモのコメント）
<ws>/figures ->           下書きの figures/ への symlink
```

- `numbers.tex` を symlink にするのは、解析をやり直したときの数値の更新を清書にもそのまま反映させるため。
  数値マクロ（`\floorPot{}` など）は atoms として扱い、メモでは値を表示し、⟨ ⟩ の中にマクロ名を置く。
- 式（display math）と図は骨組みにそのまま入れる（逐語であるべきもので、言い回しの問題が無い）。
  図の caption は文章なので空にし、どの段落のメモに材料があるかだけを書く。
- 骨組みはそのまま build できる（preamble・数値・文献・図が揃っている）。
- 入力は TeX を使う。PDF の文字層は数字や記号が欠ける（XeTeX の PDF で数字が抜けることを確認した）ため使わない。

```
paperops 草稿 ─► init ─► [LLM: 段落メモ] ─► lint ─► [LLM: QA 往復] ─► skeleton ─► 人間が書く
                  │          memos.json        ▲  └─────── 直す ──────┘
                  └─ 原文は .sealed/ に封印 ───┘
```

- unwrite 本体は **LLM を呼ばない**。決定的な処理（分割・封印・検査・骨組みの生成）だけを持つ。
- LLM の仕事（メモ作り・QA）は **対話的に** 行う。Claude Code の skill
  `skills/unwrite/SKILL.md` が手順を持ち、プロンプトは `prompts/` にある。repo 自体が Claude Code の plugin になっている。
- LLM が書いた `memos.json` は `unwrite lint` が機械的に検査し、通るまで LLM に直させる。
  「AI に AI らしくない文を書いてと頼む」のではなく、「規則を満たすまで差し戻す」構造にする。

### 2.1 段階

| 段階 | 担当 | 入力 → 出力 |
|---|---|---|
| `init` | unwrite | paperops の project → workspace、`.sealed/source.tex`, `.sealed/segments.json`（文 ID `s001`…、段落 slot） |
| メモ作り | LLM（対話） | `unwrite segments` の出力 → `memos.json`（大きければ部分ファイルを `merge`） |
| `lint` | unwrite | `memos.json` を schema・網羅・atoms・写し・評価語の観点で検査。QA の結果も表示 |
| QA 往復 | LLM（独立した 2 文脈） | 原文から作った質問に、`unwrite memos` だけを見た盲検の LLM が答えられるか |
| `skeleton` | unwrite | `manuscript/sections/*.tex` に骨組み（段落ごとにメモをコメントで） |
| 執筆 | 人間 | メモの下に自分の文で書く（ここから先は unwrite の外） |

paperops 以外の 1 ファイルなら `unwrite split draft.tex -o <deck>` で deck だけを作り、メモまで作れる
（workspace が無いので骨組みは作らない）。

## 3. 段落メモ（memos.json）

**経緯（2026-11-25）**: 最初は 1 命題 1 枚の電報体カードにしたが、圧縮しすぎて人間がカードを読んでも
内容が分からなかった。人間が書くために要るのは命題の断片ではなく、**段落ごとに何を言いたいか**と、
そのために入れる材料である。そこで単位を段落にし、普通の言葉で説明するメモに改めた（カード方式は削除した）。

段落（slot）ごとに 1 つのメモを作る。slot は `init` / `split` が決める（段落 ¶3、式や図の後の続きは ¶3b）。

```json
{"unwrite": 1,
 "memos": [
  {"slot": "2",
   "point": "この段落で読者に分かってほしいこと（1〜2 文）",
   "items": [{"text": "入れるべき事実・根拠・条件（メモ調、それだけで意味が分かる長さ）",
              "atoms": {"numbers": ["\\wallPot"], "refs": ["Zimmerman2016"], "eqs": [], "labels": []},
              "stance": "cited", "source": ["s007"]}],
   "role": "前後の段落とのつながり（何を受け、何を渡すか）",
   "source": ["s004", "s005", "s006", "s007", "s008"]}],
 "dropped": [{"source": ["s099"], "reason": "signpost"}]}
```

- `stance`: `asserted` 断定 / `hedged` ぼかし / `speculative` 推測 / `cited` 引用に依拠。原文の「〜と考えられる」はここに移す。
- `dropped`: 情報を持たない文。理由は `filler`（一般論・飾り）、`signpost`（「本節では〜」）、
  `restatement`（繰り返し）、`meta`（謝辞の定型など）。

| 規則 | 内容 | 水準 |
|---|---|---|
| 網羅 | 段落のすべての文がそのメモの source か dropped にある。図表の caption はどれかの材料の source にある | error |
| atoms | 段落の文に出る数値・数値マクロ・引用キー・ラベルは、その段落の材料の atoms に必ずある。atoms は草稿に実在する | error |
| dropped | 数値・引用・ラベルを含む文を dropped にしない | error |
| 写し（`memo.copy`） | 草稿と日本語 20 字・英語 10 語以上そのまま同じ並び（atoms を除く）を禁止。の・と だけでつながる名詞句は許す | error |
| 修辞（`memo.eval`） | 草稿の決まり文句・評価語（重要な役割、注目すべき、様々な、crucial…） | warn |
| 長さ | point 160 字、材料 90 字、流れ 120 字まで | warn |

メモは普通の文で書き、論理（〜なので、〜だが）も書いてよい。壊す対象は草稿の**文そのもの**（言い回し・
文の組み立て・決まり文句）で、内容と構成は残す。人間がメモから自分の文を組み立てることで、文体が人間のものになる。

**名詞句は言い換えさせない**。不自然な言い換えはそれ自体が AI の言い回しで、人間に移したくないものである。
名詞句は分野の語彙なので原文のまま残し、取り除くのは文の組み立て（述語・接続・修辞）に限る。

## 4. 骨組み（`unwrite skeleton`）

段落ごとにメモがコメントで入る。コメントなので PDF には出ず、原稿はそのまま build できる。

```tex
% ── ¶2 ──────────────────────────────
% [ ] ¶2 言いたいこと: 地形が表面帯電にどう効くかはまだ分かっておらず、本論文はクレーターの大きさとの関係を調べる。
%   材料:
%     - PIC 計算ではクレーターの壁が -50 V まで帯電した例がある（引用）   ⟨\wallPot{}=-50  \citep{Zimmerman2016}  引用[?]⟩
%   流れ: 序論の一段落。背景から問いまで。
```

- ⟨ ⟩ の中は逐語で使うもの（数値マクロは `\name{}=値`、式、引用、参照）。
- `[ ]`・`引用[?]` は書く人のための印で、unwrite は読まない（書き終えた段落や確かめた引用の目印に使う）。
- 一度書き出した section ファイルの hash を `deck/skeleton.json` に残し、人間が書き換えたファイルは
  `--force` なしでは上書きしない。

## 5. 情報を保つ仕組み

形を壊すほど情報は落ちやすい。そのため次の検査を重ねる。

1. **網羅**（lint, error）: 見出し以外のすべての文 ID が、どれかのメモの `source` か `dropped` にある。
2. **atoms の完全性**（lint, error）: 段落の文に現れる数値・数値マクロ・引用キー・ラベルは、その段落の材料の atoms にある。
3. **atoms の逐語性**（lint, error）: atoms の数値・引用キー・ラベル・式は草稿に実在する。
4. **QA 往復**（LLM, 独立文脈）: 原文を見る LLM が事実の質問と答えを作り（`.sealed/qa.json`）、
   **メモしか見ない**別の LLM 文脈（`unwrite memos`）がそれに答える。答えられない質問は情報の欠落なので、メモを直す。
   結果は `qa.json` に残り、lint が合格率を表示する。
5. **逆向き（混入）**: QA の採点時に、メモにあって原文にない主張がないかも確認する（作成時の幻覚対策）。

## 6. 封印について

- 原文と文分割は `<deck>/.sealed/` に置く。人間はここを開かない、という運用上の約束である。
  workspace の `.gitignore` に入れる。
- `unwrite segments` は原文を表示する唯一のコマンドで、LLM 側が使う。
- LLM はチャットに原文の文やメモの中身を書かない（人間がチャットを読むため）。件数と段落番号だけを報告する。

## 7. 構成

```
unwrite/
  unwrite/
    textutil.py   LaTeX を剥がした平文化、トークン化、数値・引用・ラベル・マクロ抽出
    texsrc.py     \input の展開（ファイル境界を保持）、数値マクロ、paper.toml
    segment.py    LaTeX / Markdown の文分割（見出し・数式・図表を別扱い、節・段落・slot・ファイルを記録）
    deck.py       deck ディレクトリの読み書き、語彙（stance / dropped の理由 / atoms の種類）
    memo.py       段落メモの正規化と表示（骨組みのコメント、盲検用テキスト）
    lint.py       メモの検査（schema・網羅・atoms・写し・評価語・QA）
    workspace.py  paperops から workspace への展開、原稿の骨組み
    cli.py        unwrite init / split / segments / lint / merge / memos / skeleton
  prompts/
    memo.md       段落メモの指示（LLM 用。規則は lint と一致させる）
    qa.md         QA 往復の指示
  skills/unwrite/SKILL.md   Claude Code で対話的に回す手順（plugin の skill）
  bin/unwrite               インストールせずに動かすラッパー（Python ≥ 3.9 を探す）
  .claude-plugin/           plugin.json と marketplace.json（repo 自体が plugin と marketplace）
  tests/
```

依存は Python 標準ライブラリだけ（Python ≥ 3.9）。

## 8. 今後

- 日本語の文分割・`memo.copy` の閾値をコーパスで調整する（AI 草稿と人間の論文で誤検出率を測る）。
- 下書き（paperops）が更新されたときに、メモと骨組みの差分を出す（どの段落が変わったか）。
- BRIEF.md の段落骨子をメモの `point` の手がかりとして使う。
- 複数の AI 草稿（版違い）から 1 つの deck を作る。

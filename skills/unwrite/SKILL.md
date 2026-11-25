---
name: unwrite
description: AI が書いた論文草稿（paperops の project。1 ファイルの .tex/.md も可）を unwrite で段落ごとのメモ（言いたいこと・材料・流れ）に砕き、メモをコメントで入れた原稿の骨組みを別ディレクトリ（workspace）に作る。人間はその骨組みに自分の文で書く。「unwrite して」「フラグメント化して」「清書用に展開して」「段落メモにして」で使う。書いた後の原稿の照合はこの skill の範囲外。
---

# unwrite

`<root>` はこの SKILL.md の 2 つ上のディレクトリ（plugin のルート。unwrite の repo そのもの）。
設計は `<root>/docs/design.md`、LLM 用の指示は `<root>/prompts/`。

以下の `unwrite ...` はすべて `<root>/bin/unwrite ...` で実行する（Python 3.9 以上を探して起動する。インストール不要。
`unwrite` が PATH にあればそのままでよい）。subagent に渡すときも `<root>` を絶対パスに展開して渡す。

## 守ること

- **チャットに原文の文やメモの中身を書かない。** 人間はチャットを読むので、AI の文面がそこから移る。
  報告は件数・節番号・段落番号・lint の数値だけにする。
- 原文を表示するのは `unwrite segments` だけ。`.sealed/` の中身を人間に見せない。
- paperops の project（下書き）には書き込まない。出力は別の workspace に作る。

## 1. 展開

```bash
unwrite init <paperops の project> [-o <workspace>]
```

`-o` を指定されなければ省略する（下書きの隣の `<project>-fragments/` になる）。
下書きの封印、原稿の複製、figures/numbers/refs への symlink が作られる。
paperops 以外の 1 ファイルなら `unwrite split draft.tex -o <deck>`（workspace は作られず、骨組みも作れない）。

## 2. 段落メモを作る

`<root>/prompts/memo.md` を読み、その規則で段落ごとのメモを作る（`<ws>/deck/memos.json`）。

- 内容の文が 80 程度までなら自分で作る: `unwrite segments <ws>` → `<ws>/deck/memos.json` → `unwrite lint <ws>`。
- それより大きければ節のまとまりごとに subagent に分ける（1 つ 50〜110 文が目安）。
  各 subagent に、担当節・部分ファイル `deck/memo-parts/part-X.json`・
  `unwrite lint <ws> --part <part> --section <N>` でエラー 0 にすること、報告に原文やメモを書かないことを渡す。
  終わったら `unwrite merge <ws> deck/memo-parts/*.json`。
- `unwrite lint <ws>` がエラー 0 になるまで直す。warn は判断する。

## 3. QA 往復

`<root>/prompts/qa.md` の手順で、出題（原文を見る subagent）と回答（`unwrite memos <ws>` だけを見る別の subagent）を分ける。
結果を `deck/.sealed/qa.json` に残し、不合格はメモを直す。lint の最後に合格率が出る（`-v` で info も表示）。

## 4. 骨組みを書いて渡す

```bash
unwrite skeleton <ws>    # 段落ごとにメモを TeX コメントで、見出し・式・図はそのまま
```

人間には workspace のパス、段落数、lint の結果、QA 合格率を伝える。人間は `manuscript/sections/*.tex` のメモの下に書く。
メモを直して骨組みを書き直すときは、人間が書き換えたファイルは上書きされない（`--force` は人間に確認してから）。

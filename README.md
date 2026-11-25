# unwrite

書かれた文章を書く前の状態に戻す。AI が書いた論文草稿を段落ごとのメモ（言いたいこと・材料・流れ）に砕き、
メモを TeX コメントで入れた原稿の骨組みを別ディレクトリに作る。人間はメモだけを見て自分の文章で書く。
設計は [docs/design.md](docs/design.md)。

## Claude Code の plugin として使う

```
/plugin marketplace add Nkzono99/unwrite
/plugin install unwrite@unwrite
```

入れたあとは「この草稿を unwrite して」（paperops の project のパスを添える）と頼むと、skill `unwrite` が
workspace の作成 → 段落メモ → lint → QA 往復 → 骨組みまでを進める。Python 3.9 以上があればよく、インストールは要らない。

## コマンドとして使う

```bash
bin/unwrite init <paperops の project> [-o <workspace>]   # 下書きを封印し workspace を作る（省略時 <project>-fragments）
# LLM が prompts/memo.md に沿って段落メモ <workspace>/deck/memos.json を作る
bin/unwrite lint <workspace>
bin/unwrite skeleton <workspace>   # manuscript/sections/*.tex に骨組み: 段落ごとにメモをコメントで
```

`bin/unwrite` は Python 3.9 以上を探して起動する（`UNWRITE_PYTHON` で指定できる）。`pip install -e .` すれば `unwrite` コマンドになる。

人間は `<workspace>/manuscript/sections/*.tex` のメモの下に書く。書いた原稿の照合は unwrite の範囲外。

依存は標準ライブラリだけ（Python ≥ 3.9）。テストは `python3.11 -m pytest`。

# このリポジトリについて

AI の村人が勝手に暮らす村のシミュレーション。概要と使い方は README.md を参照。

- 世界のルールは `sim/world.py`、村人の頭脳（Claude API のツール使用ループ）は `sim/brains.py`。
- `world/state.json` と `chronicle/` は実行結果。村の歴史そのものなので、勝手に消したり書き換えたりしない。
- 動作確認は `python3 run.py --mock` で API なしにできる。確認で生まれた `world/` と `chronicle/` は後で消すこと（本物の歴史と混ざるため）。
- ユーザーは村を「眺める」立場。村人の行動を Claude が直接書き換えてはいけない。

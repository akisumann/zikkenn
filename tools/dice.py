#!/usr/bin/env python3
"""TRPG 用ダイスローラー。

使い方:
    python3 tools/dice.py 2d6+3
    python3 tools/dice.py 2d6+2 --target 9 --label "見張りに気づかれずに忍び込む"
    python3 tools/dice.py 1d6+1 --label "剣のダメージ"
    python3 tools/dice.py 2d6 --secret --label "NPC の嘘を見抜けるか"

ロール結果はすべて logs/dice.log に追記される（出目の改ざん防止と振り返り用）。
"""

import argparse
import random
import re
import sys
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "dice.log"
TERM_RE = re.compile(r"([+-]?)(\d*)d(\d+)|([+-]?)(\d+)")


def parse_and_roll(expr):
    """'2d6+1d3-1' のような式を振り、(合計, 内訳文字列, 2d6の出目 or None) を返す。"""
    s = expr.replace(" ", "").lower()
    if not s:
        raise ValueError("式が空です")
    pos = 0
    total = 0
    parts = []
    dice_groups = []
    while pos < len(s):
        m = TERM_RE.match(s, pos)
        if not m or m.end() == pos:
            raise ValueError(f"式を解釈できません: {expr!r}")
        if pos > 0 and not (m.group(1) or m.group(4)):
            raise ValueError(f"項の間に + か - が必要です: {expr!r}")
        if m.group(3):
            sign = -1 if m.group(1) == "-" else 1
            count = int(m.group(2) or 1)
            sides = int(m.group(3))
            if not (1 <= count <= 100 and 2 <= sides <= 1000):
                raise ValueError(f"ダイスの数か面数が範囲外です: {m.group(0)}")
            rolls = [random.randint(1, sides) for _ in range(count)]
            total += sign * sum(rolls)
            parts.append(f"{'-' if sign < 0 else '+'}{count}d{sides}{rolls}")
            dice_groups.append((count, sides, rolls))
        else:
            sign = -1 if m.group(4) == "-" else 1
            value = int(m.group(5))
            total += sign * value
            parts.append(f"{'-' if sign < 0 else '+'}{value}")
        pos = m.end()
    breakdown = " ".join(parts).lstrip("+")
    # クリティカル/ファンブル判定は先頭が 2d6 のときだけ行う
    natural = None
    if dice_groups and dice_groups[0][:2] == (2, 6) and not s.startswith("-"):
        natural = dice_groups[0][2]
    return total, breakdown, natural


def judge(total, natural, target):
    if natural == [6, 6]:
        return "クリティカル！（自動成功）"
    if natural == [1, 1]:
        return "ファンブル…（自動失敗）"
    if target is None:
        return None
    if total >= target:
        return "成功"
    if target - total <= 2:
        return f"失敗（あと {target - total}：代償付き成功を提案できる）"
    return "失敗"


def main():
    parser = argparse.ArgumentParser(description="TRPG 用ダイスローラー")
    parser.add_argument("expr", help="ダイス式（例: 2d6+3, 1d6+1, 2d6-1）")
    parser.add_argument("-t", "--target", type=int, help="目標値（指定すると成否を判定）")
    parser.add_argument("-l", "--label", default="", help="何の判定か")
    parser.add_argument("-s", "--secret", action="store_true",
                        help="GM のシークレットダイス（ログには [秘] と記録）")
    args = parser.parse_args()

    try:
        total, breakdown, natural = parse_and_roll(args.expr)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    result = judge(total, natural, args.target)
    line = f"{args.expr} → {breakdown} = {total}"
    if args.target is not None:
        line += f" (目標値 {args.target})"
    if result:
        line += f" ⇒ {result}"
    if args.label:
        line = f"《{args.label}》 {line}"
    if args.secret:
        line = f"[秘] {line}"

    print(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")


if __name__ == "__main__":
    main()

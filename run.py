#!/usr/bin/env python3
"""村の時間を進める。

    python3 run.py              # 2 時間（1 ティック）進める
    python3 run.py --ticks 8    # 1 日ぶん進める
    python3 run.py --days 3     # 3 日ぶん進める
    python3 run.py --mock       # API を使わずに動作確認（村人はランダムに動く）
    python3 run.py --reset      # 世界を初期状態に戻す

進めた結果は world/state.json に保存され、次回はその続きから始まる。
観察記録は chronicle/day-NNN.md に書かれる。
"""

import argparse
import random
import shutil

from sim.brains import ClaudeBrain, MockBrain
from sim.world import CHRONICLE_DIR, DAY_HOURS, STATE_PATH, World


def main():
    parser = argparse.ArgumentParser(description="勝手に生きている村を進める")
    parser.add_argument("--ticks", type=int, default=1, help="進めるティック数（1 ティック = 2 時間）")
    parser.add_argument("--days", type=int, help="進める日数（--ticks より優先）")
    parser.add_argument("--mock", action="store_true", help="API を使わずにランダムに動かす")
    parser.add_argument("--reset", action="store_true", help="世界と年代記を初期状態に戻す")
    args = parser.parse_args()

    if args.reset:
        STATE_PATH.unlink(missing_ok=True)
        shutil.rmtree(CHRONICLE_DIR, ignore_errors=True)
        print("世界を初期状態に戻した。")

    world = World.load()
    brain = MockBrain() if args.mock else ClaudeBrain()
    ticks = args.days * len(DAY_HOURS) if args.days else args.ticks

    for _ in range(ticks):
        print(f"\n## {world.clock()}（{world.data['weather']}）")
        order = list(world.villagers)
        random.shuffle(order)  # 毎回動く順番を変える。後の人は前の人の言動に反応できる
        for name in order:
            brain.take_turn(world, name)
            world.end_turn(name)
            world.save()  # 途中で止まっても、そこまでは残る
        world.advance()
        world.save()

    print(f"\n— いまは {world.clock()}（{world.data['weather']}）—")


if __name__ == "__main__":
    main()

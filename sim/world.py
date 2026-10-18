"""村の状態と、村人が行う行動のルール。

AI とは無関係の「物理法則」だけをここに書く。
村人が何をするかは brains.py が決め、ここはその結果を世界に反映するだけ。
"""

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_PATH = ROOT / "seed" / "village.json"
STATE_PATH = ROOT / "world" / "state.json"
CHRONICLE_DIR = ROOT / "chronicle"

DAY_HOURS = [6, 8, 10, 12, 14, 16, 18, 20]  # 1 ティック = 2 時間。22 時〜翌 6 時は全員眠る
FOOD = {"パン": 4, "魚": 3, "野菜": 2}  # 食べると減る空腹度
WEATHERS = [("晴れ", 5), ("曇り", 3), ("雨", 2), ("霧", 1), ("嵐", 0.5)]
MAX_MEMORIES = 40
MAX_INBOX = 30


class World:
    def __init__(self, data):
        self.data = data

    # ---------- 保存と読み込み ----------

    @classmethod
    def load(cls):
        if STATE_PATH.exists():
            return cls(json.loads(STATE_PATH.read_text(encoding="utf-8")))
        return cls.from_seed()

    @classmethod
    def from_seed(cls):
        seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
        villagers = {}
        for v in seed["villagers"]:
            villagers[v["name"]] = {
                **v,
                "location": v["home"],
                "hunger": 3,
                "energy": 10,
                "activity": "目を覚ましたところ",
                "memories": [],
                "inbox": [],
                "impressions": {k: {"score": s, "note": n} for k, (s, n) in v["impressions"].items()},
            }
        data = {
            "name": seed["name"],
            "description": seed["description"],
            "places": seed["places"],
            "day": 1,
            "hour_index": 0,
            "weather": "晴れ",
            "villagers": villagers,
        }
        return cls(data)

    def save(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------- 基本情報 ----------

    @property
    def villagers(self):
        return self.data["villagers"]

    @property
    def hour(self):
        return DAY_HOURS[self.data["hour_index"]]

    def clock(self):
        return f"{self.data['day']}日目 {self.hour:02d}:00"

    def people_at(self, place, exclude=None):
        return [n for n, v in self.villagers.items() if v["location"] == place and n != exclude]

    # ---------- 記録 ----------

    def log(self, text):
        """年代記（観察者向けの全記録）に 1 行追記する。"""
        line = f"- `{self.hour:02d}:00` {text}"
        print(line)
        CHRONICLE_DIR.mkdir(parents=True, exist_ok=True)
        path = CHRONICLE_DIR / f"day-{self.data['day']:03d}.md"
        if not path.exists():
            path.write_text(f"# {self.data['name']} {self.data['day']}日目（{self.data['weather']}）\n\n",
                            encoding="utf-8")
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def broadcast(self, place, text, exclude=None):
        """その場にいる村人の耳と目に、出来事を届ける。"""
        for name in self.people_at(place, exclude=exclude):
            inbox = self.villagers[name]["inbox"]
            inbox.append(f"{self.hour:02d}:00 {place}: {text}")
            del inbox[:-MAX_INBOX]

    # ---------- 村人の知覚 ----------

    def perceive(self, name):
        """村人 name が「いま」感じ取れることを文章にする。AI への入力になる。"""
        v = self.villagers[name]
        here = v["location"]
        others = self.people_at(here, exclude=name)
        lines = [
            f"【いま】{self.clock()}（天気：{self.data['weather']}）",
            f"【居場所】{here} — {self.data['places'][here]}",
        ]
        if others:
            lines.append("【ここにいる人】" + "、".join(
                f"{o}（{self.villagers[o]['activity']}）" for o in others))
        else:
            lines.append("【ここにいる人】誰もいない")
        lines.append(f"【体】空腹 {v['hunger']}/10、元気 {v['energy']}/10"
                     + ("（とても空腹だ）" if v["hunger"] >= 8 else "")
                     + ("（くたくただ）" if v["energy"] <= 2 else ""))
        inv = "、".join(f"{k}×{n}" for k, n in v["inventory"].items() if n > 0) or "なし"
        lines.append(f"【持ち物】{inv}、銀貨 {v['money']} 枚")
        lines.append("【前の行動から今までに見聞きしたこと】")
        lines += [f"- {e}" for e in v["inbox"]] or ["- 特になし"]
        lines.append("【あなたの記憶メモ（古い順）】")
        lines += [f"- {m}" for m in v["memories"][-15:]] or ["- まだない"]
        lines.append("【人への印象】（-5 嫌い 〜 +5 好き）")
        lines += [f"- {k}: {i['score']:+d} {i['note']}" for k, i in v["impressions"].items()] or ["- なし"]
        others_far = [f"{n}" for n in self.villagers if n != name and n not in others]
        lines.append("【村の場所】" + "、".join(self.data["places"]))
        lines.append("【ほかの村人】" + "、".join(others_far))
        return "\n".join(lines)

    # ---------- 行動（ターンを消費する） ----------

    def act_move(self, name, destination):
        v = self.villagers[name]
        if destination not in self.data["places"]:
            return f"「{destination}」という場所はない。行ける場所: " + "、".join(self.data["places"])
        if destination == v["location"]:
            return "もうそこにいる。"
        src = v["location"]
        self.broadcast(src, f"{name}が{destination}へ向かった。", exclude=name)
        v["location"] = destination
        v["activity"] = "やって来たところ"
        self.broadcast(destination, f"{name}がやって来た。", exclude=name)
        self.log(f"🚶 **{name}** {src} → {destination}")
        return f"{destination}に着いた。"

    def act_say(self, name, to, message):
        v = self.villagers[name]
        here = v["location"]
        present = self.people_at(here, exclude=name)
        if to not in ("みんな", "ひとりごと") and to not in present:
            return f"{to}はここにいない。ここにいるのは: " + ("、".join(present) or "誰もいない")
        target = "" if to in ("みんな", "ひとりごと") else f"→{to}"
        v["activity"] = f"{to}と話している" if target else "話している"
        self.broadcast(here, f"{name}{target}「{message}」", exclude=name)
        self.log(f"💬 **{name}**{target}（{here}）「{message}」")
        return "言った。" if present else "誰もいないので、声は風に消えた。"

    def act_work(self, name):
        v = self.villagers[name]
        if v["location"] != v["workplace"]:
            return f"仕事は{v['workplace']}でしかできない。"
        if v["energy"] <= 1:
            return "疲れすぎて働けない。"
        gained = []
        for item, n in v["produce"].items():
            if self.data["weather"] in ("雨", "嵐") and v["workplace"] in ("畑", "川辺", "森の入口"):
                n = max(1, n // 2)
            if item == "銀貨":
                v["money"] += n
            else:
                v["inventory"][item] = v["inventory"].get(item, 0) + n
            gained.append(f"{item}×{n}")
        v["energy"] = max(0, v["energy"] - 2)
        v["activity"] = f"{v['job']}の仕事をしている"
        self.broadcast(v["location"], f"{name}が仕事をしている。", exclude=name)
        self.log(f"🔨 **{name}** 働いた（{'、'.join(gained)}）")
        return f"働いて {'、'.join(gained)} を得た。"

    def act_eat(self, name, item):
        v = self.villagers[name]
        if item not in FOOD:
            return f"{item}は食べられない。食べられるもの: " + "、".join(FOOD)
        if v["inventory"].get(item, 0) <= 0:
            return f"{item}を持っていない。"
        v["inventory"][item] -= 1
        v["hunger"] = max(0, v["hunger"] - FOOD[item])
        v["activity"] = f"{item}を食べている"
        self.broadcast(v["location"], f"{name}が{item}を食べている。", exclude=name)
        self.log(f"🍞 **{name}** {item}を食べた")
        return f"{item}を食べた。空腹 {v['hunger']}/10。"

    def act_give(self, name, to, item, amount):
        v = self.villagers[name]
        if to not in self.people_at(v["location"], exclude=name):
            return f"{to}はここにいない。"
        if amount <= 0:
            return "1 以上を渡すこと。"
        if item == "銀貨":
            if v["money"] < amount:
                return f"銀貨が足りない（{v['money']} 枚）。"
            v["money"] -= amount
            self.villagers[to]["money"] += amount
        else:
            if v["inventory"].get(item, 0) < amount:
                return f"{item}が足りない。"
            v["inventory"][item] -= amount
            inv = self.villagers[to]["inventory"]
            inv[item] = inv.get(item, 0) + amount
        v["activity"] = f"{to}に何かを渡している"
        self.broadcast(v["location"], f"{name}が{to}に{item}を{amount}つ渡した。", exclude=name)
        self.log(f"🎁 **{name}** → {to}：{item}×{amount}")
        return f"{to}に{item}を{amount}つ渡した。"

    def act_rest(self, name):
        v = self.villagers[name]
        v["energy"] = min(10, v["energy"] + 3)
        v["activity"] = "休んでいる"
        self.log(f"💤 **{name}** 休んだ（{v['location']}）")
        return f"休んだ。元気 {v['energy']}/10。"

    def act_do(self, name, activity):
        v = self.villagers[name]
        v["activity"] = activity
        self.broadcast(v["location"], f"{name}は{activity}", exclude=name)
        self.log(f"✨ **{name}**（{v['location']}）{activity}")
        return "した。"

    # ---------- 内面（ターンを消費しない） ----------

    def remember(self, name, note):
        mem = self.villagers[name]["memories"]
        mem.append(f"[{self.clock()}] {note}")
        del mem[:-MAX_MEMORIES]
        self.log(f"💭 *{name}の心のメモ：{note}*")
        return "覚えた。"

    def update_impression(self, name, target, change, note):
        if target not in self.villagers or target == name:
            return f"{target}という村人はいない。"
        change = max(-2, min(2, change))
        imp = self.villagers[name]["impressions"].setdefault(target, {"score": 0, "note": ""})
        imp["score"] = max(-5, min(5, imp["score"] + change))
        imp["note"] = note
        self.log(f"💭 *{name}→{target} の印象 {change:+d}（{imp['score']:+d}）：{note}*")
        return f"{target}への印象は {imp['score']:+d} になった。"

    # ---------- 時間の流れ ----------

    def end_turn(self, name):
        self.villagers[name]["inbox"] = []

    def advance(self):
        """全員が動き終えたあと、時間を 2 時間進める。夜なら眠って翌日へ。"""
        for v in self.villagers.values():
            v["hunger"] = min(10, v["hunger"] + 1)
            v["energy"] = max(0, v["energy"] - 1)
        if self.data["hour_index"] + 1 < len(DAY_HOURS):
            self.data["hour_index"] += 1
            return False
        # 夜：全員家に帰って眠る
        self.log("🌙 夜が来た。村人たちはそれぞれの家で眠りについた。")
        for name, v in self.villagers.items():
            v["location"] = v["home"]
            v["energy"] = 10
            v["activity"] = "目を覚ましたところ"
            v["inbox"].append("夜のあいだ、ぐっすり眠った。")
        self.data["day"] += 1
        self.data["hour_index"] = 0
        self.data["weather"] = random.choices([w for w, _ in WEATHERS], [p for _, p in WEATHERS])[0]
        return True

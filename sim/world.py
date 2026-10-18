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
FOOD = {"シチュー": 5, "パン": 4, "肉": 4, "魚": 3, "野菜": 2, "山菜": 2}  # 食べると減る空腹度
PRICES = {"シチュー": 3, "パン": 2, "肉": 3, "魚": 3, "野菜": 1, "山菜": 1, "薬草": 3, "エール": 2, "薪": 1}  # 村の相場（銀貨）
TONICS = {"薬草": 3, "エール": 1}  # 口にすると元気が戻るもの
KEEP_FOOD = 2  # 自分用に残しておく食べ物の数。これを超えた分なら売ってもいい
WEATHERS = [("晴れ", 5), ("曇り", 3), ("雨", 2), ("霧", 1), ("嵐", 0.5)]
MAX_MEMORIES = 40
MAX_INBOX = 30
MAX_RUMORS = 10


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

    def broadcast(self, place, text, exclude=None, kind="see", actor=None, to=None, quote=None):
        """その場にいる村人の耳と目に、出来事を届ける。"""
        event = {"t": f"{self.hour:02d}:00 {place}: {text}", "kind": kind,
                 "actor": actor, "to": to, "quote": quote}
        for name in self.people_at(place, exclude=exclude):
            inbox = self.villagers[name]["inbox"]
            inbox.append(event)
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
        lines += [f"- {e['t']}" for e in v["inbox"]] or ["- 特になし"]
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
        self.broadcast(here, f"{name}{target}「{message}」", exclude=name,
                       kind="say", actor=name, to=to, quote=message)
        self.log(f"💬 **{name}**{target}（{here}）「{message}」")
        return "言った。" if present else "誰もいないので、声は風に消えた。"

    def act_work(self, name):
        v = self.villagers[name]
        if v["location"] != v["workplace"]:
            return f"仕事は{v['workplace']}でしかできない。"
        if v["energy"] <= 1:
            return "疲れすぎて働けない。"
        lacking = [i for i, n in v.get("needs", {}).items() if v["inventory"].get(i, 0) < n]
        if lacking:
            return f"仕事に使う{'、'.join(lacking)}が足りない。"
        for i, n in v.get("needs", {}).items():
            v["inventory"][i] -= n
        gained = []
        for item, n in v["produce"].items():
            if self.data["weather"] in ("雨", "嵐") and v["workplace"] in ("畑", "川辺", "森の入口"):
                n = max(1, n // 2)
            if item == "銀貨":
                v["money"] += n
            else:
                v["inventory"][item] = v["inventory"].get(item, 0) + n
            gained.append(f"{item}×{n}")
        v["energy"] = max(0, v["energy"] - 1)
        v["activity"] = f"{v['job']}の仕事をしている"
        self.broadcast(v["location"], f"{name}が仕事をしている。", exclude=name)
        self.log(f"🔨 **{name}** 働いた（{'、'.join(gained)}）")
        return f"働いて {'、'.join(gained)} を得た。"

    def act_eat(self, name, item):
        v = self.villagers[name]
        if item in TONICS and v["inventory"].get(item, 0) > 0:
            v["inventory"][item] -= 1
            v["energy"] = min(10, v["energy"] + TONICS[item])
            v["activity"] = f"{item}を口にしている"
            self.log(f"🌿 **{name}** {item}を口にした")
            return f"{item}を口にした。元気 {v['energy']}/10。"
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
        self.broadcast(v["location"], f"{name}が{to}に{item}を{amount}つ渡した。", exclude=name,
                       kind="give", actor=name, to=to, quote=item)
        self.log(f"🎁 **{name}** → {to}：{item}×{amount}")
        return f"{to}に{item}を{amount}つ渡した。"

    def surplus(self, name, item):
        """name が売ってもいい item の数。"""
        have = self.villagers[name]["inventory"].get(item, 0)
        return have - KEEP_FOOD if item in FOOD else have

    def will_sell(self, seller, buyer, item):
        """村の決まり：余っていて、相手をひどく嫌っていなければ、相場で売る。"""
        imp = self.villagers[seller]["impressions"].get(buyer, {"score": 0})["score"]
        return self.surplus(seller, item) > 0 and imp >= -2

    def will_buy(self, buyer, item):
        """村の決まり：食費（銀貨 4 枚）を残して払えて、手元に少ないなら買う。"""
        v = self.villagers[buyer]
        if item == "エール":  # エールは日暮れの酒場で、懐に余裕があれば何杯でも
            return v["location"] == "酒場" and self.hour >= 16 and v["money"] >= 4
        return v["money"] - PRICES.get(item, 99) >= 4 and v["inventory"].get(item, 0) < 2

    def act_sell(self, name, buyer, item):
        v = self.villagers[name]
        if buyer not in self.people_at(v["location"], exclude=name):
            return f"{buyer}はここにいない。"
        if item not in PRICES or v["inventory"].get(item, 0) <= 0:
            return f"{item}を持っていない。"
        if not self.will_buy(buyer, item):
            v["activity"] = f"{buyer}に{item}を売り込んでいる"
            self.log(f"🙅 **{buyer}** は **{name}** の{item}を買わなかった")
            return f"{buyer}には要らないと言われた。"
        price = PRICES[item]
        v["inventory"][item] -= 1
        v["money"] += price
        self.villagers[buyer]["money"] -= price
        if item == "エール":
            b = self.villagers[buyer]
            b["energy"] = min(10, b["energy"] + TONICS["エール"])
            self.broadcast(v["location"], f"{name}が{buyer}にエールを注ぎ、{buyer}が飲み干した。", exclude=name,
                           kind="trade", actor=name, to=buyer, quote=item)
            self.log(f"🍺 **{name}** が **{buyer}** にエールを注いだ（銀貨{price}枚）")
            return f"{buyer}にエールを売った。"
        inv = self.villagers[buyer]["inventory"]
        inv[item] = inv.get(item, 0) + 1
        v["activity"] = f"{buyer}に{item}を売っている"
        self.broadcast(v["location"], f"{name}が{buyer}に{item}を売った。", exclude=name,
                       kind="trade", actor=name, to=buyer, quote=item)
        self.log(f"💰 **{name}** は **{buyer}** に{item}を銀貨{price}枚で売った")
        return f"{buyer}に{item}を銀貨{price}枚で売った。"

    def act_buy(self, name, seller, item, amount):
        v = self.villagers[name]
        if seller not in self.people_at(v["location"], exclude=name):
            return f"{seller}はここにいない。"
        if item not in PRICES:
            return f"{item}は売り買いできない。相場: " + "、".join(f"{k} {p}枚" for k, p in PRICES.items())
        amount = max(1, amount)
        price = PRICES[item] * amount
        if v["money"] < price:
            return f"銀貨が足りない（{price} 枚必要、手持ち {v['money']} 枚）。"
        if not self.will_sell(seller, name, item) or self.surplus(seller, item) < amount:
            v["activity"] = f"{seller}に{item}を売ってくれと頼んでいる"
            self.broadcast(v["location"], f"{name}が{seller}に{item}を売ってくれと頼んだが、断られた。",
                           exclude=name, kind="refuse", actor=name, to=seller, quote=item)
            self.log(f"🙅 **{seller}** は **{name}** に{item}を売らなかった")
            return f"{seller}に断られた。"
        v["money"] -= price
        self.villagers[seller]["money"] += price
        self.villagers[seller]["inventory"][item] -= amount
        if item == "エール":  # エールはその場で飲む
            v["energy"] = min(10, v["energy"] + TONICS["エール"] * amount)
            self.broadcast(v["location"], f"{name}が{seller}からエールを買って飲み干した。", exclude=name,
                           kind="trade", actor=name, to=seller, quote=item)
            self.log(f"🍺 **{name}** は **{seller}** からエールを買って飲み干した")
            return f"{seller}からエールを買って飲み干した。"
        v["inventory"][item] = v["inventory"].get(item, 0) + amount
        v["activity"] = f"{seller}から{item}を買っている"
        self.broadcast(v["location"], f"{name}が{seller}から{item}を{amount}つ買った。", exclude=name,
                       kind="trade", actor=name, to=seller, quote=item)
        self.log(f"💰 **{name}** は **{seller}** から{item}×{amount}を銀貨{price}枚で買った")
        return f"{seller}から{item}を{amount}つ、銀貨{price}枚で買った。"

    def act_rest(self, name):
        v = self.villagers[name]
        v["energy"] = min(10, v["energy"] + 3)
        v["activity"] = "休んでいる"
        self.log(f"💤 **{name}** 休んだ（{v['location']}）")
        return f"休んだ。元気 {v['energy']}/10。"

    def act_do(self, name, activity):
        v = self.villagers[name]
        v["activity"] = activity
        self.broadcast(v["location"], f"{name}は{activity}", exclude=name, actor=name)
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
        """ターンの終わりに、見聞きしたことを忘れる。ただし人のセリフは噂として少しのあいだ覚えている。"""
        v = self.villagers[name]
        rumors = v.setdefault("rumors", [])
        rumors += [e for e in v["inbox"] if e["kind"] == "say" and e["actor"] != name]
        del rumors[:-MAX_RUMORS]
        v["inbox"] = []

    def advance(self):
        """全員が動き終えたあと、時間を 2 時間進める。夜なら眠って翌日へ。"""
        if self.data["hour_index"] % 2 == 1:  # 4 時間ごとに腹が減り、疲れる
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
            v["hunger"] = min(10, v["hunger"] + 1)
            v["activity"] = "目を覚ましたところ"
            if v["inventory"].get("薪", 0) > 0:  # 薪があれば暖かく眠れる
                v["inventory"]["薪"] -= 1
                v["energy"] = 10
                night = "夜のあいだ、薪を燃やして暖かく眠った。"
            else:
                v["energy"] = 8
                night = "薪がなく、夜の冷え込みであまり眠れなかった。"
            v["inbox"].append({"t": night, "kind": "sleep", "actor": None, "to": None, "quote": None})
        self.data["day"] += 1
        self.data["hour_index"] = 0
        self.data["weather"] = random.choices([w for w, _ in WEATHERS], [p for _, p in WEATHERS])[0]
        return True

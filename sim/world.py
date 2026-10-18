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
# 村の需要は「食べる」と「暖を取る」の二つだけ。品物はすべてそこから逆算する（README の「経済の設計」）。
#   食材（麦・魚・肉）─┐
#                       ├→ 加工（パン屋・酒場の台所）→ 食事（パン・料理）
#   薪 ────────────────┤
#                       └→ 夜の暖（一家に 1 本）
MEALS = {"料理": 5, "サンドイッチ": 5, "パン": 3}  # 店で作る食事。食べると減る空腹度
INGREDIENTS = {"麦": "麦粥", "魚": "焼き魚", "肉": "焼き肉"}  # 食材。生では食べず、家で薪を使って煮炊きする
HOME_MEAL = 4  # 家で煮炊きした食事で減る空腹度。薪 1 本で 1 人前なので、店より薪を食う
FOOD = dict(MEALS)
CATEGORIES = {"食材": list(INGREDIENTS)}  # 仕事の材料に「どれでもいい」を指定するための分類
PRICES = {"料理": 25, "サンドイッチ": 34, "パン": 24, "麦": 26, "魚": 30, "肉": 28, "薪": 12}  # 村の相場（銀貨）。売り手の収支を見て自動で詰めた値
HELP_JOBS = {"畑": {"麦": 1}, "川辺": {"魚": 1}, "森の入口": {"薪": 1}}  # 誰でもできる手伝い仕事（本業より実入りは少ない）
# これだけ売れ残ったら「余っている」と感じる（村で 1〜2 日分の備蓄の目安）
RESERVE = {"麦": 8, "魚": 4, "肉": 4, "薪": 8, "パン": 8, "サンドイッチ": 6, "料理": 6}
WOOD_STORE = 5  # 薪は傷まないので、懐に余裕があれば一家で何晩分か貯めておく
ASSEMBLY_PLACE = "広場"  # 毎朝 6 時、全員がここに集まって朝礼をする
NEWS_DAYS = 2  # 聞いた村の様子を当てにする日数
SAY_STATE = {"不足": "足りない", "余り": "余っている"}
KEEP = {"料理": 2, "サンドイッチ": 2, "パン": 2, "麦": 1, "魚": 1, "肉": 1, "薪": 1}  # 自分用に残す数。超えた分なら売る
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
                "known": {},  # 聞いたり見たりした村の様子 {品物: [不足/余り, 日, 誰から]}
                "impressions": {k: {"score": s, "note": n} for k, (s, n) in v["impressions"].items()},
            }
        data = {
            "name": seed["name"],
            "description": seed["description"],
            "places": seed["places"],
            "zones": {place: zone for zone, places in seed["zones"].items() for place in places},
            "day": 1,
            "hour_index": 0,
            "weather": "晴れ",
            "villagers": villagers,
        }
        world = cls(data)
        world.morning_assembly()
        return world

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

    @property
    def tick(self):
        return self.data["day"] * len(DAY_HOURS) + self.data["hour_index"]

    def travel_turns(self, a, b):
        """移動にかかるターン数。同じ区画どうしか中心との行き来は 1（2 時間）、外れどうしは 2（4 時間）。"""
        za, zb = self.data["zones"].get(a), self.data["zones"].get(b)
        return 1 if za == zb or "中心" in (za, zb) else 2

    def continue_travel(self, name):
        """遠出の途中なら、このターンは歩き続けて目的地に着く。歩いていたら True。"""
        v = self.villagers[name]
        travel = v.pop("travel", None)
        if not travel:
            return False
        v["location"] = travel["to"]
        v["activity"] = "やって来たところ"
        self.broadcast(travel["to"], f"{name}がやって来た。", exclude=name)
        self.log(f"🚶 **{name}** {travel['to']}に着いた")
        return True

    def price(self, item):
        return PRICES.get(item)

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
            f"【居場所】{here} — {self.data['places'].get(here, '')}",
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
        lines.append(f"【村の相場】{self.price_list()}")
        news = self.recent_news(name)
        if news:
            lines.append("【知っている村の様子】" + "、".join(
                f"{item}が{SAY_STATE[state]}（{src}）" for item, (state, _, src) in news.items()))
        lines.append("【前の行動から今までに見聞きしたこと】")
        lines += [f"- {e['t']}" for e in v["inbox"]] or ["- 特になし"]
        lines.append("【あなたの記憶メモ（古い順）】")
        lines += [f"- {m}" for m in v["memories"][-15:]] or ["- まだない"]
        lines.append("【人への印象】（-5 嫌い 〜 +5 好き）")
        lines += [f"- {k}: {i['score']:+d} {i['note']}" for k, i in v["impressions"].items()] or ["- なし"]
        others_far = [f"{n}" for n in self.villagers if n != name and n not in others]
        lines.append("【村の場所】" + "、".join(
            f"{p}（{'2' if self.travel_turns(here, p) == 1 else '4'}時間）" for p in self.data["places"] if p != here))
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
        if self.travel_turns(src, destination) == 2:  # 遠出：次のターンも歩いて、着くのはその後
            v["location"] = "道中"
            v["travel"] = {"to": destination}
            v["activity"] = f"{destination}へ向かって歩いている"
            self.log(f"🚶 **{name}** {src} → {destination}（遠いので 4 時間かかる）")
            return f"{destination}へ向かって歩いている。着くのは次の時間だ。"
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
        for listener in present:
            self.share_news(name, listener)
        return "言った。" if present else "誰もいないので、声は風に消えた。"

    def act_work(self, name):
        v = self.villagers[name]
        if v["energy"] <= 1:
            return "疲れすぎて働けない。"
        if v["location"] != v["workplace"]:
            if v["location"] not in HELP_JOBS:
                return f"仕事は{v['workplace']}でしかできない（手伝いなら{'・'.join(HELP_JOBS)}でできる）。"
            return self._help(name)
        recipe = next((r for r in self.recipes(name) if not self._missing(name, r["needs"])), None)
        if recipe is None:
            lacking = self.lacking(name)
            for need in lacking:
                for item in self._members(need):
                    self.note(name, item, "不足")
            return f"仕事に使う{'、'.join(lacking)}が足りない。"
        for need, n in recipe["needs"].items():
            for _ in range(n):
                item = max(self._members(need), key=lambda i: v["inventory"].get(i, 0))
                v["inventory"][item] -= 1
        bonus = self._streak(name)
        gained = []
        for item, n in recipe["produce"].items():
            if self.data["weather"] in ("雨", "嵐") and v["workplace"] in ("畑", "川辺", "森の入口"):
                n = max(1, n // 2)
            n += bonus
            v["inventory"][item] = v["inventory"].get(item, 0) + n
            gained.append(f"{item}×{n}")
            if self.surplus(name, item) >= RESERVE.get(item, 99):
                self.note(name, item, "余り")
        v["energy"] = max(0, v["energy"] - 1)
        v["activity"] = f"{v['job']}の仕事をしている"
        self.broadcast(v["location"], f"{name}が仕事をしている。", exclude=name)
        self.log(f"🔨 **{name}** 働いた（{'、'.join(gained)}）" + ("　続けて働いてはかどった" if bonus else ""))
        return f"働いて {'、'.join(gained)} を得た。" + ("続けて働いたのではかどった。" if bonus else "")

    def _streak(self, name):
        """同じ仕事場で続けて働くと、段取りがよくなって実入りが 1 増える。"""
        v = self.villagers[name]
        bonus = 1 if v.get("last_work") == [v["location"], self.tick - 1] else 0
        v["last_work"] = [v["location"], self.tick]
        return bonus

    def _help(self, name):
        v = self.villagers[name]
        place = v["location"]
        bonus = self._streak(name)
        gained = []
        for item, n in HELP_JOBS[place].items():
            n += bonus
            v["inventory"][item] = v["inventory"].get(item, 0) + n
            gained.append(f"{item}×{n}")
        v["energy"] = max(0, v["energy"] - 1)
        v["activity"] = f"{place}で手伝い仕事をしている"
        self.broadcast(place, f"{name}が手伝い仕事をしている。", exclude=name)
        self.log(f"🤝 **{name}** {place}で手伝った（{'、'.join(gained)}）" + ("　続けて働いてはかどった" if bonus else ""))
        return f"手伝って {'、'.join(gained)} を得た。" + ("続けて働いたのではかどった。" if bonus else "")

    # ---------- 村の様子のうわさ ----------

    def note(self, name, item, state, source="自分で見た"):
        self.villagers[name].setdefault("known", {})[item] = [state, self.data["day"], source]

    def recent_news(self, name):
        known = self.villagers[name].get("known", {})
        return {i: k for i, k in known.items() if self.data["day"] - k[1] < NEWS_DAYS}

    def share_news(self, speaker, listener):
        """話をすると、相手の知っている村の様子が伝わる（新しい話だけ）。"""
        learned = []
        mine = self.villagers[listener].setdefault("known", {})
        for item, (state, day, src) in self.recent_news(speaker).items():
            if item not in mine or mine[item][1] < day or (mine[item][1] == day and mine[item][0] != state):
                mine[item] = [state, day, f"{speaker}から聞いた"]
                learned.append(f"{item}が{SAY_STATE[state]}")
        if learned:
            self.log(f"📣 *{listener}は{speaker}から聞いた：{'、'.join(learned)}*")

    def price_list(self):
        return "、".join(f"{k} {p}枚" for k, p in PRICES.items())

    def stock(self, item):
        """村じゅうにある item の数。"""
        return sum(v["inventory"].get(item, 0) for v in self.villagers.values())

    def act_cook(self, name, item):
        """家で、食材 1 つと薪 1 本を使って煮炊きし、その場で食べる。家族の食材や薪も使える。"""
        v = self.villagers[name]
        if v["location"] != v["home"]:
            return "煮炊きは家でしかできない。"
        if item not in INGREDIENTS:
            return f"{item}は煮炊きできない。食材: " + "、".join(INGREDIENTS)
        owner = self.food_owner(name, item)
        if owner is None:
            return f"家に{item}がない。"
        wood = self.food_owner(name, "薪")
        if wood is None:
            return "家に薪がない。"
        self.villagers[owner]["inventory"][item] -= 1
        self.villagers[wood]["inventory"]["薪"] -= 1
        dish = INGREDIENTS[item]
        v["hunger"] = max(0, v["hunger"] - HOME_MEAL)
        v["activity"] = f"{dish}を作って食べている"
        self.broadcast(v["location"], f"{name}が{dish}を作って食べている。", exclude=name)
        self.log(f"🍳 **{name}** 家で{dish}を作って食べた")
        return f"{dish}を作って食べた。空腹 {v['hunger']}/10。"

    def act_eat(self, name, item):
        v = self.villagers[name]
        if item in INGREDIENTS:
            return f"{item}は生では食べられない。家で cook（煮炊き）すれば食べられる。"
        if item not in FOOD:
            return f"{item}は食べられない。食べられるもの: " + "、".join(FOOD)
        owner = self.food_owner(name, item)
        if owner is None:
            return f"{item}を持っていない。"
        self.villagers[owner]["inventory"][item] -= 1
        v["hunger"] = max(0, v["hunger"] - FOOD[item])
        v["activity"] = f"{item}を食べている"
        self.broadcast(v["location"], f"{name}が{item}を食べている。", exclude=name)
        self.log(f"🍞 **{name}** {item}を食べた")
        return f"{item}を食べた。空腹 {v['hunger']}/10。"

    def food_owner(self, name, item):
        """name が食べられる item の持ち主。自分の分か、家にいるなら家族の分（家の食べ物は家族のもの）。"""
        v = self.villagers[name]
        if v["inventory"].get(item, 0) > 0:
            return name
        if v["location"] == v["home"]:
            for other, ov in self.villagers.items():
                if ov["home"] == v["home"] and ov["inventory"].get(item, 0) > 0:
                    return other
        return None

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

    def _members(self, need):
        return CATEGORIES.get(need, [need])

    def recipes(self, name):
        """name の仕事の作り方。上から順に、材料がそろっているものを作る。"""
        v = self.villagers[name]
        if v.get("recipes"):
            return v["recipes"]
        return [{"needs": v.get("needs", {}), "produce": v["produce"]}] if v["produce"] else []

    def outputs(self, name):
        return [item for r in self.recipes(name) for item in r["produce"]]

    def inputs(self, name):
        """仕事の材料と、1 回に要る最大の数。"""
        needs = {}
        for r in self.recipes(name):
            for need, n in r["needs"].items():
                needs[need] = max(needs.get(need, 0), n)
        return needs

    def _missing(self, name, needs):
        v = self.villagers[name]
        return [need for need, n in needs.items()
                if sum(v["inventory"].get(i, 0) for i in self._members(need)) < n]

    def lacking(self, name):
        """どの作り方も材料がそろわないとき、基本の作り方（いちばん下）で足りないもの。"""
        recipes = self.recipes(name)
        if not recipes or any(not self._missing(name, r["needs"]) for r in recipes):
            return []
        return self._missing(name, recipes[-1]["needs"])

    def uses(self, name, item):
        """item が name の仕事の材料かどうか。"""
        return any(item in self._members(need) for need in self.inputs(name))

    def surplus(self, name, item):
        """name が売ってもいい item の数。仕事の材料は売らない。"""
        if self.uses(name, item):
            return 0
        return self.villagers[name]["inventory"].get(item, 0) - KEEP.get(item, 0)

    def family(self, a, b):
        return self.villagers[a]["home"] == self.villagers[b]["home"]

    def household_stock(self, name, item):
        """name の一家全員が持っている item の数。"""
        home = self.villagers[name]["home"]
        return sum(v["inventory"].get(item, 0) for v in self.villagers.values() if v["home"] == home)

    def will_sell(self, seller, buyer, item):
        """村の決まり：余っていて、相手をひどく嫌っていなければ、相場で売る。家族とは売り買いせず分け合う。"""
        if self.family(seller, buyer):
            return False
        imp = self.villagers[seller]["impressions"].get(buyer, {"score": 0})["score"]
        return self.surplus(seller, item) > 0 and imp >= -2

    def will_buy(self, buyer, item):
        """村の決まり：要るものを、払える範囲で買う。
        仕事の材料は 4 つまで仕入れる。薪は夜の分を 2 本まで。食事は空腹なら 2 つまで。"""
        v = self.villagers[buyer]
        have, price = v["inventory"].get(item, 0), self.price(item) or 99
        if self.uses(buyer, item):
            return v["money"] >= price and have < 4
        if item == "薪":  # 夜の薪は一家で 1 本。今夜の分は必需品、余裕があれば何晩分か貯める
            stock = self.household_stock(buyer, "薪")
            if stock == 0:
                return v["money"] >= price
            return stock < WOOD_STORE and v["money"] - price >= 40
        if item in MEALS:
            return v["money"] >= price and have < 2 and v["hunger"] >= 3
        return False

    def act_sell(self, name, buyer, item):
        v = self.villagers[name]
        if buyer not in self.people_at(v["location"], exclude=name):
            return f"{buyer}はここにいない。"
        if self.family(name, buyer):
            return "家族とは売り買いしない。必要なら give で分け合う。"
        if not self.price(item) or v["inventory"].get(item, 0) <= 0:
            return f"{item}を持っていない。"
        if not self.will_buy(buyer, item):
            v["activity"] = f"{buyer}に{item}を売り込んでいる"
            self.log(f"🙅 **{buyer}** は **{name}** の{item}を買わなかった")
            return f"{buyer}には要らないと言われた。"
        price = self.price(item)
        v["inventory"][item] -= 1
        v["money"] += price
        self.villagers[buyer]["money"] -= price
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
        if self.family(name, seller):
            return "家族とは売り買いしない。必要なら分けてもらう。"
        if not self.price(item):
            return f"{item}は売り買いできない。相場: " + self.price_list()
        amount = max(1, amount)
        price = self.price(item) * amount
        if v["money"] < price:
            return f"銀貨が足りない（{price} 枚必要、手持ち {v['money']} 枚）。"
        if not self.will_sell(seller, name, item) or self.surplus(seller, item) < amount:
            v["activity"] = f"{seller}に{item}を売ってくれと頼んでいる"
            self.broadcast(v["location"], f"{name}が{seller}に{item}を売ってくれと頼んだが、断られた。",
                           exclude=name, kind="refuse", actor=name, to=seller, quote=item)
            self.log(f"🙅 **{seller}** は **{name}** に{item}を売らなかった")
            if self.surplus(seller, item) <= 0:
                self.note(name, item, "不足")
            return f"{seller}に断られた。"
        v["money"] -= price
        self.villagers[seller]["money"] += price
        self.villagers[seller]["inventory"][item] -= amount
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
        homes = {}
        for name, v in self.villagers.items():
            homes.setdefault(v["home"], []).append(name)
        for home, family in homes.items():
            # 一家で薪を 1 本燃やせば、全員が暖かく眠れる。いちばん多く持っている人が出す
            giver = max(family, key=lambda n: self.villagers[n]["inventory"].get("薪", 0))
            warm = self.villagers[giver]["inventory"].get("薪", 0) > 0
            if warm:
                self.villagers[giver]["inventory"]["薪"] -= 1
            else:
                self.log(f"🥶 {home}には薪がなく、寒い夜になった")
            for name in family:
                v = self.villagers[name]
                v["location"] = home
                v.pop("travel", None)
                v["hunger"] = min(10, v["hunger"] + 1)
                v["energy"] = 10 if warm else 7
                v["activity"] = "目を覚ましたところ"
                night = ("夜のあいだ、薪を燃やして暖かく眠った。" if warm
                         else "薪がなく、夜の冷え込みであまり眠れなかった。")
                v["inbox"].append({"t": night, "kind": "sleep", "actor": None, "to": None, "quote": None})
        self.data["day"] += 1
        self.data["hour_index"] = 0
        self.data["weather"] = random.choices([w for w, _ in WEATHERS], [p for _, p in WEATHERS])[0]
        self.morning_assembly()
        return True

    def morning_assembly(self):
        """朝 6 時の朝礼。全員が広場に集まり、それぞれの手持ちと困りごとを話す。
        その場で全員が聞くので、村全体で何が足りない・余っているかが、うわさではなく正確にわかる。
        受け渡しは、この時間に広場で顔を合わせた者どうしで行う（ついでの用事）。"""
        for v in self.villagers.values():
            v["location"] = ASSEMBLY_PLACE
            v.pop("travel", None)
            v["activity"] = "朝礼に出ている"
        have, want = {}, {}
        for name, v in self.villagers.items():
            for item in PRICES:
                have[item] = have.get(item, 0) + max(0, self.surplus(name, item))
            for need, n in self.inputs(name).items():  # 仕事の材料：2 回分に足りない分
                items = self._members(need)
                short = n * 2 - sum(v["inventory"].get(i, 0) for i in items)
                for i in items:
                    want[i] = want.get(i, 0) + max(0, short) / len(items)
            if not any(self.food_owner(name, f) for f in MEALS):  # 今日の食事がない
                want["パン"] = want.get("パン", 0) + 1
        for home in {v["home"] for v in self.villagers.values()}:  # 今夜の薪がない家
            member = next(n for n, v in self.villagers.items() if v["home"] == home)
            if self.household_stock(member, "薪") == 0:
                want["薪"] = want.get("薪", 0) + 1
        short = [i for i in PRICES if want.get(i, 0) > have.get(i, 0)]
        extra = [i for i in PRICES if i not in short and have.get(i, 0) >= RESERVE.get(i, 99) and not want.get(i)]
        for name in self.villagers:
            for item in short:
                self.note(name, item, "不足", "朝礼で聞いた")
            for item in extra:
                self.note(name, item, "余り", "朝礼で聞いた")
        self.log(f"🌅 朝礼（{ASSEMBLY_PLACE}）：足りない＝{'、'.join(short) or 'なし'}／余っている＝{'、'.join(extra) or 'なし'}")

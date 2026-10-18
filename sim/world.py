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
TURN_MINUTES = 120   # 1 ティックの持ち時間
MOVE_MINUTES = 20    # 村の中の移動は、どこへでも 20 分
MAX_MOVES = 3        # 1 ティックに歩ける回数（それ以上は何もする時間がない）
# 村の需要は「食べる」と「暖を取る」の二つだけ。品物はすべてそこから逆算する（README の「経済の設計」）。
#   食材（麦・魚・肉）─┐
#                       ├→ 加工（パン屋・酒場の台所）→ 食事（パン・料理）
#   薪 ────────────────┤
#                       └→ 夜の暖（一家に 1 本）
MEALS = {"料理": 5, "サンドイッチ": 5, "ツナサンド": 5, "パン": 3}  # ちゃんとした食事。食べると減る空腹度
SNACKS = {"燻製魚": 2, "燻製肉": 2, "干物": 2}  # 燻製・干物はそのままでも食べられるが、腹の足しは生より少しマシな程度
# 食材。生では食べず、家で薪を使って煮炊きする（燻製も食材として使える）
INGREDIENTS = {"麦": "麦粥", "魚": "焼き魚", "肉": "焼き肉", "燻製魚": "燻製魚の焼き物", "燻製肉": "燻製肉の煮込み",
               "干物": "干物のあぶり"}
# 毎晩、持っている分のうちこの割合が傷んで捨てられる。麦と薪、保存食は傷まない
SPOIL = {"料理": 0.5, "サンドイッチ": 0.5, "ツナサンド": 0.5, "魚": 0.4, "肉": 0.3, "パン": 0.2}  # 燻製・干物は傷まない
# 保存食づくり：手の空いた日に時間を使って、傷む食材を長持ちする食べ物にする
PRESERVE = {
    # 作るもの: 場所、材料、元の食材、作れない天気
    "干物": {"place": "川辺", "needs": {"魚": 2}, "from": "魚", "makes": {"干物": 2}, "weather_ng": ("雨", "嵐", "霧"), "how": "魚を開いて干した"},
    "燻製魚": {"place": "家", "needs": {"魚": 2, "薪": 10}, "from": "魚", "makes": {"燻製魚": 2}, "weather_ng": (), "how": "魚を燻した"},
    "燻製肉": {"place": "家", "needs": {"肉": 2, "薪": 10}, "from": "肉", "makes": {"燻製肉": 2}, "weather_ng": (), "how": "肉を燻した"},
}
# 薪の数え方：一晩の暖房、家での煮炊き 1 回、燻製 1 回、店の 1 回の仕事に、それぞれ 10 本
NIGHT_WOOD = 10
COOK_WOOD = 10
WOOD_LOT = 10  # 薪を売り買いするときのひと束
HOME_MEAL = 4  # 家で煮炊きした食事で減る空腹度。薪 10 本で 1 人前なので、店より薪を食う
FOOD = {**MEALS, **SNACKS}
RETAIL_MARKUP = 1.25  # 店が仕入れた食材を店先で売るときの上乗せ
# 仕事の材料に「どれでもいい」を指定するための分類
CATEGORIES = {"食材": list(INGREDIENTS), "魚類": ["魚", "燻製魚", "干物"], "肉類": ["肉", "燻製肉"]}
PRICES = {"料理": 25, "サンドイッチ": 34, "ツナサンド": 34, "パン": 24, "燻製魚": 40, "燻製肉": 38, "干物": 36, "麦": 26, "魚": 30, "肉": 28, "薪": 1}  # 村の相場（銀貨）。売り手の収支を見て自動で詰めた値
HELP_JOBS = {"畑": {"麦": 1}, "川辺": {"魚": 1}, "森の入口": {"薪": 10}}  # 誰でもできる手伝い仕事（本業より実入りは少ない）
# これだけ売れ残ったら「余っている」と感じる（村で 1〜2 日分の備蓄の目安）
RESERVE = {"麦": 8, "魚": 4, "肉": 4, "薪": 80, "パン": 8, "サンドイッチ": 6, "ツナサンド": 6, "料理": 6, "燻製魚": 10, "燻製肉": 10, "干物": 10}
WOOD_STORE = 50  # 薪は傷まないので、懐に余裕があれば一家で何晩分（10 本で一晩）か貯めておく
ASSEMBLY_PLACE = "広場"  # 毎朝 6 時、全員がここに集まって朝礼をする
NEWS_DAYS = 2  # 聞いた村の様子を当てにする日数
SAY_STATE = {"不足": "足りない", "余り": "余っている"}
FAMILY_KEEP = {"食材": 2}  # 家に持ち帰ったとき、煮炊き用に蔵へ入れる食材の数（残りは売り物として持っておく）
DEFAULT_DEMAND = 6
SHOP_BUFFER = 4  # 酒場が蓄えておく、傷まない食材（燻製・干物・麦）それぞれの数  # 店がまだ売れ行きを知らないときの、1 日に売れる見込み
KEEP = {"料理": 2, "サンドイッチ": 2, "ツナサンド": 2, "パン": 2, "燻製魚": 1, "燻製肉": 1, "干物": 1, "麦": 1, "魚": 1, "肉": 1, "薪": 10}  # 自分用に残す数。超えた分なら売る
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
            "stores": {},   # 場所ごとの在庫（家の蔵、店の棚）{場所: {品物: 数}}
            "sales": {},    # 店ごとの売れ行き {店: {日: 数}}
            "orders": {},   # 朝礼で店が出した材料の注文 {店: {品物: 数}}
        }
        world = cls(data)
        for name, v in villagers.items():  # 最初の持ち物は、家の蔵と店の棚にしまっておく
            data["stores"].setdefault(v["home"], {})
            if world.recipes(name) and world.inputs(name):
                data["stores"].setdefault(v["workplace"], {})
            for item, n in list(v["inventory"].items()):
                to_shop = (world.uses(name, item) or item in world.outputs(name)) and world.inputs(name)
                if to_shop and item == "薪":  # 店の主人の薪は、店に 1 回分残して家へ
                    world._add(data["stores"][v["workplace"]], item, WOOD_LOT)
                    n -= WOOD_LOT
                    to_shop = False
                world._add(data["stores"][v["workplace"] if to_shop else v["home"]], item, n)
                v["inventory"][item] = 0
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

    def begin_turn(self, name):
        """ターンの始め。2 時間の持ち時間を元に戻す。"""
        v = self.villagers[name]
        v["moves"] = 0
        v["visited"] = [v["location"]]

    def minutes_left(self, name):
        return TURN_MINUTES - MOVE_MINUTES * self.villagers[name].get("moves", 0)

    def can_move(self, name):
        return self.villagers[name].get("moves", 0) < MAX_MOVES

    # ---------- 場所の在庫（家の蔵・店の棚） ----------

    @staticmethod
    def _add(box, item, n):
        box[item] = box.get(item, 0) + n

    def shop_owner(self, place):
        """place が誰かの店（材料を仕入れて加工する仕事場）なら、その主人。"""
        for name, v in self.villagers.items():
            if v["workplace"] == place and self.inputs(name):
                return name
        return None

    def store_at(self, name):
        """name がいま使える場所の在庫。家にいれば家の蔵、自分の店にいれば店の棚。"""
        v = self.villagers[name]
        here = v["location"]
        if here == v["home"]:
            return self.data["stores"].setdefault(here, {})
        if here == v["workplace"] and self.shop_owner(here) == name:
            return self.data["stores"].setdefault(here, {})
        return None

    def has(self, name, item):
        """name がいま手に取れる item の数（持ち物＋いる場所の在庫。注文で作る店の主人なら出せる料理の数も）。"""
        box = self.store_at(name) or {}
        n = self.villagers[name]["inventory"].get(item, 0) + box.get(item, 0)
        if item in self.outputs(name) and self.at_order_shop(name):
            n += self.servable(name)
        return n

    # ---------- 注文を受けてから作る店（酒場） ----------

    def at_order_shop(self, name):
        v = self.villagers[name]
        return v.get("to_order") and v["location"] == v["workplace"]

    def servable(self, name):
        """いま出せる料理の数。鍋に残っている分と、棚の材料で作れる分。"""
        shop = self.villagers[name]["workplace"]
        pot = self.data.setdefault("pots", {}).get(shop, 0)
        box = self.data["stores"].get(shop, {})
        recipe = self.recipes(name)[-1]
        batches = min((sum(box.get(i, 0) for i in self._members(need)) // n) for need, n in recipe["needs"].items())
        return pot + batches * sum(recipe["produce"].values())

    def serve(self, name, n):
        """注文を受けて料理を出す。鍋が空なら、棚の材料で一鍋作る（材料と薪を使う）。"""
        shop = self.villagers[name]["workplace"]
        pots = self.data.setdefault("pots", {})
        recipe = self.recipes(name)[-1]
        while pots.get(shop, 0) < n and not self._missing(name, recipe["needs"]):
            for need, k in recipe["needs"].items():
                for _ in range(k):
                    item = max(self._members(need), key=lambda i: self.data["stores"][shop].get(i, 0))
                    self.data["stores"][shop][item] -= 1
            made = sum(recipe["produce"].values())
            pots[shop] = pots.get(shop, 0) + made
            self.log(f"🍲 **{name}** 注文を受けて一鍋作った（料理×{made}）")
        served = min(n, pots.get(shop, 0))
        pots[shop] = pots.get(shop, 0) - served
        return served

    def take(self, name, item, n=1):
        """item を n 個取り出す。家や店の在庫から先に使い、足りなければ持ち物から。"""
        if self.has(name, item) < n:
            return False
        if item in self.outputs(name) and self.at_order_shop(name):
            return self.serve(name, n) == n
        box = self.store_at(name) or {}
        for _ in range(n):
            if box.get(item, 0) > 0:
                box[item] -= 1
            else:
                self.villagers[name]["inventory"][item] -= 1
        return True

    def put(self, name, item, n=1):
        """手に入れた item を置く。家や自分の店にいればそこの在庫へ、それ以外は持ち物へ。"""
        box = self.store_at(name)
        self._add(box if box is not None else self.villagers[name]["inventory"], item, n)

    def put_away(self, name):
        """家や自分の店に着いたら、持ち物をしまう。
        家には食事と薪（貯めておける分まで）と煮炊き用の食材を少し入れ、残りは売り物として持っておく。
        店には仕事の材料と売り物をすべて並べる。"""
        v = self.villagers[name]
        box = self.store_at(name)
        if box is None:
            return
        inv = v["inventory"]
        for item, n in list(inv.items()):
            if n <= 0:
                continue
            if v["location"] != v["home"]:  # 自分の店
                if self.uses(name, item) or item in self.outputs(name):
                    self._add(box, item, n); inv[item] = 0
                continue
            if item in MEALS:
                move = n
            elif item == "薪":
                move = max(0, min(n, WOOD_STORE - box.get("薪", 0)))
            elif item in INGREDIENTS and item not in self.made_goods(name):
                move = n  # 買ってきた食材は家で使う
            elif item in INGREDIENTS:  # 自分で獲った・作った品は、家に少し置いて残りは売り物として持っておく
                move = max(0, min(n, FAMILY_KEEP["食材"] - box.get(item, 0)))
            else:
                move = 0
            if move:
                self._add(box, item, move); inv[item] -= move

    def home_stock(self, name, item):
        """name の家の蔵にある item の数。"""
        return self.data["stores"].get(self.villagers[name]["home"], {}).get(item, 0)

    # ---------- 店の売れ行きと注文 ----------

    def record_sale(self, shop, n):
        day = str(self.data["day"])
        sales = self.data["sales"].setdefault(shop, {})
        sales[day] = sales.get(day, 0) + n

    def expected_demand(self, shop):
        """今日売れそうな数の見込み。毎晩、売れ行きを見て店の主人が決め直す（update_demand）。"""
        return self.data.setdefault("demand", {}).get(shop, DEFAULT_DEMAND)

    def update_demand(self):
        """夜、店じまいのときに見込みを決め直す。品切れなら明日は多めに、売れ残れば少し減らす。
        （品切れの日の売れた数は本当の需要より少ないので、売れた数だけで決めると先細りする）"""
        for shop in [p for p in self.data["stores"] if self.shop_owner(p)]:
            demand = self.expected_demand(shop)
            if self.villagers[self.shop_owner(shop)].get("to_order"):  # 注文で作る店：出た数と断った数から
                asked = self.sold_today(shop) + self.data.setdefault("missed", {}).get(shop, 0)
                self.data["demand"][shop] = max(3, round((demand + asked) / 2 + 0.49))
                self.data["missed"][shop] = 0
                left = self.data.setdefault("pots", {}).get(shop, 0)
                if left:
                    self.log(f"🍲 {shop}の鍋に残った料理×{left}を片づけた")
                self.data["pots"][shop] = 0
                continue
            left = self.shelf_goods(shop)
            if left == 0:
                demand = min(30, demand + 2)
            elif left >= 3:
                demand = max(3, demand - left // 3)
            self.data["demand"][shop] = demand

    def shelf_goods(self, shop):
        owner = self.shop_owner(shop)
        box = self.data["stores"].get(shop, {})
        return sum(box.get(i, 0) for i in self.outputs(owner)) if owner else 0

    def sold_today(self, shop):
        return self.data["sales"].get(shop, {}).get(str(self.data["day"]), 0)

    def needs_more_goods(self, shop):
        """店の棚の品と今日もう売れた数が、見込みに届いていなければ作る。注文で作る店は作り置きしない。"""
        if self.villagers[self.shop_owner(shop)].get("to_order"):
            return False
        return self.shelf_goods(shop) + self.sold_today(shop) < self.expected_demand(shop)

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

    def broadcast(self, place, text, exclude=None, kind="see", actor=None, to=None, quote=None, small=False):
        """その場にいる村人の耳と目に、出来事を届ける。small はあいさつ等の、噂にならない小話。"""
        event = {"t": f"{self.hour:02d}:00 {place}: {text}", "kind": kind,
                 "actor": actor, "to": to, "quote": quote, "small": small}
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
        box = self.store_at(name)
        if box is not None:
            label = "家の蔵" if here == v["home"] else "店の棚"
            lines.append(f"【{label}】" + ("、".join(f"{k}×{n}" for k, n in box.items() if n > 0) or "空っぽ"))
            if label == "店の棚":
                lines.append(f"【店の売れ行き】今日はこれまでに {self.sold_today(here)} 個、見込みは 1 日 {self.expected_demand(here)} 個")
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
        lines.append(f"【村の場所】（どこへでも歩いて {MOVE_MINUTES} 分。この 2 時間の残り {self.minutes_left(name)} 分）" + "、".join(
            p for p in self.data["places"] if p != here))
        lines.append("【ほかの村人】" + "、".join(others_far))
        return "\n".join(lines)

    # ---------- 行動（ターンを消費する） ----------

    def act_move(self, name, destination):
        v = self.villagers[name]
        if destination not in self.data["places"]:
            return f"「{destination}」という場所はない。行ける場所: " + "、".join(self.data["places"])
        if destination == v["location"]:
            return "もうそこにいる。"
        if not self.can_move(name):
            return "この 2 時間はもう歩き回る時間がない。"
        if v.get("moves", 0) >= 2 and destination in v.get("visited", []):
            return f"{destination}にはさっき行ったばかりだ。行ったり来たりしていても仕方がない。"
        src = v["location"]
        v["moves"] = v.get("moves", 0) + 1
        v.setdefault("visited", []).append(destination)
        self.broadcast(src, f"{name}が{destination}へ向かった。", exclude=name)
        v["location"] = destination
        v["activity"] = "やって来たところ"
        self.broadcast(destination, f"{name}がやって来た。", exclude=name)
        self.log(f"🚶 **{name}** {src} → {destination}")
        self.put_away(name)
        return f"{destination}に着いた（この 2 時間の残り {self.minutes_left(name)} 分）。"

    def act_say(self, name, to, message, small=False):
        v = self.villagers[name]
        here = v["location"]
        present = self.people_at(here, exclude=name)
        if to not in ("みんな", "ひとりごと") and to not in present:
            return f"{to}はここにいない。ここにいるのは: " + ("、".join(present) or "誰もいない")
        target = "" if to in ("みんな", "ひとりごと") else f"→{to}"
        v["activity"] = f"{to}と話している" if target else "話している"
        self.broadcast(here, f"{name}{target}「{message}」", exclude=name,
                       kind="say", actor=name, to=to, quote=message, small=small)
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
        recipe = self._pick_recipe(name)
        if recipe is None:
            lacking = self.lacking(name)
            for need in lacking:
                for item in self._members(need):
                    self.note(name, item, "不足")
            return f"仕事に使う{'、'.join(lacking)}が足りない。"
        for need, n in recipe["needs"].items():
            for _ in range(n):
                item = max(self._members(need), key=lambda i: self.has(name, i))
                self.take(name, item)
        bonus = self._streak(name)
        gained = []
        for item, n in recipe["produce"].items():
            if self.data["weather"] in ("雨", "嵐") and v["workplace"] in ("畑", "川辺", "森の入口"):
                n = max(1, n // 2)
            n = self._scale(name, n + bonus)
            if n <= 0:
                continue
            self.put(name, item, n)
            gained.append(f"{item}×{n}")
            if self.surplus(name, item) >= RESERVE.get(item, 99):
                self.note(name, item, "余り")
        if not gained:
            return "歩き回って時間がなく、仕事にならなかった。"
        v["energy"] = max(0, v["energy"] - 1)
        v["activity"] = f"{v['job']}の仕事をしている"
        self.broadcast(v["location"], f"{name}が仕事をしている。", exclude=name)
        self.log(f"🔨 **{name}** 働いた（{'、'.join(gained)}）" + ("　続けて働いてはかどった" if bonus else ""))
        return f"働いて {'、'.join(gained)} を得た。" + ("続けて働いたのではかどった。" if bonus else "")

    def _scale(self, name, n):
        """歩いた分だけ働く時間が減る。残り時間に応じて実入りを減らす（端数は確率で丸める）。"""
        x = n * self.minutes_left(name) / TURN_MINUTES
        return int(x) + (random.random() < x - int(x))

    def _pick_recipe(self, name):
        """材料のそろう作り方のうち、基本（いちばん下）以外があれば、具の手持ちが多いほうを選ぶ。"""
        recipes = self.recipes(name)
        ready = [r for r in recipes if not self._missing(name, r["needs"])]
        if not ready:
            return None
        special = [r for r in ready if r is not recipes[-1]]
        if not special:
            return ready[0]
        def filling(r):
            return sum(self.has(name, i) for need in r["needs"] for i in self._members(need)
                       if need in CATEGORIES and need != "食材")
        return max(special, key=filling)

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
            n = self._scale(name, n + bonus)
            if n <= 0:
                continue
            v["inventory"][item] = v["inventory"].get(item, 0) + n
            gained.append(f"{item}×{n}")
        if not gained:
            return "歩き回って時間がなく、手伝いにならなかった。"
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
        return (sum(v["inventory"].get(item, 0) for v in self.villagers.values())
                + sum(box.get(item, 0) for box in self.data["stores"].values()))

    def act_preserve(self, name, item):
        """手の空いた時間に、魚を干物や燻製に、肉を燻製にする（2 時間かかる）。傷まず、生より少し高く売れる。"""
        v = self.villagers[name]
        if item not in PRESERVE:
            return "作れるのは 干物（川辺で魚から）・燻製魚・燻製肉（家で薪を使って）だけ。"
        rule = PRESERVE[item]
        place = v["home"] if rule["place"] == "家" else rule["place"]
        if v["location"] != place and not (rule["place"] == "家" and self.at_order_shop(name)):
            return f"{item}は{rule['place'] if rule['place'] != '家' else '家（酒場なら店の台所）'}でしか作れない。"
        if self.data["weather"] in rule["weather_ng"]:
            return f"{self.data['weather']}の日は干せない。"
        for need, n in rule["needs"].items():
            if self.has(name, need) < n:
                return f"{need}が足りない（{n}つ要る）。"
        for need, n in rule["needs"].items():
            self.take(name, need, n)
        made = []
        for out, n in rule["makes"].items():
            self.put(name, out, n)
            made.append(f"{out}×{n}")
        v["energy"] = max(0, v["energy"] - 1)
        v["activity"] = f"{rule['how'].rstrip('た')}ている"
        self.broadcast(v["location"], f"{name}が{rule['how'].rstrip('た')}ている。", exclude=name)
        self.log(f"🐟 **{name}** {rule['how']}（{'、'.join(made)}）")
        return f"{rule['how']}。{'、'.join(made)}ができた。傷まず、生より少し高く売れる。"

    def spoil(self):
        """夜、傷みやすい食べ物の一部が傷んで捨てられる（持ち物も、家の蔵も、店の棚も）。"""
        boxes = [(f"**{n}** の持ち物", v["inventory"]) for n, v in self.villagers.items()]
        boxes += [(f"{place}{'の棚' if self.shop_owner(place) else 'の蔵'}", box) for place, box in self.data["stores"].items()]
        for label, box in boxes:
            lost = []
            for item, rate in SPOIL.items():
                n = sum(random.random() < rate for _ in range(box.get(item, 0)))
                if n:
                    box[item] -= n
                    lost.append(f"{item}×{n}")
            if lost:
                self.log(f"🦠 {label}の{'、'.join(lost)}が傷んで捨てた")

    def act_cook(self, name, item):
        """家で、食材 1 つと薪 10 本を使って煮炊きし、その場で食べる。家族の食材や薪も使える。"""
        v = self.villagers[name]
        if v["location"] != v["home"]:
            return "煮炊きは家でしかできない。"
        if item not in INGREDIENTS:
            return f"{item}は煮炊きできない。食材: " + "、".join(INGREDIENTS)
        if self.has(name, item) <= 0:
            return f"家に{item}がない。"
        if self.has(name, "薪") < COOK_WOOD:
            return f"家に薪が足りない（{COOK_WOOD} 本要る）。"
        self.take(name, item)
        self.take(name, "薪", COOK_WOOD)
        dish = INGREDIENTS[item]
        v["hunger"] = max(0, v["hunger"] - HOME_MEAL)
        v["activity"] = f"{dish}を作って食べている"
        self.broadcast(v["location"], f"{name}が{dish}を作って食べている。", exclude=name)
        self.log(f"🍳 **{name}** 家で{dish}を作って食べた")
        return f"{dish}を作って食べた。空腹 {v['hunger']}/10。"

    def act_eat(self, name, item):
        v = self.villagers[name]
        if item in INGREDIENTS and item not in FOOD:
            return f"{item}は生では食べられない。家で cook（煮炊き）すれば食べられる。"
        if item not in FOOD:
            return f"{item}は食べられない。食べられるもの: " + "、".join(FOOD)
        if not self.take(name, item):
            return f"{item}を持っていない。"
        v["hunger"] = max(0, v["hunger"] - FOOD[item])
        v["activity"] = f"{item}を食べている"
        self.broadcast(v["location"], f"{name}が{item}を食べている。", exclude=name)
        self.log(f"🍞 **{name}** {item}を食べた")
        return f"{item}を食べた。空腹 {v['hunger']}/10。"

    def food_owner(self, name, item):
        """name がいま item を手に取れるか（持ち物か、家の蔵・自分の店の棚に）。"""
        return self.has(name, item) > 0

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
            if not self.take(name, item, amount):
                return f"{item}が足りない。"
            self.put(to, item, amount)
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

    def made_goods(self, name):
        """name が売り物にする品：仕事で作るものと、それを干物・燻製にしたもの。"""
        outs = self.outputs(name)
        return outs + [make for make, rule in PRESERVE.items() if rule["from"] in outs]

    def inputs(self, name):
        """仕事の材料と、1 回に要る最大の数。"""
        needs = {}
        for r in self.recipes(name):
            for need, n in r["needs"].items():
                needs[need] = max(needs.get(need, 0), n)
        return needs

    def _missing(self, name, needs):
        return [need for need, n in needs.items()
                if sum(self.has(name, i) for i in self._members(need)) < n]

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
        """name が売ってもいい item の数。仕事の材料は売らない。
        自分の作った品は持っている分すべて（店の主人が店にいれば棚の分も）。それ以外は自分の分を残して。"""
        v = self.villagers[name]
        if self.uses(name, item):
            if self.at_order_shop(name):  # 酒場は、料理に使う分（各 2 つ）を残して食材を店先で売る
                return max(0, self.data["stores"][v["workplace"]].get(item, 0) - 2)
            return 0
        carried = self.villagers[name]["inventory"].get(item, 0)
        if item in self.outputs(name) and self.at_order_shop(name):
            return self.servable(name)
        if item in self.made_goods(name) and item not in self.outputs(name):
            return carried  # 自分で作った干物・燻製は持っている分すべて売り物
        if item in self.outputs(name):
            box = self.store_at(name)
            shelf = box.get(item, 0) if box is not None and self.shop_owner(self.villagers[name]["location"]) == name else 0
            return carried + shelf
        return carried - KEEP.get(item, 0)

    def family(self, a, b):
        return self.villagers[a]["home"] == self.villagers[b]["home"]

    def household_stock(self, name, item):
        """name の家の蔵と、一家が持ち歩いている item の数。"""
        home = self.villagers[name]["home"]
        return self.home_stock(name, item) + sum(
            v["inventory"].get(item, 0) for v in self.villagers.values() if v["home"] == home)

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
        have, price = self.has(buyer, item), self.price(item) or 99
        if self.uses(buyer, item):  # 店の材料：見込みの分まで。薪代は残しておく
            shop = v["workplace"]
            box = self.data["stores"].get(shop, {})
            reserve = 0 if item == "薪" else self.price("薪") * WOOD_LOT * 2
            if v["money"] - price < reserve:
                return False
            if v.get("to_order") and item != "薪" and item not in SPOIL:  # 傷まない食材は少し蓄えておく
                return box.get(item, 0) + v["inventory"].get(item, 0) < SHOP_BUFFER
            for need, n in self.inputs(buyer).items():
                members = self._members(need)
                if item in members:
                    batches = -(-self.expected_demand(shop) // sum(self.recipes(buyer)[-1]["produce"].values()))
                    want = n * batches + (2 if v.get("to_order") and need != "薪" else 0)
                    have_now = sum(box.get(i, 0) + v["inventory"].get(i, 0) for i in members)
                    return have_now < max(want, n)
            return False
        if item == "薪":  # 夜の薪は一家で 10 本。今夜の分は必需品、余裕があれば何晩分か貯める
            stock = self.household_stock(buyer, "薪")
            if stock < NIGHT_WOOD:
                return v["money"] >= price
            return stock < WOOD_STORE and v["money"] - price * WOOD_LOT >= 40
        if item in MEALS:
            return v["money"] >= price and have < 2 and v["hunger"] >= 3
        if item in INGREDIENTS:  # 家で煮炊きする食材：家に食材がなく、薪があって懐に余裕があれば
            home_food = sum(self.home_stock(buyer, i) for i in INGREDIENTS)
            return home_food < 2 and self.household_stock(buyer, "薪") >= COOK_WOOD * 2 and v["money"] - price >= 40
        return False

    def act_sell(self, name, buyer, item):
        v = self.villagers[name]
        if buyer not in self.people_at(v["location"], exclude=name):
            return f"{buyer}はここにいない。"
        if self.family(name, buyer):
            return "家族とは売り買いしない。必要なら give で分け合う。"
        if not self.price(item) or self.surplus(name, item) <= 0:
            return f"{item}を持っていない。"
        if not self.will_buy(buyer, item):
            v["activity"] = f"{buyer}に{item}を売り込んでいる"
            self.log(f"🙅 **{buyer}** は **{name}** の{item}を買わなかった")
            return f"{buyer}には要らないと言われた。"
        n = 1
        if item == "薪":  # 薪はひと束（10 本）を、相手が払える分まで
            n = min(WOOD_LOT, self.surplus(name, item), self.villagers[buyer]["money"] // self.price(item))
        price = self.price(item) * n
        self._hand_over(name, buyer, item, n)
        v["money"] += price
        self.villagers[buyer]["money"] -= price
        v["activity"] = f"{buyer}に{item}を売っている"
        self.broadcast(v["location"], f"{name}が{buyer}に{item}を売った。", exclude=name,
                       kind="trade", actor=name, to=buyer, quote=item)
        count = f"×{n}" if n > 1 else ""
        self.log(f"💰 **{name}** は **{buyer}** に{item}{count}を銀貨{price}枚で売った")
        return f"{buyer}に{item}{count}を銀貨{price}枚で売った。"

    def act_buy(self, name, seller, item, amount):
        v = self.villagers[name]
        if seller not in self.people_at(v["location"], exclude=name):
            return f"{seller}はここにいない。"
        if self.family(name, seller):
            return "家族とは売り買いしない。必要なら分けてもらう。"
        if not self.price(item):
            return f"{item}は売り買いできない。相場: " + self.price_list()
        amount = max(1, amount)
        unit = self.price(item)
        if self.uses(seller, item) and self.at_order_shop(seller):
            unit = round(unit * RETAIL_MARKUP)  # 店先で売る食材は少し上乗せ
        price = unit * amount
        if v["money"] < price:
            return f"銀貨が足りない（{price} 枚必要、手持ち {v['money']} 枚）。"
        if not self.will_sell(seller, name, item) or self.surplus(seller, item) < amount:
            v["activity"] = f"{seller}に{item}を売ってくれと頼んでいる"
            self.broadcast(v["location"], f"{name}が{seller}に{item}を売ってくれと頼んだが、断られた。",
                           exclude=name, kind="refuse", actor=name, to=seller, quote=item)
            self.log(f"🙅 **{seller}** は **{name}** に{item}を売らなかった")
            if self.surplus(seller, item) <= 0:
                self.note(name, item, "不足")
                if self.at_order_shop(seller) and item in self.outputs(seller):  # 材料がなくて注文を断った
                    shop = self.villagers[seller]["workplace"]
                    self.data.setdefault("missed", {})[shop] = self.data["missed"].get(shop, 0) + amount
            return f"{seller}に断られた。"
        v["money"] -= price
        self.villagers[seller]["money"] += price
        self._hand_over(seller, name, item, amount)
        v["activity"] = f"{seller}から{item}を買っている"
        self.broadcast(v["location"], f"{name}が{seller}から{item}を{amount}つ買った。", exclude=name,
                       kind="trade", actor=name, to=seller, quote=item)
        self.log(f"💰 **{name}** は **{seller}** から{item}×{amount}を銀貨{price}枚で買った")
        return f"{seller}から{item}を{amount}つ、銀貨{price}枚で買った。"

    def _hand_over(self, seller, buyer, item, n):
        """売り手から買い手へ品を渡す。店の主人が売るなら棚から、買い手が店や家にいればそこへ入る。"""
        sv = self.villagers[seller]
        if item in self.outputs(seller) and self.at_order_shop(seller):
            self.serve(seller, n)
        else:
            for _ in range(n):
                if sv["inventory"].get(item, 0) > 0:
                    sv["inventory"][item] -= 1
                else:
                    self.store_at(seller)[item] -= 1
        self.put(buyer, item, n)
        shop = sv["location"]
        if self.shop_owner(shop) == seller and item in self.outputs(seller):
            self.record_sale(shop, n)
        orders = self.data["orders"].get(self.villagers[buyer]["workplace"], {})
        if self.uses(buyer, item) and orders.get(item, 0) > 0:
            orders[item] = max(0, orders[item] - n)

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
        self.update_demand()
        self.spoil()
        homes = {}
        for name, v in self.villagers.items():
            homes.setdefault(v["home"], []).append(name)
            v["location"] = v["home"]
            self.put_away(name)
        for home, family in homes.items():
            # 一家で薪を 1 本燃やせば、全員が暖かく眠れる。蔵の薪から使い、なければ誰かの持ち歩き分を使う
            box = self.data["stores"].setdefault(home, {})
            carried = sum(self.villagers[n]["inventory"].get("薪", 0) for n in family)
            warm = box.get("薪", 0) + carried >= NIGHT_WOOD
            if warm:  # 蔵の薪から使い、足りなければ持ち歩いている分から
                need = NIGHT_WOOD
                use = min(need, box.get("薪", 0)); box["薪"] = box.get("薪", 0) - use; need -= use
                for n in family:
                    use = min(need, self.villagers[n]["inventory"].get("薪", 0))
                    self.villagers[n]["inventory"]["薪"] = self.villagers[n]["inventory"].get("薪", 0) - use
                    need -= use
            else:
                self.log(f"🥶 {home}には薪が足りず、寒い夜になった")
            for name in family:
                v = self.villagers[name]
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

    def _breakfast(self, name):
        """朝礼に出かける前に、家の蔵のもので朝ごはんを食べる（傷みやすいものから）。"""
        v = self.villagers[name]
        if v["location"] != v["home"] or v["hunger"] < 2:
            return
        meal = next((f for f in sorted(MEALS, key=lambda f: (-SPOIL.get(f, 0), -MEALS[f])) if self.has(name, f)), None)
        if meal:
            self.act_eat(name, meal)
        elif self.has(name, "薪") >= COOK_WOOD * 2 and v["hunger"] >= 4:
            item = next((i for i in INGREDIENTS if self.has(name, i)), None)
            if item:
                self.act_cook(name, item)

    def morning_assembly(self):
        """朝 6 時の朝礼。全員が広場に集まり、それぞれの手持ちと困りごとを話す。
        その場で全員が聞くので、村全体で何が足りない・余っているかが、うわさではなく正確にわかる。
        受け渡しは、この時間に広場で顔を合わせた者どうしで行う（ついでの用事）。"""
        for name, v in self.villagers.items():
            self._breakfast(name)
            v["location"] = ASSEMBLY_PLACE
            v["activity"] = "朝礼に出ている"
        have, want = {}, {}
        orders = self.data["orders"] = {}
        for name, v in self.villagers.items():
            for item in PRICES:
                have[item] = have.get(item, 0) + max(0, self.surplus(name, item))
            for place, box in self.data["stores"].items():  # 店の棚の売り物
                if self.shop_owner(place) == name:
                    for item in self.outputs(name):
                        have[item] = have.get(item, 0) + box.get(item, 0)
            if self.inputs(name):  # 店：今日売れそうな分を作るのに足りない材料を注文する
                shop = v["workplace"]
                box = self.data["stores"].setdefault(shop, {})
                recipe = self.recipes(name)[-1]
                per_batch = sum(recipe["produce"].values())
                batches = max(0, -(-(self.expected_demand(shop) - self.shelf_goods(shop)) // per_batch))
                order = {}
                for need, n in recipe["needs"].items():
                    items = self._members(need)
                    short = n * batches - sum(box.get(i, 0) for i in items)
                    if short > 0:
                        for i in items:  # 「食材」のようにどれでもいい材料は、手に入りやすい順に頼む
                            order[i] = order.get(i, 0) + short / len(items)
                for r in self.recipes(name)[:-1]:  # サンドイッチの具（肉・魚）を半分ずつ頼む
                    for need in r["needs"]:
                        if need in ("魚類", "肉類"):
                            raw = self._members(need)[0]
                            have_now = sum(box.get(i, 0) for i in self._members(need))
                            want_n = -(-batches // 2)
                            if want_n > have_now:
                                order[raw] = order.get(raw, 0) + want_n - have_now
                order = {i: round(q + 0.49) for i, q in order.items() if round(q + 0.49) > 0}
                orders[shop] = order
                for i, q in order.items():
                    want[i] = want.get(i, 0) + q
            if not any(self.food_owner(name, f) for f in MEALS) and self.home_stock(name, "パン") == 0:
                want["パン"] = want.get("パン", 0) + 1
        for home in {v["home"] for v in self.villagers.values()}:  # 今夜の薪がない家
            member = next(n for n, v in self.villagers.items() if v["home"] == home)
            if self.household_stock(member, "薪") < NIGHT_WOOD:
                want["薪"] = want.get("薪", 0) + NIGHT_WOOD
        short = [i for i in PRICES if want.get(i, 0) > have.get(i, 0)]
        extra = [i for i in PRICES if i not in short and have.get(i, 0) >= RESERVE.get(i, 99) and not want.get(i)]
        for name in self.villagers:
            for item in short:
                self.note(name, item, "不足", "朝礼で聞いた")
            for item in extra:
                self.note(name, item, "余り", "朝礼で聞いた")
        self.log(f"🌅 朝礼（{ASSEMBLY_PLACE}）：足りない＝{'、'.join(short) or 'なし'}／余っている＝{'、'.join(extra) or 'なし'}")
        for shop, order in orders.items():
            if order:
                self.log(f"📋 {shop}（{self.shop_owner(shop)}）の注文：" + "、".join(f"{i}×{q}" for i, q in order.items()))

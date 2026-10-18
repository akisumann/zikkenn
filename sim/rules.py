"""ルールで動く村人の頭脳。API なしで「基本的にはこう動く」を表す。

上から順に当てはまるものを 1 つ選んで行動する（ツールは AI と同じものを使う）。

  0. 反応   … 見聞きしたことに心を動かす（印象・記憶。ターンは消費しない）
  1. 空腹   … 腹が減ったら食べる。食べ物がなければ買いに行く
  2. 疲労   … 疲れてきたら薬草を飲む。くたくたなら家に帰って休む
  3. 食事時 … 朝・昼・夕に少し空腹なら食べる
  4. 助け合い … 目の前に腹ぺこの人がいて、好きな相手で、余っていれば分ける
  5. 返事   … 話しかけられたら、性格に応じて返事をする
  6. 商売   … 余っている品（薪・薬草・エールなど）を、欲しがりそうな人に売り込む
  7. 習慣   … その人ならではの癖（seed の habits）
  8. 日課   … 時間割どおりの場所へ行き、仕事をしたり、おしゃべりしたりする
"""

import random

from .brains import run_tool
from .world import FOOD, PRICES

# 時間割の既定値。「家」「仕事場」「自由」か、場所の名前を書く。seed の routine で上書きできる
DEFAULT_ROUTINE = {6: "家", 8: "仕事場", 10: "仕事場", 12: "仕事場", 14: "仕事場",
                   16: "自由", 18: "酒場", 20: "家"}
MEAL_HOURS = (6, 12, 18)
OUTDOOR = ("畑", "川辺", "森の入口")
FREE_PLACES = ["広場", "広場", "川辺", "酒場", "パン屋", "森の入口"]

GREET_GOOD = ["{t}、元気？", "やあ{t}、今日もいい日だね。", "{t}、ちょっと聞いてよ。"]
GREET_PLAIN = ["{t}か。", "どうも、{t}。", "{t}、何か用？"]
GREET_BAD = ["……ちっ、{t}か。", "{t}、話しかけないでくれる？"]
REPLY_GOOD = ["うんうん、そうだね。", "へえ、そうなんだ！", "あはは、{t}らしいや。", "わかるよ、それ。"]
REPLY_PLAIN = ["ふうん。", "そうか。", "まあ、そういうこともあるさ。"]
REPLY_BAD = ["……あんたには関係ないだろ。", "はいはい。"]
IDLE = {
    "広場": ["井戸のそばのベンチに腰かけている", "広場をぶらぶら歩いている"],
    "川辺": ["川面に石を投げている", "水の流れをぼんやり眺めている"],
    "酒場": ["カウンターで頬杖をついている", "酒場の喧騒に耳を傾けている"],
    "パン屋": ["焼きたてのパンの匂いをかいでいる"],
    "森の入口": ["木々のざわめきに耳を澄ませている", "きのこを探して地面を見ている"],
    "畑": ["畝のあいだを見回っている"],
}
HOME_IDLE = ["家の中を片づけている", "窓の外を眺めている", "繕い物をしている"]
BEG = "ねえ、何か食べるものを分けてくれない？　お腹がぺこぺこで……。"
RAINY = ["雨音を聞きながら道具の手入れをしている", "雨宿りしながら空を見上げている"]


class RuleBrain:
    def take_turn(self, world, name):
        v = world.villagers[name]
        act = lambda tool, **args: run_tool(world, name, tool, args)
        here = v["location"]
        others = world.people_at(here, exclude=name)

        self.react(world, name)

        # 1. 空腹（食事時に食べ物がないときも、早めに手に入れておく）
        no_food = not any(v["inventory"].get(f, 0) for f in FOOD)
        if v["hunger"] >= 6 or (no_food and v["hunger"] >= 3 and world.hour in MEAL_HOURS):
            if self.eat_something(world, name):
                return
            if self.buy_food(world, name, others):
                return
            if v["money"] < 2:  # 金がない：売れる物を売るか、働いて稼ぐ
                if self.sell_something(world, name, others, include_food=False):
                    return
                market = self.find_buyer(world, name)
                if market and market != here:  # 売り物を抱えて、買ってくれそうな人のところへ
                    act("move", destination=market)
                    return
                if here == v["workplace"] and v["energy"] > 1:
                    act("work")
                    return
                if v["energy"] > 1 and 6 <= world.hour <= 16:
                    act("move", destination=v["workplace"])
                    return
            seller_place = self.find_food_seller(world, name)
            if seller_place and seller_place != here and v["money"] >= 1:
                act("move", destination=seller_place)
                return
            if others and v["hunger"] >= 9:
                act("say", to=random.choice(others), message=BEG)
                return

        # 2. 疲労
        if v["energy"] <= 4 and v["inventory"].get("薬草", 0) > 0:
            act("eat", item="薬草")
            return
        if v["energy"] <= 1:
            if here == v["home"]:
                act("rest")
            else:
                act("move", destination=v["home"])
            return

        # 3. 食事時
        if world.hour in MEAL_HOURS and v["hunger"] >= 3 and self.eat_something(world, name):
            return

        # 4. 助け合い：家族には手持ちから、好きな相手には余りから分ける。頼まれたら考える
        begged = {e["actor"] for e in v["inbox"] if e["kind"] == "say" and e["to"] == name and e["quote"] == BEG}
        for o in others:
            family = world.villagers[o]["home"] == v["home"]
            food = self.any_food(world, name) if family else self.spare_food(world, name)
            hungry = world.villagers[o]["hunger"] >= (6 if family or o in begged else 8)
            if food and hungry and (family or self.score(v, o) >= (0 if o in begged else 1)):
                act("give", to=o, item=food, amount=1)
                return

        # 5. 返事
        talker = self.addressed_by(world, name, others)
        if talker and random.random() < v.get("talk", 0.5) + 0.3:
            act("say", to=talker, message=self.reply(v, talker))
            return

        # 5.5 おしゃべり好きなら、予定より会話を優先することもある
        if others and random.random() < v.get("talk", 0.5) * 0.4:
            self.chat(world, name, others)
            return

        # 6. 商売
        if others and random.random() < 0.5 and self.sell_something(world, name, others, include_food=True):
            return
        if others and self.treat_yourself(world, name, others):
            return

        # 7. 習慣
        for habit in v.get("habits", []):
            if world.hour in habit["hours"] and random.random() < habit["chance"]:
                if self.do_habit(world, name, habit, others):
                    return

        # 8. 日課
        self.routine(world, name, others)

    # ---------- 0. 反応 ----------

    def react(self, world, name):
        v = world.villagers[name]
        for e in v["inbox"]:
            actor = e.get("actor")
            if e["kind"] == "give" and e["to"] == name:
                world.update_impression(name, actor, 1, f"{e['quote']}をくれた。いい人だ。")
                world.remember(name, f"{actor}が{e['quote']}をくれた")
            elif e["kind"] == "say" and e["to"] == name and random.random() < 0.15:
                score = self.score(v, actor)
                note = v["impressions"].get(actor, {}).get("note") or "よく話しかけてくる"
                world.update_impression(name, actor, 1 if score >= 0 else -1, note)
            elif (e["kind"] == "say" and e["to"] != name and name in (e.get("quote") or "")
                  and not is_small_talk(world, e["quote"])):
                world.remember(name, f"{actor}が私のことを話していた：「{e['quote']}」")
            elif e["kind"] == "refuse" and e["to"] == name:
                pass  # 断った側は特に気にしない

    # ---------- 1〜4. 体と食べ物 ----------

    def eat_something(self, world, name):
        inv = world.villagers[name]["inventory"]
        food = [f for f in sorted(FOOD, key=FOOD.get) if inv.get(f, 0) > 0]  # 安いものから食べる
        if not food:
            return False
        run_tool(world, name, "eat", {"item": food[0]})
        return True

    def buy_food(self, world, name, others):
        v = world.villagers[name]
        for seller in sorted(others, key=lambda o: -self.score(v, o)):
            for food in FOOD:
                if world.will_sell(seller, name, food) and v["money"] >= PRICES[food]:
                    amount = 2 if world.surplus(seller, food) >= 2 and v["money"] >= PRICES[food] * 2 + 4 else 1
                    result = run_tool(world, name, "buy", {"seller": seller, "item": food, "amount": amount})
                    if "断られた" in result:
                        world.update_impression(name, seller, -1, f"{food}を売ってくれなかった。")
                    return True
        return False

    def find_food_seller(self, world, name):
        """食べ物が余っていそうな人の居場所。"""
        for other, ov in world.villagers.items():
            if other != name and any(world.will_sell(other, name, f) for f in FOOD):
                return ov["location"]
        return None

    def any_food(self, world, name):
        inv = world.villagers[name]["inventory"]
        return next((f for f in FOOD if inv.get(f, 0) > 0), None)

    def sell_something(self, world, name, others, include_food):
        """余っている品を、欲しがりそうな人に売り込む。食べ物は腹を空かせた人にだけ。"""
        for item, n in world.villagers[name]["inventory"].items():
            if item not in PRICES or n <= 0:
                continue
            if item in FOOD:
                if not include_food or world.surplus(name, item) <= 0:
                    continue
                buyers = [o for o in others if world.will_buy(o, item) and world.villagers[o]["hunger"] >= 4]
            else:
                buyers = [o for o in others if world.will_buy(o, item)]
            if buyers:
                run_tool(world, name, "sell", {"buyer": random.choice(buyers), "item": item})
                return True
        return False

    def find_buyer(self, world, name):
        """手持ちの品を買ってくれそうな人の居場所（人の家は除く）。"""
        homes = {ov["home"] for ov in world.villagers.values()}
        goods = [i for i, n in world.villagers[name]["inventory"].items() if n > 0 and i not in FOOD]
        for other, ov in world.villagers.items():
            if other != name and ov["location"] not in homes and any(world.will_buy(other, g) for g in goods):
                return ov["location"]
        return None

    def treat_yourself(self, world, name, others):
        """懐に余裕があれば、酒場で一杯やったり、ほかの人の品を買ったりする。"""
        v = world.villagers[name]
        here = v["location"]
        if here == "酒場" and world.hour >= 16 and v["money"] >= 4 and random.random() < 0.4:
            for seller in others:
                if world.will_sell(seller, name, "エール"):
                    run_tool(world, name, "buy", {"seller": seller, "item": "エール", "amount": 1})
                    return True
        if v["money"] >= 25 and random.random() < 0.4:
            for seller in others:
                for item in PRICES:
                    if item != "エール" and v["inventory"].get(item, 0) < 2 and world.will_sell(seller, name, item):
                        run_tool(world, name, "buy", {"seller": seller, "item": item, "amount": 1})
                        return True
        return False

    def spare_food(self, world, name):
        for f in FOOD:
            if world.surplus(name, f) > 0:
                return f
        return None

    # ---------- 5. 会話 ----------

    def score(self, v, other):
        return v["impressions"].get(other, {"score": 0})["score"]

    def addressed_by(self, world, name, others):
        for e in reversed(world.villagers[name]["inbox"]):
            if e["kind"] == "say" and e["to"] == name and e["actor"] in others:
                return e["actor"]
        return None

    def reply(self, v, talker):
        s = self.score(v, talker)
        pool = REPLY_GOOD if s >= 2 else REPLY_BAD if s <= -2 else REPLY_PLAIN
        if random.random() < 0.4 and v.get("lines"):
            return random.choice(v["lines"])
        return random.choice(pool).format(t=talker)

    def chat(self, world, name, others):
        """誰かに話しかける。噂好きなら、聞いた話を広める。"""
        v = world.villagers[name]
        target = max(others, key=lambda o: self.score(v, o) + random.random() * 3)
        heard = [e for e in v["inbox"] + v.get("rumors", [])
                 if e["kind"] == "say" and e["actor"] not in (name, target)
                 and not is_small_talk(world, e["quote"])]
        if heard and random.random() < v.get("gossip", 0.3):
            e = random.choice(heard)
            msg = f"ねえ聞いた？ {e['actor']}が「{e['quote']}」って言ってたよ。"
        elif v.get("lines") and random.random() < 0.6:
            msg = random.choice(v["lines"])
        else:
            s = self.score(v, target)
            pool = GREET_GOOD if s >= 2 else GREET_BAD if s <= -2 else GREET_PLAIN
            msg = random.choice(pool).format(t=target)
        run_tool(world, name, "say", {"to": target, "message": msg})

    # ---------- 6. 習慣 ----------

    def do_habit(self, world, name, h, others):
        v = world.villagers[name]
        here = v["location"]
        kind = h["type"]
        if kind == "buy":
            if here != h["at"]:
                return False
            for seller in others:
                if world.will_sell(seller, name, h["item"]) and v["money"] >= PRICES[h["item"]]:
                    run_tool(world, name, "buy", {"seller": seller, "item": h["item"], "amount": 1})
                    return True
            return False
        if kind == "talk_to":
            if h["target"] not in others:
                return False
            if "else_text" in h and random.random() < 0.6:
                run_tool(world, name, "do", {"activity": h["else_text"]})
            else:
                run_tool(world, name, "say", {"to": h["target"], "message": random.choice(h["lines"])})
            return True
        if kind == "seek":
            dest = world.villagers[h["target"]]["location"]
            homes = {ov["home"] for ov in world.villagers.values()}
            if dest == here or dest in homes:
                return False  # 人の家には押しかけない
            run_tool(world, name, "move", {"destination": dest})
            return True
        if kind == "do":
            if here != h["at"]:
                return False
            run_tool(world, name, "do", {"activity": h["text"]})
            return True
        return False

    # ---------- 7. 日課 ----------

    def routine(self, world, name, others):
        v = world.villagers[name]
        here = v["location"]
        plan = {**DEFAULT_ROUTINE, **{int(k): p for k, p in v.get("routine", {}).items()}}[world.hour]
        rainy = world.data["weather"] in ("雨", "嵐")
        if plan == "家":
            dest = v["home"]
        elif plan == "仕事場":
            dest = v["workplace"]
            if rainy and dest in OUTDOOR and random.random() < 0.5:
                dest = v["home"]
        elif plan == "自由":
            dest = here if random.random() < 0.4 else random.choice(FREE_PLACES)
        else:
            dest = plan

        lacking = [i for i, n in v.get("needs", {}).items() if v["inventory"].get(i, 0) < n]
        if plan in ("仕事場", v["workplace"]) and lacking:  # 仕事の材料を仕入れる
            item = lacking[0]
            sellers = [o for o in others if world.will_sell(o, name, item)]
            if sellers and v["money"] >= PRICES[item]:
                run_tool(world, name, "buy", {"seller": sellers[0], "item": item,
                                              "amount": min(3, v["money"] // PRICES[item])})
                return
            for other, ov in world.villagers.items():
                if other != name and world.will_sell(other, name, item) and ov["location"] != here:
                    run_tool(world, name, "move", {"destination": ov["location"]})
                    return

        if dest != here:
            run_tool(world, name, "move", {"destination": dest})
        elif here == v["workplace"] and plan in ("仕事場", v["workplace"]) and v["energy"] > 2:
            run_tool(world, name, "work", {})
        elif others and random.random() < v.get("talk", 0.5):
            self.chat(world, name, others)
        elif rainy and here != v["home"]:
            run_tool(world, name, "do", {"activity": random.choice(RAINY)})
        elif here == v["home"]:
            run_tool(world, name, "do", {"activity": random.choice(HOME_IDLE)})
        else:
            run_tool(world, name, "do", {"activity": random.choice(IDLE.get(here, ["ぼんやりしている"]))})


def is_small_talk(world, quote):
    """あいさつや相づちなど、噂にする価値のないセリフか。"""
    if not quote or len(quote) < 8 or quote == BEG or quote.startswith("ねえ聞いた"):
        return True
    templates = GREET_GOOD + GREET_PLAIN + GREET_BAD + REPLY_GOOD + REPLY_PLAIN + REPLY_BAD
    return any(quote == t.format(t=n) for t in templates for n in world.villagers)

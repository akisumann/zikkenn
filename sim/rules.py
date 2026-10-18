"""ルールで動く村人の頭脳。API なしで「基本的にはこう動く」を表す。

毎ターン、まず「ついでの用事」を最大 3 つ済ませ、それから「この 2 時間の過ごし方」を 1 つ選ぶ。
ツールは AI と同じものを使う。

ついでの用事（上から順に、当てはまるものを）
  1. 食べる   … 空腹なら食事をとる。食事時は少しの空腹でも。本当に飢えたら食材をかじる
  2. 買う     … 食事の手持ちがなければ、目の前の人から買っておく
  3. 分ける   … 家族、頼んできた人、好きな人が腹ぺこなら食事を分ける
  4. 仕入れる … 加工する人は、仕事の材料を 2 回分を目安に仕入れる
  5. 売る     … 余った品を欲しがる人に売る（食材は加工する人へ、薪は家々へ、食事は空腹な人へ）
  6. 備える   … 夜の薪がなければ買う。懐に余裕があれば夕方の酒場で料理を頼む

この 2 時間の過ごし方（上から順に、当てはまるものを 1 つ）
  0. 反応     … 見聞きしたことに心を動かす（印象・記憶。ターンは使わない）
  1. 腹ぺこ   … 食事を売っている人のところへ行く。金がなければ売り物を売りに行く
  2. 疲労     … くたくたなら家に帰って休む
  3. 会話     … 話しかけられたら返事をする。話し好きは話しかけ、噂好きは噂を広める。
                仕事の時間は話し込まず仕事場へ。同じ仕事場に人がいれば、働きながら話す
  4. 行商     … 仕事のあと、余った品を買ってくれる人のところへ売りに行く
  5. 習慣     … その人ならではの癖（seed の habits）
  6. 日課     … 時間割どおりの場所へ行き、働く。材料が足りなければ仕入れに行く。
                その日の仕事場は朝に一度だけ決める。本業の品が余っていて、どこかが足りないと
                聞いていれば、そこ（畑・川・森）を手伝う。同じ所で続けて働くと、はかどる

朝は身支度しながら家族と話す（時間は使わない）。村の様子（何が足りない・余っている）は、
自分で見たことと、人から聞いたことでしか知らない。話をすると、それが相手に伝わる。
"""

import random

from .brains import QUICK_LIMIT, run_tool
from .world import CATEGORIES, DAY_HOURS, HELP_JOBS, INGREDIENTS, MEALS, RESERVE

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
CHORES = ["家の掃除をしている", "繕い物をしている", "かまどの火の番をしている", "家族の洗濯物を干している"]
HOME_IDLE = ["家の中を片づけている", "窓の外を眺めている", "繕い物をしている"]
BEG = "ねえ、何か食べるものを分けてくれない？　お腹がぺこぺこで……。"
RAINY = ["雨音を聞きながら道具の手入れをしている", "雨宿りしながら空を見上げている"]


class RuleBrain:
    def take_turn(self, world, name):
        if world.continue_travel(name):  # 遠出の途中なら、このターンは歩くだけ
            return
        self.react(world, name)
        for _ in range(QUICK_LIMIT):  # ついでの用事を済ませてから
            if not self.errand(world, name):
                break
        self.morning_talk(world, name)
        self.main_action(world, name)  # この 2 時間の過ごし方を 1 つ選ぶ

    def morning_talk(self, world, name):
        """朝は身支度しながら家族と話す（時間は使わない）。村の様子はここでも伝わる。"""
        if world.hour != DAY_HOURS[0]:
            return
        v = world.villagers[name]
        family = [o for o in world.people_at(v["location"], exclude=name) if world.family(name, o)]
        if family and random.random() < 0.7:
            talk = self.talk_while_working(world, name, family)
            if talk["message"]:
                run_tool(world, name, "say", talk)

    # ---------- ついでの用事（食べる・買う・売る・渡す） ----------

    def errand(self, world, name):
        v = world.villagers[name]
        here = v["location"]
        others = world.people_at(here, exclude=name)
        meal_time = world.hour in MEAL_HOURS
        has_meal = any(world.food_owner(name, f) for f in MEALS)

        # 1. 空腹なら食べる（食事時は少しの空腹でも）。本当に飢えたら食材をかじる
        if v["hunger"] >= 5 or (meal_time and v["hunger"] >= 3):
            if self.eat_something(world, name) or (v["hunger"] >= 10 and self.eat_something(world, name, raw=True)):
                return True
        # 2. 食事の手持ちがなければ、目の前の人から買っておく
        if not has_meal and v["hunger"] >= 2 and self.buy_food(world, name, others):
            return True
        # 3. 家族や、頼んできた人・好きな人が腹ぺこなら分ける
        if self.share(world, name, others):
            return True
        # 4. 仕事の材料が心もとなければ仕入れる
        if self.restock(world, name, others):
            return True
        # 5. 余った品を、欲しがる人に売る（食材は加工する人へ、薪は家々へ、食事は空腹な人へ）
        if others and self.sell_something(world, name, others, include_food=True):
            return True
        # 6. 夜の薪がなければ買う。懐に余裕があれば夕方の酒場で料理を頼む
        if others and self.treat_yourself(world, name, others):
            return True
        return False

    def share(self, world, name, others):
        v = world.villagers[name]
        begged = {e["actor"] for e in v["inbox"] if e["kind"] == "say" and e["to"] == name and e["quote"] == BEG}
        for o in others:
            family = world.villagers[o]["home"] == v["home"]
            food = self.any_food(world, name) if family else self.spare_food(world, name)
            hungry = world.villagers[o]["hunger"] >= (6 if family or o in begged else 8)
            if food and hungry and (family or self.score(v, o) >= (0 if o in begged else 1)):
                run_tool(world, name, "give", {"to": o, "item": food, "amount": 1})
                return True
        return False

    def restock(self, world, name, others):
        """仕事の材料を、2 回分を目安に仕入れる。"""
        v = world.villagers[name]
        for need, n in v.get("needs", {}).items():
            items = CATEGORIES.get(need, [need])
            if sum(v["inventory"].get(i, 0) for i in items) >= n * 2:
                continue
            for seller in others:
                for item in items:
                    if world.will_sell(seller, name, item) and world.will_buy(name, item):
                        amount = max(1, min(3, world.surplus(seller, item), v["money"] // world.price(item)))
                        run_tool(world, name, "buy", {"seller": seller, "item": item, "amount": amount})
                        return True
        return False

    # ---------- この 2 時間の過ごし方 ----------

    def main_action(self, world, name):
        v = world.villagers[name]
        act = lambda tool, **args: run_tool(world, name, tool, args)
        here = v["location"]
        others = world.people_at(here, exclude=name)
        working = self.plan(world, v) in ("仕事場", v["workplace"]) and v["energy"] > 2  # 仕事の時間

        # 1. 腹ぺこで食事がない：食事を売っている人のところへ。だめなら売り物を売りに行く。それもなければ働く
        has_meal = any(v["inventory"].get(f, 0) for f in MEALS)
        if v["hunger"] >= 6 and not has_meal:
            seller_place = self.find_food_seller(world, name)
            if seller_place and seller_place != here and v["money"] >= min(world.price(m) for m in MEALS):
                act("move", destination=seller_place)
                return
            if self.market_trip(world, name, minimum=1):
                return
            if others and v["hunger"] >= 9 and not working and random.random() < 0.3:
                act("say", to=random.choice(others), message=BEG)
                return

        # 2. 疲労：くたくたなら家に帰って休む
        if v["energy"] <= 1:
            act("rest") if here == v["home"] else act("move", destination=v["home"])
            return

        # 3. 返事・おしゃべり（仕事の時間は、仕事場で働きながら話すので、ここでは話し込まない）
        if not working:
            talker = self.addressed_by(world, name, others)
            if talker and random.random() < v.get("talk", 0.5) + 0.3:
                act("say", to=talker, message=self.reply(v, talker))
                return
            if others and random.random() < v.get("talk", 0.5) * 0.4:
                self.chat(world, name, others)
                return

        # 4. 仕事のあと、余った品を売りに行く
        if world.hour >= 14 and self.market_trip(world, name):
            return

        # 5. 習慣
        for habit in v.get("habits", []):
            if world.hour in habit["hours"] and random.random() < habit["chance"]:
                if self.do_habit(world, name, habit, others):
                    return

        # 6. 日課
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

    def eat_something(self, world, name, raw=False):
        """食事（腹持ちのいい順）をとる。raw なら、売り物でない食材をかじる。"""
        food = [f for f in sorted(MEALS, key=MEALS.get, reverse=True) if world.food_owner(name, f)]
        if raw and not food:
            food = [f for f in INGREDIENTS if world.food_owner(name, f)]
        if not food:
            return False
        run_tool(world, name, "eat", {"item": food[0]})
        return True

    def buy_food(self, world, name, others):
        v = world.villagers[name]
        for seller in sorted(others, key=lambda o: -self.score(v, o)):
            for food in MEALS:
                if world.will_sell(seller, name, food) and v["money"] >= world.price(food):
                    amount = 2 if world.surplus(seller, food) >= 2 and v["money"] >= world.price(food) * 2 + 40 else 1
                    result = run_tool(world, name, "buy", {"seller": seller, "item": food, "amount": amount})
                    if "断られた" in result:
                        world.update_impression(name, seller, -1, f"{food}を売ってくれなかった。")
                    return True
        return False

    def find_food_seller(self, world, name):
        """食べ物が余っていそうな人の居場所。"""
        for other, ov in world.villagers.items():
            if other != name and any(world.will_sell(other, name, f) for f in MEALS):
                return ov["location"]
        return None

    def any_food(self, world, name):
        inv = world.villagers[name]["inventory"]
        return next((f for f in MEALS if inv.get(f, 0) > 0), None)

    def sell_something(self, world, name, others, include_food):
        """余っている品を、欲しがりそうな人に売り込む。食べ物は腹を空かせた人にだけ。"""
        for item, n in world.villagers[name]["inventory"].items():
            if not world.price(item) or n <= 0:
                continue
            if world.surplus(name, item) <= 0 or (item in MEALS and not include_food):
                continue
            buyers = [o for o in others if world.will_buy(o, item) and not world.family(name, o)]
            if buyers:
                run_tool(world, name, "sell", {"buyer": random.choice(buyers), "item": item})
                return True
        return False

    def find_buyer(self, world, name):
        """手持ちの品を買ってくれそうな人の居場所（人の家は除く）。"""
        homes = {ov["home"] for ov in world.villagers.values()}
        goods = [i for i in world.villagers[name]["inventory"] if world.surplus(name, i) > 0 and i not in MEALS]
        for other, ov in world.villagers.items():
            if other != name and ov["location"] not in homes and any(world.will_buy(other, g) for g in goods):
                return ov["location"]
        return None

    def treat_yourself(self, world, name, others):
        """要るものを買う。夜の薪が足りなければ買い、懐に余裕があれば夕方の酒場で料理を頼む。"""
        v = world.villagers[name]
        wants = []
        if world.will_buy(name, "薪") and v["inventory"].get("薪", 0) == 0:
            wants.append("薪")
        if v["location"] == "酒場" and world.hour >= 16 and v["money"] >= 80 and random.random() < 0.5:
            wants.append("料理")
        for item in wants:
            for seller in others:
                if world.will_sell(seller, name, item) and v["money"] >= world.price(item):
                    run_tool(world, name, "buy", {"seller": seller, "item": item, "amount": 1})
                    return True
        return False

    def market_trip(self, world, name, minimum=2):
        """余った品（食材・薪）を抱えて、買ってくれる人のところへ売りに行く。"""
        v = world.villagers[name]
        if sum(world.surplus(name, i) for i in v["inventory"] if i not in MEALS) < minimum:
            return False
        market = self.find_buyer(world, name)
        if market and market != v["location"]:
            run_tool(world, name, "move", {"destination": market})
            return True
        return False

    def spare_food(self, world, name):
        for f in MEALS:
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

    def talk_while_working(self, world, name, others):
        """同じ場所にいる人と、手を動かしながら話す。話しかけられていれば返事をする。"""
        v = world.villagers[name]
        talker = self.addressed_by(world, name, others)
        if talker and random.random() < v.get("talk", 0.5) + 0.3:
            return {"to": talker, "message": self.reply(v, talker)}
        if others and random.random() < v.get("talk", 0.5) * 0.6:
            to, message = self.pick_chat(world, name, others)
            return {"to": to, "message": message}
        return {"to": "", "message": ""}

    def chat(self, world, name, others):
        to, message = self.pick_chat(world, name, others)
        run_tool(world, name, "say", {"to": to, "message": message})

    def pick_chat(self, world, name, others):
        """誰かに話しかける。噂好きなら、聞いた話を広める。"""
        v = world.villagers[name]
        target = max(others, key=lambda o: self.score(v, o) + random.random() * 3)
        heard = [e for e in v["inbox"] + v.get("rumors", [])
                 if e["kind"] == "say" and e["actor"] not in (name, target)
                 and not is_small_talk(world, e["quote"])]
        news = world.recent_news(name)
        if news and random.random() < 0.4:
            item, (state, _, src) = random.choice(list(news.items()))
            msg = f"{item}が{'足りない' if state == '不足' else '余ってる'}{'んだ' if src == '自分で見た' else 'らしいよ'}。"
        elif heard and random.random() < v.get("gossip", 0.3):
            e = random.choice(heard)
            msg = f"ねえ聞いた？ {e['actor']}が「{e['quote']}」って言ってたよ。"
        elif v.get("lines") and random.random() < 0.6:
            msg = random.choice(v["lines"])
        else:
            s = self.score(v, target)
            pool = GREET_GOOD if s >= 2 else GREET_BAD if s <= -2 else GREET_PLAIN
            msg = random.choice(pool).format(t=target)
        return target, msg

    # ---------- 6. 習慣 ----------

    def do_habit(self, world, name, h, others):
        v = world.villagers[name]
        here = v["location"]
        kind = h["type"]
        if kind == "buy":
            if here != h["at"]:
                return False
            for seller in others:
                if world.will_sell(seller, name, h["item"]) and v["money"] >= world.price(h["item"]):
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

    def where_needed(self, world, name):
        """その日の仕事場を、朝に一度だけ決める。
        本業の品が余っていて、どこかが足りないと聞いていれば、そこを手伝いに行く（近い方を選ぶ）。
        余りすぎているのに足りない所を知らなければ、仕事を休んで人の集まる広場へ出る（話を聞くため）。"""
        v = world.villagers[name]
        if v.get("today_job", [None])[0] == world.data["day"]:
            return v["today_job"][1]
        job = v["workplace"]
        over = [i for i in v["produce"] if world.surplus(name, i) >= RESERVE.get(i, 99)]
        if over:
            news = world.recent_news(name)
            short = [place for place, out in HELP_JOBS.items()
                     if not any(i in v["produce"] for i in out)
                     and any(news.get(i, [None])[0] == "不足" for i in out)]
            if short:
                job = min(short, key=lambda p: world.travel_turns(v["home"], p))
                world.log(f"🗓 **{name}** は今日は{job}を手伝うことにした（{'・'.join(over)}が余っているので）")
            elif any(world.surplus(name, i) >= RESERVE[i] * 2 for i in over):
                job = "広場"
                world.log(f"🗓 **{name}** は{'・'.join(over)}が余りすぎているので、今日は仕事を休んだ")
        v["today_job"] = [world.data["day"], job]
        return job

    def plan(self, world, v):
        """時間割で、いまどこにいるべきか。"""
        return {**DEFAULT_ROUTINE, **{int(k): p for k, p in v.get("routine", {}).items()}}[world.hour]

    def routine(self, world, name, others):
        v = world.villagers[name]
        here = v["location"]
        plan = self.plan(world, v)
        if plan == v["workplace"]:
            plan = "仕事場"  # 時間割に仕事場の名前で書いてあっても同じ扱い
        rainy = world.data["weather"] in ("雨", "嵐")
        if plan == "家":
            dest = v["home"]
        elif plan == "仕事場":
            dest = self.where_needed(world, name)
            if rainy and dest in OUTDOOR and random.random() < 0.5:
                dest = v["home"]
        elif plan == "自由":
            dest = here if random.random() < 0.4 else random.choice(FREE_PLACES)
        else:
            dest = plan

        lacking = world.lacking(name)
        if plan in ("仕事場", v["workplace"]) and lacking:  # 仕事の材料を仕入れに行く
            items = CATEGORIES.get(lacking[0], [lacking[0]])
            for seller in others:
                for item in items:
                    if world.will_sell(seller, name, item) and v["money"] >= world.price(item):
                        amount = max(1, min(3, world.surplus(seller, item), v["money"] // world.price(item)))
                        run_tool(world, name, "buy", {"seller": seller, "item": item, "amount": amount})
                        return
            for other, ov in world.villagers.items():
                if other != name and ov["location"] != here and any(world.will_sell(other, name, i) for i in items):
                    run_tool(world, name, "move", {"destination": ov["location"]})
                    return

        if dest != here:
            run_tool(world, name, "move", {"destination": dest})
        elif here == v["workplace"] and plan == "仕事場" and not v["produce"]:
            run_tool(world, name, "do", {"activity": random.choice(CHORES)})  # 品物を作らない人は家のことをする
        elif here == dest and plan == "仕事場" and here in HELP_JOBS and here != v["workplace"] and v["energy"] > 2:
            run_tool(world, name, "work", self.talk_while_working(world, name, others))  # 手伝い仕事
        elif here == v["workplace"] and plan in ("仕事場", v["workplace"]) and v["energy"] > 2 and not lacking:
            run_tool(world, name, "work", self.talk_while_working(world, name, others))
        elif here == v["workplace"] and lacking:
            run_tool(world, name, "do", {"activity": f"{lacking[0]}が届くのを待っている"})
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

"""ルールで動く村人の頭脳。API なしで「基本的にはこう動く」を表す。

毎ターン、まず「ついでの用事」を最大 3 つ済ませ、それから「この 2 時間の過ごし方」を 1 つ選ぶ。
ツールは AI と同じものを使う。

ついでの用事（上から順に、当てはまるものを）
  1. 食べる   … 空腹なら食事をとる。食事時は少しの空腹でも
  2. 買う     … 食事の手持ちがなければ、目の前の人から買っておく
  3. 分ける   … 家族、頼んできた人、好きな人が腹ぺこなら食事を分ける
  4. 仕入れる … 加工する人は、仕事の材料を 2 回分を目安に仕入れる
  5. 売る     … 余った品を欲しがる人に売る（食材は加工する人へ、薪は家々へ、食事は空腹な人へ）
  6. 備える   … 夜の薪がなければ買う。懐に余裕があれば夕方の酒場で料理を頼む

この 2 時間の過ごし方（上から順に、当てはまるものを 1 つ）
  0. 反応     … 見聞きしたことに心を動かす（印象・記憶。ターンは使わない）
  1. 腹ぺこ   … 家なら食材と薪で煮炊きする（夜の薪は残す）。そうでなければ食事を売っている人の
                ところへ行く。金がなければ売り物を売りに行く
  2. 疲労     … くたくたなら家に帰って休む
  3. 会話     … 話しかけられたら返事をする。話し好きは話しかけ、噂好きは噂を広める。
                仕事の時間は話し込まず仕事場へ。同じ仕事場に人がいれば、働きながら話す
  3.5 保存食 … 昼過ぎ、余った魚や肉が傷む前に、魚は川辺で干物に（干せない日は家で燻製に）、
                肉は家で燻製にする（酒場の主人は店の台所で燻製に）
  3.8 納品   … 店に注文された品を持っていれば、店へ届ける
  4. 行商     … 仕事のあと、余った品を買ってくれる人のところへ売りに行く
  5. 習慣     … その人ならではの癖（seed の habits）
  6. 日課     … 時間割どおりの場所へ行き、働く。材料が足りなければ仕入れに行く。
                その日の仕事場は朝に一度だけ決める。本業の品が余っていて、どこかが足りないと
                聞いていれば、そこ（畑・川・森）を手伝う。足りない所がなければ、余った魚や肉を
                干物や燻製にする。それもできず余りすぎていれば休む。同じ所で続けて働くと、はかどる

毎朝 6 時は広場で朝礼。全員の手持ちと困りごとから、村で何が足りない・余っているかがわかり、
その場で受け渡しをする。それ以外の時間に知る村の様子は、自分で見たことと人から聞いたことだけ。
"""

import random

from .brains import QUICK_LIMIT, run_tool
from .world import MAX_MOVES
from .world import CATEGORIES, DAY_HOURS, HELP_JOBS, INGREDIENTS, MEALS, PRESERVE, RESERVE, SNACKS, SPOIL

# 時間割の既定値。「家」「仕事場」「自由」か、場所の名前を書く。seed の routine で上書きできる
DEFAULT_ROUTINE = {6: "広場", 8: "仕事場", 10: "仕事場", 12: "仕事場", 14: "仕事場",
                   16: "自由", 18: "酒場", 20: "家"}
MEAL_HOURS = (6, 12, 18)
OUTDOOR = ("畑", "川辺", "森の入口")
FREE_PLACES = ["広場", "広場", "川辺", "酒場", "パン屋", "森の入口"]

# 口調。村人ごとに seed の style で上書きする（あいさつ・相づち・うわさ・村の様子・物乞いの言い方）
DEFAULT_STYLE = {
    "greet": ["{t}、こんにちは。"], "greet_bad": ["……{t}。"],
    "reply": ["そうなんだ。", "なるほど。"], "reply_bad": ["……そう。"],
    "gossip": "{who}が「{q}」って言ってたよ。", "news": "{item}が{state}らしいよ。",
    "beg": "すまないけど、何か食べるものを分けてくれないか。",
}
STATE_WORD = {"不足": "足りない", "余り": "余ってる"}
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
RAINY = ["雨音を聞きながら道具の手入れをしている", "雨宿りしながら空を見上げている"]


class RuleBrain:
    def take_turn(self, world, name):
        world.begin_turn(name)
        self.react(world, name)
        self.morning_talk(world, name)
        v = world.villagers[name]
        for _ in range(MAX_MOVES + 1):
            for _ in range(QUICK_LIMIT):  # ついでの用事を済ませてから
                if not self.errand(world, name):
                    break
            moves = v.get("moves", 0)
            self.main_action(world, name)  # この 2 時間の過ごし方を 1 つ選ぶ
            if v.get("moves", 0) == moves:  # 移動（20 分）なら、着いた先で続きをする
                break

    def morning_talk(self, world, name):
        """朝礼の場で、まず家族と話す（時間は使わない）。"""
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
            if self.eat_something(world, name):
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

    def cook(self, world, name):
        v = world.villagers[name]
        wood = world.household_stock(name, "薪")
        if wood < 2 and not (wood >= 1 and v["hunger"] >= 8):  # 夜を越す 1 本は残したい
            return False
        for item in INGREDIENTS:
            if world.food_owner(name, item):
                run_tool(world, name, "cook", {"item": item})
                return True
        return False

    def share(self, world, name, others):
        v = world.villagers[name]
        begged = {e["actor"] for e in v["inbox"] if e["kind"] == "say" and e["to"] == name and is_beg(world, e)}
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
        for need, n in world.inputs(name).items():
            items = CATEGORIES.get(need, [need])
            if sum(world.has(name, i) for i in items) >= n * 2 and not any(
                    world.data.get("orders", {}).get(v["workplace"], {}).get(i, 0) for i in items):
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
        has_meal = any(world.food_owner(name, f) for f in MEALS)
        # 0. 家にいて腹が減っていて、店の食事がなければ、家の食材と薪で煮炊きする（夜の薪は残す）
        if here == v["home"] and v["hunger"] >= 4 and not has_meal and self.cook(world, name):
            return
        if v["hunger"] >= 6 and not has_meal:
            seller_place = self.find_food_seller(world, name)
            if seller_place and seller_place != here and v["money"] >= min(world.price(m) for m in MEALS):
                act("move", destination=seller_place)
                return
            if self.market_trip(world, name, minimum=1):
                return
            if others and v["hunger"] >= 9 and not working and random.random() < 0.3:
                act("say", to=random.choice(others), message=style(v)["beg"], small=True)
                return

        # 2. 疲労：くたくたなら家に帰って休む
        if v["energy"] <= 1:
            act("rest") if here == v["home"] else act("move", destination=v["home"])
            return

        # 3. 返事・おしゃべり（仕事の時間は、仕事場で働きながら話すので、ここでは話し込まない）
        if not working:
            talker = self.addressed_by(world, name, others)
            if talker and random.random() < v.get("talk", 0.5) + 0.3:
                message, small = self.reply(world, name, talker)
                act("say", to=talker, message=message, small=small)
                return
            if others and random.random() < v.get("talk", 0.5) * 0.4:
                self.chat(world, name, others)
                return

        # 3.5 昼過ぎ、余った魚や肉が傷む前に、干物や燻製にする
        item = self.preserve_plan(world, name) if world.hour in (14, 16) else None
        if item:
            rule = PRESERVE[item]
            place = v["home"] if rule["place"] == "家" else rule["place"]
            if world.at_order_shop(name):
                place = here  # 酒場の主人は店の台所で
            if here == place:
                act("preserve", item=item)
                return
            act("move", destination=place)
            return

        # 3.8 店に注文された品を持っていれば、届けに行く
        shop = self.delivery_target(world, name)
        if shop and shop != here:
            act("move", destination=shop)
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
                  and not is_small_talk(e)):
                world.remember(name, f"{actor}が私のことを話していた：「{e['quote']}」")
            elif e["kind"] == "refuse" and e["to"] == name:
                pass  # 断った側は特に気にしない

    # ---------- 1〜4. 体と食べ物 ----------

    def eat_something(self, world, name):
        """食事をとる。傷みやすいものから先に、同じなら腹持ちのいいものから。"""
        food = [f for f in sorted(MEALS, key=lambda f: (-SPOIL.get(f, 0), -MEALS[f])) if world.food_owner(name, f)]
        if not food and world.villagers[name]["hunger"] >= 5:  # 食事がなければ、燻製をかじってしのぐ
            food = [f for f in SNACKS if world.food_owner(name, f)]
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
        if world.will_buy(name, "薪"):  # 今夜の分がなければ必ず、余裕があれば何晩分か
            wants.append("薪")
        if v["location"] == "酒場" and world.hour >= 16 and v["money"] >= 80 and random.random() < 0.5:
            wants.append("料理")
        for item in wants:
            for seller in others:
                if world.will_sell(seller, name, item) and v["money"] >= world.price(item):
                    run_tool(world, name, "buy", {"seller": seller, "item": item, "amount": 1})
                    return True
        return False

    def delivery_target(self, world, name):
        """持っている品を注文している店（仕事を一区切りした 10 時以降）。"""
        if world.hour < 10:
            return None
        for shop, order in world.data.get("orders", {}).items():
            owner = world.shop_owner(shop)
            if owner == name or world.villagers[owner]["location"] != shop:  # 主人が店にいなければ行かない
                continue
            if any(q > 0 and world.surplus(name, i) > 0 and world.will_buy(owner, i) for i, q in order.items()):
                return shop
        return None

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

    def reply(self, world, name, talker):
        """返事をする。たまに口癖で返す。セリフは、その人の口調と相手の呼び方で。"""
        v = world.villagers[name]
        lines = lines_for(v, talker)
        if random.random() < 0.3 and lines:
            return random.choice(lines), False
        pool = style(v)["reply_bad" if self.score(v, talker) <= -2 else "reply"]
        return random.choice(pool).format(t=address(world, name, talker)), True

    def talk_while_working(self, world, name, others):
        """同じ場所にいる人と、手を動かしながら話す。話しかけられていれば返事をする。"""
        v = world.villagers[name]
        talker = self.addressed_by(world, name, others)
        if talker and random.random() < v.get("talk", 0.5) + 0.3:
            message, small = self.reply(world, name, talker)
            return {"to": talker, "message": message, "small": small}
        if others and random.random() < v.get("talk", 0.5) * 0.6:
            to, message, small = self.pick_chat(world, name, others)
            return {"to": to, "message": message, "small": small}
        return {"to": "", "message": ""}

    def chat(self, world, name, others):
        to, message, small = self.pick_chat(world, name, others)
        run_tool(world, name, "say", {"to": to, "message": message, "small": small})

    def pick_chat(self, world, name, others):
        """誰かに話しかける。(相手, セリフ, 噂にする価値のない小話か) を返す。
        村の様子を伝える／噂を広める／口癖を言う／あいさつする、のどれか。"""
        v = world.villagers[name]
        st = style(v)
        targeted = [(l["to"], l["text"]) for l in v.get("lines", []) if isinstance(l, dict) and l.get("to") in others]
        if targeted and random.random() < 0.3:  # その人にだけ言いたいことがある
            to, text = random.choice(targeted)
            return to, text, False
        target = max(others, key=lambda o: self.score(v, o) + random.random() * 3)
        heard = [e for e in v["inbox"] + v.get("rumors", [])
                 if e["kind"] == "say" and e["actor"] not in (name, target) and e["to"] not in (name, target)
                 and not is_small_talk(e)]  # 自分に言われたこと・相手に言われたことは言いふらさない
        news = world.recent_news(name)
        if news and random.random() < 0.4:
            item, (state, _, _) = random.choice(list(news.items()))
            return target, st["news"].format(item=item, state=STATE_WORD[state]), True
        if heard and random.random() < v.get("gossip", 0.3):
            e = random.choice(heard)
            return target, st["gossip"].format(who=address(world, name, e["actor"]), q=e["quote"]), True
        lines = lines_for(v, target)
        if lines and random.random() < 0.6:
            return target, random.choice(lines), False
        pool = st["greet_bad" if self.score(v, target) <= -2 else "greet"]
        return target, random.choice(pool).format(t=address(world, name, target)), True

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
        if world.inputs(name):  # 店の主人は店にいる（作るかどうかは売れ行き次第）
            v["today_job"] = [world.data["day"], job]
            return job
        # 売れ残り：生の品だけでなく、自分で作った干物・燻製も（家の蔵の分も含めて）
        unsold = {i: world.surplus(name, i) + world.home_stock(name, i) for i in world.made_goods(name)}
        over = [i for i, n in unsold.items() if n >= RESERVE.get(i, 99)]
        if over:
            news = world.recent_news(name)
            short = [place for place, out in HELP_JOBS.items()
                     if not any(i in world.outputs(name) for i in out)
                     and any(news.get(i, [None])[0] == "不足" for i in out)]
            if short:
                job = short[0]
                world.log(f"🗓 **{name}** は今日は{job}を手伝うことにした（{'・'.join(over)}が余っているので）")
            elif self.preserve_plan(world, name) and not any(i not in world.outputs(name) for i in over):
                item = self.preserve_plan(world, name)
                rule = PRESERVE[item]
                job = v["home"] if rule["place"] == "家" else rule["place"]
                world.log(f"🗓 **{name}** は{item}が余っているので、今日は保存食を作ることにした")
                v["today_job"] = [world.data["day"], job, item]
                return job
            elif any(i not in world.outputs(name) or unsold[i] >= RESERVE[i] * 2 for i in over):
                job = "広場"
                world.log(f"🗓 **{name}** は{'・'.join(over)}が売れ残っているので、今日は仕事を休んだ")
        v["today_job"] = [world.data["day"], job]
        return job

    def preserve_plan(self, world, name):
        """余った魚や肉を干物・燻製にできるなら、作るもの（干物・燻製魚・燻製肉）を返す。
        魚は晴れていれば川辺で干物に（薪がいらない）、干せない日は家で燻製に。"""
        for make, rule in PRESERVE.items():
            if world.data["weather"] in rule["weather_ng"]:
                continue
            enough = all((world.household_stock(name, n) if n == "薪" else world.has(name, n)) >= k
                         for n, k in rule["needs"].items())
            piled = world.surplus(name, make) + world.home_stock(name, make) >= RESERVE.get(make, 99)
            if enough and world.surplus(name, rule["from"]) >= 2 and not piled:  # 売れ残っていれば作らない
                return make
        return None

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
        shop = world.inputs(name) and here == v["workplace"]

        if dest != here:
            run_tool(world, name, "move", {"destination": dest})
        elif plan == "仕事場" and len(v.get("today_job", [])) > 2 and here == dest:
            item = v["today_job"][2]  # 保存食づくりの日
            if self.preserve_plan(world, name) == item:
                run_tool(world, name, "preserve", {"item": item})
            else:
                run_tool(world, name, "do", {"activity": random.choice(IDLE.get(here, HOME_IDLE))})
        elif here == v["workplace"] and plan == "仕事場" and not world.outputs(name):
            run_tool(world, name, "do", {"activity": random.choice(CHORES)})  # 品物を作らない人は家のことをする
        elif here == dest and plan == "仕事場" and here in HELP_JOBS and here != v["workplace"] and v["energy"] > 2:
            run_tool(world, name, "work", self.talk_while_working(world, name, others))  # 手伝い仕事
        elif shop and world.at_order_shop(name) and self.preserve_plan(world, name):
            run_tool(world, name, "preserve", {"item": self.preserve_plan(world, name)})  # 手が空いたら燻製を作る
        elif shop and world.at_order_shop(name):
            run_tool(world, name, "do", {"activity": "店番をしている（注文が来たら料理を出す）"})
        elif shop and not world.needs_more_goods(here):
            run_tool(world, name, "do", {"activity": "店番をしている（今日の分はもう作った）"})
        elif here == v["workplace"] and plan in ("仕事場", v["workplace"]) and v["energy"] > 2 and not lacking:
            run_tool(world, name, "work", self.talk_while_working(world, name, others))
        elif shop and lacking:
            run_tool(world, name, "do", {"activity": f"{lacking[0]}が届くのを待っている"})
        elif others and random.random() < v.get("talk", 0.5):
            self.chat(world, name, others)
        elif rainy and here != v["home"]:
            run_tool(world, name, "do", {"activity": random.choice(RAINY)})
        elif here == v["home"]:
            run_tool(world, name, "do", {"activity": random.choice(HOME_IDLE)})
        else:
            run_tool(world, name, "do", {"activity": random.choice(IDLE.get(here, ["ぼんやりしている"]))})


def style(v):
    return {**DEFAULT_STYLE, **v.get("style", {})}


def address(world, speaker, target):
    """speaker が target を呼ぶときの呼び名。決まっていなければ、15 歳以上年上ならさん付け。"""
    v = world.villagers[speaker]
    if target in v.get("call", {}):
        return v["call"][target]
    if world.villagers[target]["age"] - v["age"] >= 15:
        return f"{target}さん"
    return target


def lines_for(v, target):
    """target に向かって言える口癖。宛先つきのものはその人にだけ、not_to のものはその人以外に。"""
    out = []
    for line in v.get("lines", []):
        if isinstance(line, str):
            out.append(line)
        elif line.get("to") == target or (line.get("not_to") and line["not_to"] != target):
            out.append(line["text"])
    return out


def is_beg(world, e):
    return e.get("actor") in world.villagers and e.get("quote") == style(world.villagers[e["actor"]])["beg"]


def is_small_talk(e):
    """あいさつ・相づち・噂話・村の様子の話など、噂として広める価値のないセリフか。"""
    return e.get("small") or not e.get("quote") or len(e["quote"]) < 8

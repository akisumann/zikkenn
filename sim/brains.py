"""村人が使えるツールと、Claude で動く村人の頭脳。

- ClaudeBrain: 村人ひとりひとりを Claude のエージェントとして動かす（--ai）
- ルールで動く頭脳は rules.py（既定）
"""

import os


MODEL = os.environ.get("VILLAGE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("VILLAGE_EFFORT", "low")
MAX_STEPS = 6  # 1 ターンで API を呼ぶ回数の上限（内面ツールを何度か使ってから行動する余地）


def _tool(name, description, properties):
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


S = {"type": "string"}
I = {"type": "integer"}

# この 2 時間の過ごし方を決めるツール。どれか 1 つを使うとターンが終わる。
ACTION_TOOLS = [
    _tool("move", "別の場所へ移動する。近い場所は 2 時間、遠い場所（村の外れどうし）は 4 時間かかる。", {
        "destination": {**S, "description": "村の場所の名前"}}),
    _tool("say", "その場にいる人に話しかける。その場の全員に聞こえる。", {
        "to": {**S, "description": "話しかける相手の名前。全員に向けるなら「みんな」、独り言なら「ひとりごと」"},
        "message": {**S, "description": "口に出すセリフ（あなたらしい口調で、1〜3 文）"},
    }),
    _tool("work", "仕事場で仕事をする。生産物が手に入るが疲れる。同じ場所にいる人と、働きながら話すこともできる。", {
        "to": {**S, "description": "働きながら話しかける相手。話さないなら空文字"},
        "message": {**S, "description": "働きながら口にするセリフ。話さないなら空文字"},
    }),
    _tool("cook", "家で、食材 1 つと薪 1 本を使って煮炊きし、その場で食べる（麦→麦粥、魚→焼き魚、肉→焼き肉）。家族の食材や薪も使える。", {
        "item": {**S, "description": "麦・魚・肉のどれか"}}),
    _tool("preserve", "時間を使って保存食を作る。川辺で魚 2 匹を干物 2 つに（雨・嵐・霧の日は不可）、家で肉 2 つと薪 1 本を燻製肉 2 つに。保存食は傷まない。", {
        "item": {**S, "description": "魚 または 肉"}}),
    _tool("rest", "その場で休んで元気を回復する。", {}),
    _tool("do", "上のどれにも当てはまらないことをする（散歩、歌う、考え込む、掃除する、など）。", {
        "activity": {**S, "description": "何をしているかの描写（例：「井戸のそばで空を見上げている」）"},
    }),
]
# ついでにできる小さな用事。2 時間を使わず、1 回のターンで QUICK_LIMIT 回まで使える。
QUICK_TOOLS = [
    _tool("eat", "持っている食べ物を 1 つ食べる。", {"item": {**S, "description": "料理・サンドイッチ・パン・燻製肉・干物。麦・魚・肉は生では食べられない（家で cook する）"}}),
    _tool("give", "その場にいる人に物や銀貨を渡す。取引や贈り物に使う。", {
        "to": S, "item": {**S, "description": "持ち物の名前、または「銀貨」"}, "amount": I,
    }),
    _tool("buy", "その場にいる人から、村の相場で物を買う。相手に余りがなければ断られる。", {
        "seller": S, "item": {**S, "description": "料理・サンドイッチ・パン・麦・魚・肉・薪"}, "amount": I,
    }),
    _tool("sell", "その場にいる人に、持ち物を 1 つ村の相場で売り込む。要らなければ断られる。", {
        "buyer": S, "item": S,
    }),
]
QUICK_LIMIT = 3
# 心の中の動き。ターンを消費しないので、行動の前に何度か使える。
INNER_TOOLS = [
    _tool("remember", "覚えておきたいことを記憶メモに書く。明日以降も読み返せるのはこのメモだけ。", {
        "note": {**S, "description": "一人称で簡潔に（例：「アヤメは都から逃げてきたらしい」）"},
    }),
    _tool("update_impression", "ある人への印象を変える。", {
        "target": S,
        "change": {**I, "description": "-2〜+2"},
        "note": {**S, "description": "その人をいまどう思っているか"},
    }),
]
TOOLS = ACTION_TOOLS + QUICK_TOOLS + INNER_TOOLS
ACTION_NAMES = {t["name"] for t in ACTION_TOOLS}
QUICK_NAMES = {t["name"] for t in QUICK_TOOLS}


def run_tool(world, name, tool, args):
    """ツール呼び出しを世界に反映し、村人に返す結果の文章を返す。"""
    if tool == "move":
        return world.act_move(name, args["destination"])
    if tool == "say":
        return world.act_say(name, args["to"], args["message"], small=args.get("small", False))
    if tool == "work":
        result = world.act_work(name)
        if args.get("message") and args.get("to"):
            result += " " + world.act_say(name, args["to"], args["message"], small=args.get("small", False))
        return result
    if tool == "eat":
        return world.act_eat(name, args["item"])
    if tool == "give":
        return world.act_give(name, args["to"], args["item"], args["amount"])
    if tool == "buy":
        return world.act_buy(name, args["seller"], args["item"], args["amount"])
    if tool == "sell":
        return world.act_sell(name, args["buyer"], args["item"])
    if tool == "cook":
        return world.act_cook(name, args["item"])
    if tool == "preserve":
        return world.act_preserve(name, args["item"])
    if tool == "rest":
        return world.act_rest(name)
    if tool == "do":
        return world.act_do(name, args["activity"])
    if tool == "remember":
        return world.remember(name, args["note"])
    if tool == "update_impression":
        return world.update_impression(name, args["target"], args["change"], args["note"])
    return f"{tool} という行動はない。"


def work_text(world, name):
    recipes = world.recipes(name)
    if not recipes:
        return "品物は作らず、家のことをして家族と暮らしている。"
    def one(r):
        made = "、".join(f"{k}×{n}" for k, n in r["produce"].items())
        need = "、".join(f"{k}×{n}" for k, n in r["needs"].items())
        return f"{need}で{made}" if need else made
    return "仕事をすると " + " / ".join(one(r) for r in recipes) + " ができる（材料がそろっている上のものから作る）。"


def habits_text(v):
    lines = []
    if v.get("routine"):
        lines.append("- 時間割の変更：" + "、".join(f"{h}時は{p}" for h, p in v["routine"].items()))
    lines.append("- 基本の一日：朝は広場の朝礼、8〜14時は仕事場で働き、夕方は自由、日暮れは酒場に集まり、夜は家に帰る。")
    lines += [f"- {h['desc']}" for h in v.get("habits", [])]
    if v.get("lines"):
        def one(l):
            if isinstance(l, str):
                return f"「{l}」"
            return f"「{l['text']}」（{l['to']}にだけ）" if l.get("to") else f"「{l['text']}」（{l['not_to']}には言わない）"
        lines.append("- 口癖：" + " / ".join(one(l) for l in v["lines"]))
    st = v.get("style", {})
    if st.get("greet"):
        lines.append("- 話し方の例：" + " / ".join(f"「{x.format(t='○○')}」" for x in st["greet"][:2] + st.get("reply", [])[:2]))
    if v.get("call"):
        lines.append("- 人の呼び方：" + "、".join(f"{k}は「{c}」" for k, c in v["call"].items()))
    return "\n".join(lines)


def system_prompt(world, name):
    v = world.villagers[name]
    return f"""あなたは{world.data['name']}に暮らす村人「{name}」です。{world.data['description']}

## あなた
- {v['age']}歳、{v['job']}。家は「{v['home']}」、仕事場は「{v['workplace']}」。
- {work_text(world, name)}
- 性格：{v['personality']}
- 願い：{v['goal']}

## ふだんの暮らし（基本はこう動くが、状況しだいで変えてよい）
{habits_text(v)}

## この世界での過ごし方
これはシミュレーションです。2 時間ごとに、あなたは「いまの状況」を受け取り、次の 2 時間に何をするかをツールで決めます。
- 行動ツール（move / say / work / cook / preserve / rest / do）は 1 回につき 1 つだけ使えます。使った時点でこの 2 時間は終わります。
- 小さな用事（eat / give / buy / sell）は 2 時間を使わず、行動の前に {QUICK_LIMIT} つまでできます。
- remember と update_impression は心の中の動きなので、行動の前に何度でも使えます。大事な出来事や秘密、約束は remember に残してください。あなたが明日以降に思い出せるのは、記憶メモだけです。
- 空腹が 10 に近づくとつらくなります。食事はパン屋のパン・サンドイッチと酒場の料理で、麦・魚・肉・薪を材料に作られます。食材は家で薪を使って煮炊きしても食べられますが、薪 1 本で 1 人前なので、店より薪を食います。食べ物は自分で作るか、人から買うか、分けてもらいます。村の相場は状況欄に出ます。値引きや物々交換は話し合いと give で行ってください。
- 家族の食べ物は家族みんなのものです。家にいるときは、家族の誰が持っている食べ物でも食べられます。家族とは売り買いせず、分け合います。
- 毎朝 6 時は広場で朝礼です。全員が集まり、村で何が足りない・余っているかがわかります。困っていることがあれば、この場で受け渡しや相談をしてください。
- 料理・サンドイッチは一晩で半分、魚は 4 割、肉は 3 割、パンは 2 割が傷みます。干物と燻製肉は傷みません。
- 薪は傷まないので、家に何晩分か貯めておけます。
- 同じ仕事場で続けて働くと、段取りがよくなって実入りが増えます。
- 村で何が足りない・余っているかは、自分で見たことと人から聞いたことでしかわかりません（状況欄の「知っている村の様子」）。話をすると、あなたの知っている様子も相手に伝わります。
- 夜 22 時になると、全員が自動で家に帰って眠ります。一家で薪を 1 本燃やせば暖かくよく眠れますが、なければ冷えてあまり疲れが取れません。

## 心がけ
- {name}として、その性格と願いのとおりに、自分で考えて動いてください。物語の都合や、誰かを喜ばせることより、{name}らしさを優先します。
- 話すときは、その場にいる人にだけ話しかけられます。セリフは自然な日本語の話し言葉で、あなたらしい口調にしてください。
- 知らないことは知りません。見聞きしたことと記憶メモだけを頼りにしてください。
- 毎回必ずツールを使って行動を決めてください。
"""


class ClaudeBrain:
    def __init__(self):
        try:
            import anthropic
        except ImportError as e:
            raise SystemExit("anthropic パッケージが必要です: pip install anthropic") from e
        self.client = anthropic.Anthropic()

    def take_turn(self, world, name):
        if world.continue_travel(name):  # 遠出の途中なら、このターンは歩くだけ
            return
        messages = [{"role": "user", "content": world.perceive(name)}]
        system = system_prompt(world, name)
        quick_used = 0
        for _ in range(MAX_STEPS):
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": EFFORT},
                cache_control={"type": "ephemeral"},
                system=system,
                tools=TOOLS,
                messages=messages,
            )
            if response.stop_reason == "refusal":
                world.act_do(name, "ぼんやりと考えごとをしている")
                return
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:  # ツールを使わずに終わった
                world.act_do(name, "ぼんやりと過ごしている")
                return

            results = []
            acted = False
            for block in tool_uses:
                if block.name in ACTION_NAMES and acted:
                    text = "この 2 時間はもう別の行動をした。"
                elif block.name in QUICK_NAMES and quick_used >= QUICK_LIMIT:
                    text = f"小さな用事は 1 回に {QUICK_LIMIT} つまで。あとは行動を 1 つ選ぶこと。"
                else:
                    quick_used += block.name in QUICK_NAMES
                    text = run_tool(world, name, block.name, block.input)
                    acted = acted or block.name in ACTION_NAMES
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text})
            if acted:
                return
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": results})
        world.act_do(name, "迷ったまま時間が過ぎた")

"""村人が使えるツールと、Claude で動く村人の頭脳。

- ClaudeBrain: 村人ひとりひとりを Claude のエージェントとして動かす（--ai）
- ルールで動く頭脳は rules.py（既定）
"""

import os

from .world import PRICES

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

# この時間の行動を決めるツール。どれか 1 つを使うとターンが終わる。
ACTION_TOOLS = [
    _tool("move", "別の場所へ移動する。", {"destination": {**S, "description": "村の場所の名前"}}),
    _tool("say", "その場にいる人に話しかける。その場の全員に聞こえる。", {
        "to": {**S, "description": "話しかける相手の名前。全員に向けるなら「みんな」、独り言なら「ひとりごと」"},
        "message": {**S, "description": "口に出すセリフ（あなたらしい口調で、1〜3 文）"},
    }),
    _tool("work", "自分の仕事場で仕事をする。生産物が手に入るが疲れる。", {}),
    _tool("eat", "持っている食べ物や薬草を 1 つ口にする。", {"item": {**S, "description": "シチュー・パン・肉・魚・野菜・山菜（空腹が減る）、薬草（元気が戻る）"}}),
    _tool("give", "その場にいる人に物や銀貨を渡す。取引や贈り物に使う。", {
        "to": S, "item": {**S, "description": "持ち物の名前、または「銀貨」"}, "amount": I,
    }),
    _tool("buy", "その場にいる人から、村の相場で物を買う。相手に余りがなければ断られる。", {
        "seller": S, "item": {**S, "description": "シチュー・パン・肉・魚・野菜・山菜・薬草・エール・薪"}, "amount": I,
    }),
    _tool("sell", "その場にいる人に、持ち物を 1 つ村の相場で売り込む。要らなければ断られる。", {
        "buyer": S, "item": S,
    }),
    _tool("rest", "その場で休んで元気を回復する。", {}),
    _tool("do", "上のどれにも当てはまらないことをする（散歩、歌う、考え込む、掃除する、など）。", {
        "activity": {**S, "description": "何をしているかの描写（例：「井戸のそばで空を見上げている」）"},
    }),
]
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
TOOLS = ACTION_TOOLS + INNER_TOOLS
ACTION_NAMES = {t["name"] for t in ACTION_TOOLS}


def run_tool(world, name, tool, args):
    """ツール呼び出しを世界に反映し、村人に返す結果の文章を返す。"""
    if tool == "move":
        return world.act_move(name, args["destination"])
    if tool == "say":
        return world.act_say(name, args["to"], args["message"])
    if tool == "work":
        return world.act_work(name)
    if tool == "eat":
        return world.act_eat(name, args["item"])
    if tool == "give":
        return world.act_give(name, args["to"], args["item"], args["amount"])
    if tool == "buy":
        return world.act_buy(name, args["seller"], args["item"], args["amount"])
    if tool == "sell":
        return world.act_sell(name, args["buyer"], args["item"])
    if tool == "rest":
        return world.act_rest(name)
    if tool == "do":
        return world.act_do(name, args["activity"])
    if tool == "remember":
        return world.remember(name, args["note"])
    if tool == "update_impression":
        return world.update_impression(name, args["target"], args["change"], args["note"])
    return f"{tool} という行動はない。"


def habits_text(v):
    lines = []
    if v.get("routine"):
        lines.append("- 時間割の変更：" + "、".join(f"{h}時は{p}" for h, p in v["routine"].items()))
    lines.append("- 基本の一日：朝は家、8〜14時は仕事場で働き、夕方は自由、日暮れは酒場に集まり、夜は家に帰る。")
    lines += [f"- {h['desc']}" for h in v.get("habits", [])]
    if v.get("lines"):
        lines.append("- 口癖：" + " / ".join(f"「{l}」" for l in v["lines"]))
    return "\n".join(lines)


def system_prompt(world, name):
    v = world.villagers[name]
    return f"""あなたは{world.data['name']}に暮らす村人「{name}」です。{world.data['description']}

## あなた
- {v['age']}歳、{v['job']}。家は「{v['home']}」、仕事場は「{v['workplace']}」。
- 仕事をすると{"、".join(f"{k}×{n}" for k, n in v["produce"].items())}が手に入る。{"仕事には毎回" + "、".join(f"{k}×{n}" for k, n in v["needs"].items()) + "が要る。" if v.get("needs") else ""}
- 性格：{v['personality']}
- 願い：{v['goal']}

## ふだんの暮らし（基本はこう動くが、状況しだいで変えてよい）
{habits_text(v)}

## この世界での過ごし方
これはシミュレーションです。2 時間ごとに、あなたは「いまの状況」を受け取り、次の 2 時間に何をするかをツールで決めます。
- 行動ツール（move / say / work / eat / give / buy / sell / rest / do）は 1 回につき 1 つだけ使えます。使った時点でこの 2 時間は終わります。
- remember と update_impression は心の中の動きなので、行動の前に何度でも使えます。大事な出来事や秘密、約束は remember に残してください。あなたが明日以降に思い出せるのは、記憶メモだけです。
- 空腹が 10 に近づくとつらくなります。食べ物は自分で作るか、人から買うか、分けてもらいます。村の相場は {"、".join(f"{k} {p}枚" for k, p in PRICES.items())}。値引きや物々交換は話し合いと give で行ってください。
- 夜 22 時になると、全員が自動で家に帰って眠ります。薪を 1 本燃やせば暖かくよく眠れますが、なければ冷えてあまり疲れが取れません。

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
        messages = [{"role": "user", "content": world.perceive(name)}]
        system = system_prompt(world, name)
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
                else:
                    text = run_tool(world, name, block.name, block.input)
                    acted = acted or block.name in ACTION_NAMES
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": text})
            if acted:
                return
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": results})
        world.act_do(name, "迷ったまま時間が過ぎた")

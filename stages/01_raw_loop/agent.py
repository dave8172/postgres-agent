"""Stage 1: an agent with no framework. Just a loop.

    python stages/01_raw_loop/agent.py "Which film category earns the most?"

The whole idea of an agent is in run() below:
  1. send the conversation so far (plus the tool menu) to the model
  2. if the model asks for tools, run them and append the results
  3. repeat until the model answers instead of asking
Everything else in this file is printing, so you can watch it happen.
In VS Code, put a breakpoint on the `response = ...` line and press F5 to
stop at every turn and look inside `messages`.
"""

import json
import os
import sys
import time
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from common.db import FUNCTIONS, TOOLS  # noqa: E402  (the same tools every stage uses)

MODEL = os.environ.get("MODEL", "claude-haiku-4-5")
MAX_TURNS = 10  # a budget: an agent that never stops answering is a bill that never stops
PRICES = {"claude-haiku-4-5": (1.00, 5.00), "claude-sonnet-5-5": (2.00, 10.00)}  # $ per 1M tokens, in / out

SYSTEM = """You answer questions about a DVD rental shop's Postgres database (Pagila).
Look before you write SQL: list the tables, describe the ones you need, then query.
If a query fails, read the error and fix it. Check that your result makes sense before answering.
Final answer: one or two plain sentences, then the SQL that produced it."""


def show(label: str, text: str, max_lines: int = 12) -> None:
    lines = str(text).splitlines() or [""]
    cut = lines[:max_lines] + ([f"... ({len(lines) - max_lines} more lines)"] if len(lines) > max_lines else [])
    print(f"  {label} " + ("\n" + " " * (len(label) + 3)).join(cut))


def run(question: str) -> str:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment / .env
    messages = [{"role": "user", "content": question}]
    tokens_in = tokens_out = 0

    for turn in range(1, MAX_TURNS + 1):
        print(f"\n── turn {turn} " + "─" * 40)

        # (1) The model sees: the system prompt, the tool menu, and every message so far.
        # It keeps no memory between calls; this list IS its memory.
        response = client.messages.create(
            model=MODEL, max_tokens=4000, system=SYSTEM, tools=TOOLS, messages=messages
        )
        tokens_in += response.usage.input_tokens
        tokens_out += response.usage.output_tokens
        print(f"  [{response.usage.input_tokens} tokens in, {response.usage.output_tokens} out, "
              f"stop_reason={response.stop_reason}]")

        # The reply is a list of blocks: "text" (it talking) and "tool_use" (it asking for a tool).
        for block in response.content:
            if block.type == "text" and block.text.strip():
                show("model:", block.text)
            elif block.type == "tool_use":
                show("asks →", f"{block.name}({json.dumps(block.input)})")

        # Keep the model's reply in the history, tool requests included.
        messages.append({"role": "assistant", "content": response.content})

        # (3) No tool requests means it's done: this is the exit from the loop.
        if response.stop_reason != "tool_use":
            report(messages, tokens_in, tokens_out, turn)
            return "".join(b.text for b in response.content if b.type == "text")

        # (2) Run every tool it asked for. The results go back as ONE user message,
        # each tagged with the id of the request it answers.
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = FUNCTIONS[block.name](**block.input)
                show("result:", output, max_lines=8)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                    "is_error": output.startswith("Error:"),
                })
        messages.append({"role": "user", "content": results})

    report(messages, tokens_in, tokens_out, MAX_TURNS)
    return f"Stopped: no answer after {MAX_TURNS} turns."


def report(messages: list, tokens_in: int, tokens_out: int, turns: int) -> None:
    price_in, price_out = PRICES.get(MODEL, (0, 0))
    cost = tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out
    print(f"\n── done: {turns} turns, {tokens_in} tokens in, {tokens_out} out, ~${cost:.4f} ({MODEL})")

    # Save the whole conversation. Reading these files is how you debug an agent,
    # and in the observability stage a tool will do this for us.
    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    path = runs / f"{time.strftime('%Y%m%d-%H%M%S')}-stage1.json"
    plain = [{"role": m["role"], "content": [c if isinstance(c, dict) else c.model_dump() for c in m["content"]]}
             if isinstance(m["content"], list) else m for m in messages]
    path.write_text(json.dumps({"model": MODEL, "tokens_in": tokens_in, "tokens_out": tokens_out,
                                "cost_usd": round(cost, 5), "messages": plain}, indent=2, default=str))
    print(f"   transcript: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Which film category brings in the most rental revenue?"
    print(f"Q: {question}")
    run(question)  # returns the answer too; the evals stage will use that

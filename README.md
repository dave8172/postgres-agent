# postgres-agent

**One AI agent, built three ways, then benchmarked.**

The agent answers plain-English questions about a Postgres database. It looks at the tables, writes
SQL, reads its own errors, fixes them, checks the result, and answers with the query it used. The
database is [Pagila](https://github.com/devrimgunduz/pagila), a sample DVD rental shop: films,
customers, rentals, payments.

The same agent is built three times: with no framework, with Pydantic AI, and with LangGraph. Same
model, same prompt, same tools. Then all three face the same test questions, so you can see what a
framework actually changes.

## The series

| Part | Folder | What it shows | Status |
|---|---|---|---|
| 1 | `stages/01_raw_loop/` | The agent loop itself in ~100 lines of plain Python. No framework, nothing hidden | Code in repo |
| 2 | `stages/02_pydantic_ai/` | The same agent in Pydantic AI: typed tools and output, retries, tracing | Next |
| 3 | `stages/03_langgraph/` | The same agent as an explicit graph: state, branches, a human approval step, tracing | Planned |
| 4 | `stages/04_benchmark/` | All three against the same question set: accuracy, consistency, cost, speed, code size | Planned |

All three agents share `common/db.py`, the three tools (`list_tables`, `describe_table`, `run_sql`),
so only the loop changes between parts.

## Quick start

You need Python 3.10+, Docker, and an [Anthropic API key](https://console.anthropic.com).

```bash
git clone https://github.com/dave8172/postgres-agent && cd postgres-agent
docker compose up -d                      # Postgres 16 + Pagila + the read-only agent login
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # then paste your API key into .env
.venv/bin/python stages/01_raw_loop/agent.py "Which film category brings in the most rental revenue?"
```

On Windows (PowerShell), use `.venv\Scripts\python` in place of `.venv/bin/python`.

You'll see every turn: what the model asked for, what each tool returned, tokens and cost. The full
conversation of every run is saved in `runs/`.

## How the loop works (Part 1)

1. Send the model the conversation so far, plus a menu of tools.
2. If it asks for tools, run them and add the results to the conversation.
3. Repeat until it answers instead of asking.

The model remembers nothing between calls. The conversation list *is* its memory, and the whole
list is sent again every turn, which is why the input token count grows each turn.

**Watch it in VS Code:** open `stages/01_raw_loop/agent.py`, set a breakpoint on the
`response = client.messages.create(` line, press F5 and type a question. It stops before every
model call; open `messages` in the Variables panel to see exactly what the model is about to read.

## Safety lives in the database, not the prompt

The agent logs in as `agent_ro` (created by `setup/init.sh`):

- it can only `SELECT`, and every transaction is read-only
- Postgres cancels any query after 5 seconds
- it can't read the staff password column
- at most 3 connections

`run_sql` also sends each query as a prepared statement, which Postgres accepts only as one
statement, so `select 1; drop table ...` fails before anything runs. A prompt can be talked out of
its rules; these limits can't be.

## Benchmark rules (fixed before any results)

- Same model, system prompt, tools and database for every agent.
- Questions come with a reference SQL query. An answer is correct when its numbers match the
  reference result, checked by code, not by a model's opinion.
- Every question runs 3 times per agent, because agents don't give the same answer every time.
- Reported per agent: accuracy, share of questions right all 3 times, turns, tokens, cost, time,
  and lines of code.
- Results get published as they come out, including where the raw loop wins.

## Cost

Defaults to Claude Haiku 4.5 ($1 per million input tokens, $5 per million output, as of October
2026). Expect a cent or two per question; each run prints its exact tokens and cost, and Part 4
reports the measured numbers. Set `MODEL=claude-sonnet-5-5` to try a stronger model.

## Use your own Postgres

Run `setup/init.sh` as a superuser against an empty database named `pagila` (instructions at the
top of the file), then point `DATABASE_URL` in `.env` at it.

## Credits

Pagila v3.1.0 by Devrim Gündüz (MIT licence, `setup/pagila/LICENSE.txt`), a Postgres port of MySQL's
Sakila sample database.

## Licence

MIT

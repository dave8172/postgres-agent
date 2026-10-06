"""The agent's three tools: plain Python functions over the Pagila database.

Every stage (raw loop, Pydantic AI, LangGraph) imports these same functions,
so when we compare the stages later, only the loop differs, never the tools.

Each tool returns a short string, because a tool result is text the model has
to read: the smaller and clearer it is, the cheaper and less confused the agent.
"""

import os

import psycopg
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

MAX_ROWS = 20  # never hand the model more than this many rows


def _connect():
    # The database login (agent_ro) can only SELECT, and Postgres cancels any
    # query that runs longer than 5 seconds. Those limits live in the database,
    # not in this code, so a wrong query from the model can't get past them.
    return psycopg.connect(os.environ["DATABASE_URL"], autocommit=False)


def list_tables() -> str:
    """Names of every table, with row counts."""
    sql = """
        select c.relname
        from pg_class c join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'public' and c.relkind in ('r', 'p')
          and not c.relispartition
        order by c.relname
    """
    with _connect() as conn:
        names = [r[0] for r in conn.execute(sql).fetchall()]
        # Exact counts: fine for a small database; a big one would use estimates.
        counts = [conn.execute(f'select count(*) from "{n}"').fetchone()[0] for n in names]
    return "\n".join(f"{n} ({c} rows)" for n, c in zip(names, counts))


def describe_table(table: str) -> str:
    """Columns of one table: name, type, and which other table each foreign key points to."""
    # Read from Postgres's own catalog (pg_attribute, pg_constraint): the
    # information_schema views hide foreign keys from a login that doesn't own
    # the tables, and agent_ro owns nothing.
    sql = """
        select a.attname, format_type(a.atttypid, a.atttypmod),
               (select ft.relname || '.' || fa.attname
                  from pg_constraint k
                  join pg_class ft on ft.oid = k.confrelid
                  join pg_attribute fa on fa.attrelid = k.confrelid
                                      and fa.attnum = k.confkey[array_position(k.conkey, a.attnum)]
                 where k.contype = 'f' and k.conrelid = t.oid and a.attnum = any(k.conkey)
                 limit 1) as points_to
        from pg_class t
        join pg_namespace n on n.oid = t.relnamespace
        join pg_attribute a on a.attrelid = t.oid and a.attnum > 0 and not a.attisdropped
         and has_column_privilege(t.oid, a.attnum, 'SELECT')  -- hide what agent_ro can't read
        where n.nspname = 'public' and t.relname = %s
        order by a.attnum
    """
    with _connect() as conn:
        rows = conn.execute(sql, (table,)).fetchall()
    if not rows:
        return f"Error: no table named '{table}'. Call list_tables to see the names."
    lines = [f"{col} {typ}" + (f" -> {fk}" if fk else "") for col, typ, fk in rows]
    return f"{table}:\n" + "\n".join(lines)


def run_sql(query: str) -> str:
    """Run one read-only SELECT and return at most MAX_ROWS rows as text.

    Errors come back as text, not exceptions. That's deliberate: the model
    reads the error, fixes its SQL and tries again. That retry is the
    "agentic" part.
    """
    try:
        with _connect() as conn:
            # prepare=True sends the query as a prepared statement, which
            # Postgres only accepts as ONE statement, so "select 1; drop ..."
            # fails before anything runs.
            cur = conn.execute(query, prepare=True)
            if cur.description is None:
                return "Error: that statement returned no rows. Use a SELECT."
            cols = [d.name for d in cur.description]
            rows = cur.fetchmany(MAX_ROWS + 1)
    except psycopg.Error as e:
        return f"Error: {str(e).strip().splitlines()[0]}"

    more = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    out = [" | ".join(cols)] + [" | ".join(str(v) for v in r) for r in rows]
    footer = f"({len(rows)} rows shown, more exist; add LIMIT or aggregate)" if more else f"({len(rows)} rows)"
    return "\n".join(out + [footer])


# The menu the model sees: each tool's name, what it's for, and its inputs as
# JSON Schema. The model never sees the Python above, only these descriptions,
# so the descriptions are part of the prompt.
TOOLS = [
    {
        "name": "list_tables",
        "description": "List every table in the database with row counts. Start here.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "describe_table",
        "description": "Show one table's columns, their types, and which table each foreign key points to.",
        "input_schema": {
            "type": "object",
            "properties": {"table": {"type": "string", "description": "Table name, e.g. 'rental'"}},
            "required": ["table"],
        },
    },
    {
        "name": "run_sql",
        "description": (
            "Run one read-only PostgreSQL SELECT and get back up to 20 rows. "
            "If the query fails you get the error message; fix the SQL and try again."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A single SELECT statement"}},
            "required": ["query"],
        },
    },
]

FUNCTIONS = {"list_tables": list_tables, "describe_table": describe_table, "run_sql": run_sql}

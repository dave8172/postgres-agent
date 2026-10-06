#!/usr/bin/env bash
# Loads Pagila v3.1.0 into the current database and creates the agent's
# read-only login (agent_ro).
#
# Docker runs this automatically on first start (see docker-compose.yml).
# To use your own Postgres instead, run it as a superuser against an empty
# database called pagila, for example:
#   createdb pagila
#   PSQL="psql -d pagila" AGENT_PASSWORD=change-me bash setup/init.sh
set -euo pipefail

# Docker mounts this folder at /setup and says so in SETUP_DIR.
HERE="${SETUP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
# Inside the Docker image, POSTGRES_USER/POSTGRES_DB are set by the entrypoint.
PSQL="${PSQL:-psql --username ${POSTGRES_USER:-postgres} --dbname ${POSTGRES_DB:-pagila}}"
AGENT_PASSWORD="${AGENT_PASSWORD:?set AGENT_PASSWORD}"

# Files go in on stdin, so psql never needs permission to read this folder.
$PSQL -q -v ON_ERROR_STOP=1 < "$HERE/pagila/pagila-schema.sql" > /dev/null
$PSQL -q -v ON_ERROR_STOP=1 < "$HERE/pagila/pagila-data.sql" > /dev/null

# The safety limits live in the database, so no prompt or code bug can lift them:
# SELECT only, read-only transactions, a 5-second limit per query, and no
# access to the staff password column.
$PSQL -q -v ON_ERROR_STOP=1 -v pw="$AGENT_PASSWORD" <<'SQL'
CREATE ROLE agent_ro LOGIN PASSWORD :'pw' CONNECTION LIMIT 3;
ALTER ROLE agent_ro SET default_transaction_read_only = on;
ALTER ROLE agent_ro SET statement_timeout = '5s';
ALTER ROLE agent_ro SET idle_in_transaction_session_timeout = '30s';
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO agent_ro', current_database()) \gexec
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO agent_ro;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_ro;
REVOKE SELECT ON staff FROM agent_ro;
GRANT SELECT (staff_id, first_name, last_name, address_id, email, store_id, active, username, last_update)
  ON staff TO agent_ro;
SQL

echo "pagila loaded; agent_ro created"

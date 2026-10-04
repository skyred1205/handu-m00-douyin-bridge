# HANDU DTK PostgreSQL / TimescaleDB

DTK v5 requires PostgreSQL 17 with the TimescaleDB extension. A stock PostgreSQL service is not sufficient.

Railway service:

- Dockerfile: `services/handu-dtk-postgres/Dockerfile`
- private port: `5432`
- persistent volume mount: `/home/postgres/pgdata/data`
- variables:
  - `POSTGRES_DB=dtk`
  - `POSTGRES_USER=dtk`
  - `POSTGRES_PASSWORD=<random secret>`
  - `POSTGRES_HOST_AUTH_METHOD=scram-sha-256`

The Gateway variable should use the private Railway hostname:

`DTK_DATABASE_URL=postgresql+asyncpg://dtk:<password>@<postgres-service>.railway.internal:5432/dtk`

## Railway volume

Mount the Railway volume at `/home/postgres/pgdata/data`, but set:

`PGDATA=/home/postgres/pgdata/data/pgdata`

Do not use the volume mount root directly as `PGDATA`; Railway volumes may contain `lost+found`, which causes PostgreSQL `initdb` to fail.

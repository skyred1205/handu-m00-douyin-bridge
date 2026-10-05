# HANDU DTK PostgreSQL / TimescaleDB

DTK v5 requires PostgreSQL 17 with the TimescaleDB extension. A stock PostgreSQL service is not sufficient.

For Railway, use the non-HA TimescaleDB PostgreSQL 17 image because it works cleanly with Railway-managed volumes:

- image: `timescale/timescaledb:latest-pg17`
- private port: `5432`
- persistent volume mount: `/var/lib/postgresql`
- `PGDATA=/var/lib/postgresql/data`
- variables:
  - `POSTGRES_DB=dtk`
  - `POSTGRES_USER=dtk`
  - `POSTGRES_PASSWORD=<random secret>`
  - `POSTGRES_HOST_AUTH_METHOD=scram-sha-256`

The Gateway variable should use the private Railway hostname:

`DTK_DATABASE_URL=postgresql+asyncpg://dtk:<password>@<postgres-service>.railway.internal:5432/dtk`

The upstream DTK compose stack uses `timescale/timescaledb-ha:pg17`, but that image's hard-coded UID/data-directory expectations caused Railway volume permission/init failures in the acceptance environment. The standard TimescaleDB PostgreSQL 17 image still satisfies DTK's schema requirement: PostgreSQL 17 with the TimescaleDB extension available.

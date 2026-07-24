import argparse
import asyncio
import sys
from pathlib import Path

import asyncpg


async def connect(url: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        url.replace("postgresql+asyncpg://", "postgresql://", 1)
    )


async def ensure_migrations_table(url: str) -> None:
    conn = await connect(url)
    try:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version     text        PRIMARY KEY,
              applied_at  timestamptz NOT NULL DEFAULT now()
            )
            """
        )
    finally:
        await conn.close()


async def get_applied(url: str) -> set[str]:
    conn = await connect(url)
    try:
        rows = await conn.fetch("SELECT version FROM schema_migrations")
        return {r["version"] for r in rows}
    finally:
        await conn.close()


async def apply_one(url: str, migration: Path) -> str:
    """Run one migration atomically with its schema_migrations record.

    Migration files historically contained explicit BEGIN/COMMIT statements.
    Strip those transaction wrappers so the runner can include both the DDL
    and bookkeeping row in one transaction. Any PostgreSQL error aborts the
    transaction and the migration remains unapplied for a safe retry.
    """
    sql = migration.read_text()
    sql = sql.replace("BEGIN;", "").replace("COMMIT;", "")
    conn = await connect(url)
    try:
        async with conn.transaction():
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations(version) VALUES($1)",
                migration.name,
            )
        return "applied"
    finally:
        await conn.close()


async def apply(database_url: str, migrations_dir: Path) -> None:
    await ensure_migrations_table(database_url)
    applied = await get_applied(database_url)

    migrations = sorted(migrations_dir.glob("*.sql"))
    if not migrations:
        print("  no migration files found")
        return

    new_count = 0
    for migration in migrations:
        if migration.name in applied:
            continue  # 已完成，直接跳过

        try:
            status = await apply_one(database_url, migration)
            print(f"  applied  {migration.name}")
            new_count += 1
        except asyncpg.PostgresError as exc:
            print(
                f"\n  ERROR in {migration.name}:\n"
                f"  {type(exc).__name__}: {exc}\n",
                file=sys.stderr,
            )
            raise SystemExit(1) from exc

    if new_count == 0:
        print("  up to date")
    else:
        print(f"  done — {new_count} migration(s) processed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply VTV database migrations")
    parser.add_argument("database_url")
    parser.add_argument(
        "--migrations-dir", type=Path, default=Path("migrations"),
        help="Directory of *.sql files",
    )
    args = parser.parse_args()
    asyncio.run(apply(args.database_url, args.migrations_dir))


if __name__ == "__main__":
    main()

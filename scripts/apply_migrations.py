import argparse
import asyncio
from pathlib import Path

import asyncpg


async def apply(database_url: str, migrations_dir: Path) -> None:
    url = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(url)
    try:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version text PRIMARY KEY,
              applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        applied = {
            row["version"]
            for row in await connection.fetch("SELECT version FROM schema_migrations")
        }
        for migration in sorted(migrations_dir.glob("*.sql")):
            if migration.name in applied:
                continue
            # Migration files own their BEGIN/COMMIT boundary.
            await connection.execute(migration.read_text())
            await connection.execute(
                "INSERT INTO schema_migrations(version) VALUES($1)", migration.name
            )
            print(f"applied {migration.name}")
    finally:
        await connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database_url")
    parser.add_argument("--migrations-dir", type=Path, default=Path("migrations"))
    args = parser.parse_args()
    asyncio.run(apply(args.database_url, args.migrations_dir))


if __name__ == "__main__":
    main()

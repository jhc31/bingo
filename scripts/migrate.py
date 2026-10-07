"""Apply supabase/migrations/*.sql in order (all statements are idempotent).

Usage: python -m scripts.migrate
Alternatively paste the SQL files into the Supabase SQL editor.
"""
from app import config, db

MIGRATIONS = config.ROOT / "supabase" / "migrations"


def main():
    with db.connection() as conn:
        for f in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(f.read_text(encoding="utf-8"))
            print(f"applied {f.name}")
        conn.commit()
    db.close()


if __name__ == "__main__":
    main()

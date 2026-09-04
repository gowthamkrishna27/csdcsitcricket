import os
import sqlite3
import json
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ SUPABASE_URL or SUPABASE_KEY is missing from .env")
    exit(1)

sb: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
DB_PATH = "data/cricket.db"

if not os.path.exists(DB_PATH):
    print(f"❌ SQLite database not found at {DB_PATH}")
    exit(1)

def migrate():
    print("[MIGRATE] Starting Migration from SQLite to Supabase...")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    tables = [
        "tournaments", "leagues", "teams", "players",
        "matches", "innings", "batting_scores", "bowling_scores",
        "ball_events", "users", "admins"
    ]

    for table in tables:
        print(f"\n[MIGRATE] Migrating table: {table}...")
        try:
            cursor.execute(f"SELECT * FROM {table}")
            rows = [dict(row) for row in cursor.fetchall()]
        except sqlite3.OperationalError:
            print(f"[SKIP] Table {table} does not exist in SQLite. Skipping.")
            continue
            
        if not rows:
            print(f"[INFO] No data in {table}.")
            continue

        chunk_size = 500
        for i in range(0, len(rows), chunk_size):
            chunk = rows[i:i + chunk_size]
            try:
                res = sb.table(table).upsert(chunk).execute()
                print(f"[SUCCESS] Inserted {len(res.data)} rows into {table} (Batch {i//chunk_size + 1})")
            except Exception as e:
                print(f"[ERROR] Error inserting into {table}: {e}")
                if chunk:
                    print(f"Sample data: {chunk[0]}")

    print("\n[MIGRATE] Migration Complete!")

if __name__ == "__main__":
    migrate()

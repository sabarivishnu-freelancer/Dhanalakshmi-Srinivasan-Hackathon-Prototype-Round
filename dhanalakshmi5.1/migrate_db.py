import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.getenv("DB_NAME", "petitiondb")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "vish")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)
cur = conn.cursor()

try:
    # Add signature_count column if it doesn't exist
    cur.execute("""
        ALTER TABLE petitions
        ADD COLUMN IF NOT EXISTS signature_count INTEGER DEFAULT 0;
    """)
    print("✓ Added signature_count column to petitions table")

    # replace per-student duplicate index with a global title+description constraint
    # drop old index if present
    cur.execute("""
        DROP INDEX IF EXISTS petitions_student_title_description_uidx;
    """
    )
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS petitions_title_description_uidx
        ON petitions (lower(title), lower(description));
    """
    )
    print("✓ Added global unique constraint for duplicate petitions")

    # ensure user emails are unique when not null (case insensitive)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS users_email_uidx
        ON users (lower(email))
        WHERE email IS NOT NULL;
    """
    )
    print("✓ Added unique constraint for user emails")
    
    # Create signatures table if it doesn't exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signatures (
            id SERIAL PRIMARY KEY,
            petition_id INTEGER NOT NULL REFERENCES petitions(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            signed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(petition_id, user_id)
        );
    """)
    print("✓ Created signatures table")
    
    conn.commit()
    print("✓ Database schema updated successfully!")
    
except Exception as e:
    conn.rollback()
    print(f"✗ Error: {e}")
finally:
    cur.close()
    conn.close()

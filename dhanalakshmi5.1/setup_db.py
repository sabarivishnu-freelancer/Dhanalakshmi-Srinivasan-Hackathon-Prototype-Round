import os
import psycopg2
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

load_dotenv()

DB_NAME = os.getenv("DB_NAME", "petitiondb")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "vish")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")

conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD, host=DB_HOST, port=DB_PORT)
cur = conn.cursor()

def init_db():
    with open("init_db.sql", "r", encoding="utf-8") as f:
        sql = f.read()
    cur.execute(sql)
    conn.commit()

def create_admin(username: str, password: str):
    hashed = generate_password_hash(password)
    cur.execute("SELECT id FROM users WHERE username=%s", (username,))
    if cur.fetchone():
        print("Admin user already exists")
        return
    admin_email = os.getenv("ADMIN_EMAIL")
    cur.execute("INSERT INTO users (username,password,email,role) VALUES (%s,%s,%s,%s)", (username, hashed, admin_email, 'admin'))
    conn.commit()
    print("Admin created")

if __name__ == "__main__":
    print("Initializing DB...")
    init_db()
    # create default admin if env vars present
    admin_user = os.getenv("ADMIN_USER")
    admin_pass = os.getenv("ADMIN_PASS")
    admin_email = os.getenv("ADMIN_EMAIL")
    if admin_user and admin_pass:
        create_admin(admin_user, admin_pass)
    else:
        print("Set ADMIN_USER and ADMIN_PASS in .env to create an admin user automatically.")

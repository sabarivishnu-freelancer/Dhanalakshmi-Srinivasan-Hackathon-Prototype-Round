# Petition System Prototype

Flask + PostgreSQL prototype with login (student/admin), petition submission, AI analysis, admin approve/reject, and JSON/PDF export.

Setup

1. Copy `.env.example` to `.env` and edit DB credentials and `ADMIN_USER`/`ADMIN_PASS` if desired.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Initialize DB and create admin (reads `init_db.sql`):

```bash
python setup_db.py
```

4. Run the app:

```bash
python app.py
```

Open `http://127.0.0.1:5000` then register/login or use the admin created in step 3.

## Duplicate Prevention Logic

- **Users:** usernames are unique and emails (when provided) are normalized to lowercase and prevented from being reused. Registration checks avoid duplicates and the database enforces constraints.
- **Petitions:** the system blocks submissions that exactly match the title+description of an existing petition (across all users) and performs NLP similarity checks to warn about close duplicates. A global unique database index also guards against race conditions.
- **Signatures:** students may only sign a given petition once; the `signatures` table has a unique constraint and the API returns an error if a duplicate sign attempt occurs.


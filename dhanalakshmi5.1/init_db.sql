-- Init DB schema for petition system
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    email TEXT,
    role TEXT NOT NULL CHECK (role IN ('student','admin'))
);

-- ensure emails are unique when provided (lowercase comparison for case insensitivity)
CREATE UNIQUE INDEX IF NOT EXISTS users_email_uidx
ON users (lower(email))
WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS petitions (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT,
    priority TEXT,
    status TEXT DEFAULT 'Pending',
    signature_count INTEGER DEFAULT 0,
    student_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- prevent duplicate petitions based on title+description (case insensitive)
-- this enforces that any two petitions cannot have the same title and description,
-- regardless of which student submitted them. the application layer already checks
-- and provides user-friendly messages, but the index guards against race conditions.
CREATE UNIQUE INDEX IF NOT EXISTS petitions_title_description_uidx
ON petitions (lower(title), lower(description));

CREATE TABLE IF NOT EXISTS signatures (
    id SERIAL PRIMARY KEY,
    petition_id INTEGER NOT NULL REFERENCES petitions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    signed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(petition_id, user_id)
);

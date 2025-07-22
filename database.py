import sqlite3

# Connect to SQLite (will create file if it doesn't exist)
conn = sqlite3.connect("interviews.db")
cursor = conn.cursor()

# Create table if not exists
cursor.execute('''
    CREATE TABLE IF NOT EXISTS interviews (
        session_id TEXT PRIMARY KEY,
        name TEXT,
        email TEXT,
        video_path TEXT,
        transcript_path TEXT,
        timestamp TEXT
    )
''')

conn.commit()
conn.close()

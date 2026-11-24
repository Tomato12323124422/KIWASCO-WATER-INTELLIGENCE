import sqlite3

db = r'kiwasco.db'
con = sqlite3.connect(db)
cur = con.cursor()

# List all tables and row counts
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print('=== TABLES ===')
for t in tables:
    cur.execute(f'SELECT COUNT(*) FROM "{t}"')
    count = cur.fetchone()[0]
    print(f'  {t}: {count} rows')

print()

# Sample from key tables
for t in ['customers', 'zones', 'bills', 'meter_readings', 'users']:
    if t in tables:
        cur.execute(f'SELECT * FROM "{t}" LIMIT 3')
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        print(f'=== {t.upper()} (first 3 rows) ===')
        print('  Columns:', cols)
        for r in rows:
            print(' ', r)
        print()

con.close()
print('Done.')

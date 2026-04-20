import calendar, json, sqlite3
from datetime import date, datetime, timedelta

ADMIN_DB = "/Users/coreybadcock/Papr/Jobs/a23a3ba6-2002-4437-8c61-a82c51f05340/data/data.db"

def add_months(d, months, dom=None):
    month = d.month - 1 + months; year = d.year + month // 12; month = month % 12 + 1
    day = min(dom or d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def next_due(row):
    cur = datetime.strptime(row['next_due_date'], '%Y-%m-%d').date(); step = max(1, row['interval_n'] or 1)
    if row['frequency'] == 'daily': return cur + timedelta(days=step)
    if row['frequency'] == 'monthly': return add_months(cur, step, row['day_of_month'])
    return cur + timedelta(days=7 * step)

def main():
    conn = sqlite3.connect(ADMIN_DB); conn.row_factory = sqlite3.Row
    today = date.today().isoformat(); made = advanced = 0
    rows = conn.execute("SELECT * FROM recurring_templates WHERE status='active' AND next_due_date<=? ORDER BY next_due_date ASC", (today,)).fetchall()
    for row in rows:
        exists = conn.execute("SELECT 1 FROM tasks WHERE source='recurring' AND status='open' AND due_date=? AND json_extract(source_details,'$.recurring_template_id')=?", (row['next_due_date'], row['id'])).fetchone()
        payload = {'recurring_template_id': row['id'], 'frequency': row['frequency'], 'interval_n': row['interval_n']}
        if not exists:
            conn.execute("INSERT INTO tasks (title,description,due_date,priority,status,source,source_details) VALUES (?,?,?,?, 'open','recurring',?)", (row['title'], row['description'] or '', row['next_due_date'], row['priority'], json.dumps(payload)))
            made += 1
        nxt = next_due(row).isoformat()
        conn.execute("UPDATE recurring_templates SET next_due_date=?, updated_at=datetime('now') WHERE id=?", (nxt, row['id']))
        advanced += 1
    conn.commit(); conn.close()
    print(f'recurring templates_due={len(rows)} tasks_created={made} templates_advanced={advanced}')

if __name__ == '__main__': main()

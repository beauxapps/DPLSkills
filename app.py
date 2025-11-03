
import os, sqlite3, uuid, random, re, csv
from io import StringIO
from flask import Flask, g, render_template, request, redirect, url_for, abort, flash, Response

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key')

DB_PATH = os.path.join(os.path.dirname(__file__), 'data.db')

NAMES = [
    "Adithya Manivannan",
    "Sarah Kassim",
    "Nisha Cyril",
    "Joshua Chand",
    "Kaustubh Rajimwale",
    "Ling Lin",
    "Sai Krishna Saravanan Nannapaneni",
    "Ethan Teoh",
    "Smriti Singh",
    "Elsa Mathew Samuel",
    "Harsha Munipalle",
    "Yigit Uyan",
    "Maedeh Khodaei",
    "Jared Brown",
    "James Hall",
    "Akshay Bharadwaj",
    "Brandon Hernacki",
    "Beau Babst",
    "Daniel Duck",
    "Fatimah Ali",
    "Gisselle Williams",
    "Sunanda Seshan",
]

def slugify_first_last(full_name: str) -> str:
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    if not parts:
        return ""
    first = parts[0]
    last = parts[-1] if len(parts) > 1 else ""
    slug = f"{first}_{last}".strip("_").lower()
    slug = re.sub(r"[^a-z0-9_]+", "", slug)
    return slug

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    db.executescript('''
    CREATE TABLE IF NOT EXISTS people (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        submitted INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER UNIQUE NOT NULL,
        hard_skills TEXT,
        soft_skills TEXT,
        areas_to_grow TEXT,
        in_5_years TEXT,
        fun_fact TEXT,
        superpower TEXT,
        FOREIGN KEY(person_id) REFERENCES people(id)
    );
    CREATE TABLE IF NOT EXISTS mapping (
        person_id INTEGER UNIQUE NOT NULL,
        assigned_person_id INTEGER UNIQUE NOT NULL,
        FOREIGN KEY(person_id) REFERENCES people(id),
        FOREIGN KEY(assigned_person_id) REFERENCES people(id)
    );
    ''')
    # migrate from token->slug if old schema exists
    cols = [r['name'] for r in db.execute("PRAGMA table_info(people)").fetchall()]
    if 'slug' not in cols:
        # legacy table; rebuild quickly
        db.executescript('''
            CREATE TABLE IF NOT EXISTS people_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                submitted INTEGER DEFAULT 0
            );
        ''')
        old = db.execute('SELECT id, name, submitted FROM people').fetchall()
        for r in old:
            db.execute('INSERT OR IGNORE INTO people_new (id,name,slug,submitted) VALUES (?,?,?,?)',
                       (r['id'], r['name'], slugify_first_last(r['name']), r['submitted']))
        db.executescript('DROP TABLE people; ALTER TABLE people_new RENAME TO people;')
        db.commit()

    # seed people if empty
    cur = db.execute('SELECT COUNT(*) as c FROM people')
    if cur.fetchone()['c'] == 0:
        for name in NAMES:
            slug = slugify_first_last(name)
            # ensure uniqueness if weird dup
            existing = db.execute('SELECT 1 FROM people WHERE slug=?', (slug,)).fetchone()
            if existing:
                i = 2
                base_slug = slug
                while db.execute('SELECT 1 FROM people WHERE slug=?', (f"{base_slug}{i}",)).fetchone():
                    i += 1
                slug = f"{base_slug}{i}"
            db.execute('INSERT INTO people (name, slug) VALUES (?,?)', (name, slug))
        db.commit()

@app.before_request
def ensure_db():
    init_db()

def get_person_by_slug(slug):
    db = get_db()
    cur = db.execute('SELECT * FROM people WHERE slug=?', (slug,))
    return cur.fetchone()

def get_response_for(person_id):
    db = get_db()
    cur = db.execute('SELECT * FROM responses WHERE person_id=?', (person_id,))
    return cur.fetchone()

def get_mapping_for(person_id):
    db = get_db()
    cur = db.execute('SELECT * FROM mapping WHERE person_id=?', (person_id,))
    row = cur.fetchone()
    return row

@app.route('/')
def home():
    # minimal splash — no nav
    return render_template('index.html')

@app.route('/links')
def links():
    db = get_db()
    base_url = request.url_root.rstrip('/')
    rows = db.execute('SELECT name, slug FROM people ORDER BY name').fetchall()
    data = [{
        "name": r["name"],
        "link": f"{base_url}/{r['slug']}"
    } for r in rows]
    return render_template('links.html', data=data)

@app.route('/links.csv')
def links_csv():
    db = get_db()
    base_url = request.url_root.rstrip('/')
    rows = db.execute('SELECT name, slug FROM people ORDER BY name').fetchall()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name','Link'])
    for r in rows:
        writer.writerow([r['name'], f"{base_url}/{r['slug']}"])
    csv_data = output.getvalue()
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition':'attachment; filename=links.csv'}
    )

@app.route('/<slug>', methods=['GET', 'POST'])
def form(slug):
    person = get_person_by_slug(slug)
    if not person:
        abort(404)
    db = get_db()
    # if mapping exists and assigned has response, show read-only of assigned
    m = get_mapping_for(person['id'])
    if m:
        assigned = db.execute('SELECT * FROM people WHERE id=?', (m['assigned_person_id'],)).fetchone()
        assigned_resp = get_response_for(assigned['id'])
        if assigned_resp:
            return render_template('view.html', viewer=person, owner=assigned, resp=assigned_resp, mapped=True)

    resp = get_response_for(person['id'])

    if request.method == 'POST':
        hard = request.form.get('hard_skills','').strip()
        soft = request.form.get('soft_skills','').strip()
        grow = request.form.get('areas_to_grow','').strip()
        in5 = request.form.get('in_5_years','').strip()
        fun = request.form.get('fun_fact','').strip()
        sp = request.form.get('superpower','').strip()
        if not (hard and soft and grow):
            flash('Please fill at least the three main sections (Hard, Soft, Areas to Grow).')
            return render_template('form.html', person=person, resp=request.form)
        if resp:
            db.execute('''UPDATE responses SET hard_skills=?, soft_skills=?, areas_to_grow=?, in_5_years=?, fun_fact=?, superpower=?
                          WHERE person_id=?''', (hard, soft, grow, in5, fun, sp, person['id']))
        else:
            db.execute('''INSERT INTO responses (person_id, hard_skills, soft_skills, areas_to_grow, in_5_years, fun_fact, superpower)
                          VALUES (?,?,?,?,?,?,?)''', (person['id'], hard, soft, grow, in5, fun, sp))
        db.execute('UPDATE people SET submitted=1 WHERE id=?', (person['id'],))
        db.commit()
        return render_template('thanks.html', person=person)

    if resp:
        # already submitted; show their own read-only (until mapping happens)
        return render_template('view.html', viewer=person, owner=person, resp=resp, mapped=False)
    return render_template('form.html', person=person, resp=None)

@app.route('/admin')
def admin():
    db = get_db()
    people = db.execute('SELECT * FROM people ORDER BY name').fetchall()
    submitted = db.execute('SELECT COUNT(*) AS c FROM people WHERE submitted=1').fetchone()['c']
    total = db.execute('SELECT COUNT(*) AS c FROM people').fetchone()['c']
    mapping_rows = db.execute('''SELECT p.name as from_name, q.name as to_name
                                 FROM mapping m
                                 JOIN people p ON p.id=m.person_id
                                 JOIN people q ON q.id=m.assigned_person_id
                                 ORDER BY p.name''').fetchall()
    return render_template('admin.html', people=people, submitted=submitted, total=total, mapping=mapping_rows)

def derangement(lst):
    if len(lst) < 2:
        return None
    for _ in range(1000):
        import random as _r
        perm = lst[:]
        _r.shuffle(perm)
        if all(a != b for a,b in zip(lst, perm)):
            return perm
    perm = lst[:]
    import random as _r
    _r.shuffle(perm)
    for i,(a,b) in enumerate(zip(lst,perm)):
        if a==b:
            j = (i+1) % len(lst)
            perm[i],perm[j] = perm[j],perm[i]
    if all(a != b for a,b in zip(lst, perm)):
        return perm
    return None

from flask import redirect
@app.route('/admin/generate_mapping', methods=['POST'])
def generate_mapping():
    db = get_db()
    submitted_rows = db.execute('SELECT id FROM people WHERE submitted=1').fetchall()
    ids = [r['id'] for r in submitted_rows]
    if len(ids) < 2:
        flash('Need at least 2 submissions to generate a swap.')
        return redirect(url_for('admin'))
    target = derangement(ids)
    if not target:
        flash('Unable to generate mapping, try again.')
        return redirect(url_for('admin'))
    db.execute('DELETE FROM mapping')
    for a,b in zip(ids, target):
        db.execute('INSERT INTO mapping (person_id, assigned_person_id) VALUES (?,?)', (a,b))
    db.commit()
    flash('Mapping generated.')
    return redirect(url_for('admin'))

@app.route('/admin/reset', methods=['POST'])
def reset():
    db = get_db()
    db.execute('DELETE FROM mapping')
    db.commit()
    flash('Mapping cleared.')
    return redirect(url_for('admin'))

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")

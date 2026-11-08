"""Account profile, scoped to the authenticated user."""
import re
from datetime import date


def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS user_profiles(
        user_id INTEGER PRIMARY KEY REFERENCES users(id), started INTEGER NOT NULL DEFAULT 1,
        name TEXT, email TEXT, address TEXT, birth_date TEXT,
        contact_consent INTEGER, marketing_consent INTEGER, updated TEXT)''')


def read(c, user_id):
    row = c.execute('SELECT * FROM user_profiles WHERE user_id=?', (user_id,)).fetchone()
    if not row:
        return {'started': False, 'complete': False}
    result = dict(row)
    result.pop('user_id', None)
    result['started'] = True
    result['complete'] = all(result.get(k) for k in ('name', 'email', 'address', 'birth_date')) and all(result.get(k) in (0, 1) for k in ('contact_consent', 'marketing_consent'))
    for key in ('contact_consent', 'marketing_consent'):
        if result[key] is not None:
            result[key] = bool(result[key])
    return result


def start(c, user_id):
    c.execute('INSERT OR IGNORE INTO user_profiles(user_id) VALUES(?)', (user_id,))
    return read(c, user_id)


def save(c, user_id, data, updated):
    values = {}
    for key, label, limit in [('name', 'navn', 200), ('email', 'mailadresse', 254), ('address', 'adresse', 500), ('birth_date', 'fødselsdato', 10)]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError('Udfyld et gyldigt ' + label + '.')
        values[key] = value.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values['email']):
        raise ValueError('Udfyld en gyldig mailadresse.')
    try:
        born = date.fromisoformat(values['birth_date'])
        if born > date.today() or born.year < 1900: raise ValueError()
    except ValueError:
        raise ValueError('Udfyld en gyldig fødselsdato.')
    for key in ('contact_consent', 'marketing_consent'):
        if type(data.get(key)) is not bool:
            raise ValueError('Vælg ja eller nej til begge kontaktønsker.')
    c.execute('''INSERT INTO user_profiles(user_id,started,name,email,address,birth_date,contact_consent,marketing_consent,updated)
        VALUES(?,1,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
        started=1,name=excluded.name,email=excluded.email,address=excluded.address,birth_date=excluded.birth_date,
        contact_consent=excluded.contact_consent,marketing_consent=excluded.marketing_consent,updated=excluded.updated''',
        (user_id, values['name'], values['email'], values['address'], values['birth_date'], int(data['contact_consent']), int(data['marketing_consent']), updated))
    return read(c, user_id)

"""Account profile, scoped to the authenticated user."""
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
import json


def init(c):
    c.execute('''CREATE TABLE IF NOT EXISTS user_profiles(
        user_id INTEGER PRIMARY KEY REFERENCES users(id), started INTEGER NOT NULL DEFAULT 1,
        name TEXT, email TEXT, address TEXT, birth_date TEXT,
        contact_consent INTEGER, marketing_consent INTEGER, updated TEXT)''')
    columns = {r['name'] for r in c.execute('PRAGMA table_info(user_profiles)')}
    for column in ('street', 'postal_code', 'city'):
        if column not in columns:
            c.execute(f'ALTER TABLE user_profiles ADD COLUMN {column} TEXT')


def read(c, user_id):
    row = c.execute('SELECT * FROM user_profiles WHERE user_id=?', (user_id,)).fetchone()
    if not row:
        return {'started': False, 'complete': False}
    result = dict(row)
    result.pop('user_id', None)
    result['started'] = True
    if result.get('address') and not result.get('street'):
        match = re.fullmatch(r'\s*(.+?),?\s+(\d{4})\s+(.+?)\s*', result['address'])
        if match:
            result['street'], result['postal_code'], result['city'] = match.group(1).rstrip(', '), match.group(2), match.group(3)
        else:
            result['street'] = result['address']
    result['complete'] = all(result.get(k) for k in ('name', 'email', 'street', 'postal_code', 'city', 'birth_date')) and all(result.get(k) in (0, 1) for k in ('contact_consent', 'marketing_consent'))
    for key in ('contact_consent', 'marketing_consent'):
        if result[key] is not None:
            result[key] = bool(result[key])
    return result


def start(c, user_id):
    c.execute('INSERT OR IGNORE INTO user_profiles(user_id) VALUES(?)', (user_id,))
    return read(c, user_id)


def save(c, user_id, data, updated):
    values = {}
    for key, label, limit in [('name', 'navn', 200), ('email', 'mailadresse', 254), ('street', 'vej og nummer', 200), ('postal_code', 'postnummer', 20), ('city', 'by', 120), ('birth_date', 'fødselsdato', 10)]:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise ValueError('Udfyld et gyldigt ' + label + '.')
        values[key] = value.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values['email']):
        raise ValueError('Udfyld en gyldig mailadresse.')
    if not re.fullmatch(r'\d{4}', values['postal_code']):
        raise ValueError('Postnummeret skal bestå af fire cifre.')
    try:
        born = date.fromisoformat(values['birth_date'])
        if born > date.today() or born.year < 1900: raise ValueError()
    except ValueError:
        raise ValueError('Udfyld en gyldig fødselsdato.')
    for key in ('contact_consent', 'marketing_consent'):
        if type(data.get(key)) is not bool:
            raise ValueError('Vælg ja eller nej til begge kontaktønsker.')
    c.execute('''INSERT INTO user_profiles(user_id,started,name,email,address,birth_date,contact_consent,marketing_consent,updated,street,postal_code,city)
        VALUES(?,1,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
        started=1,name=excluded.name,email=excluded.email,address=excluded.address,birth_date=excluded.birth_date,
        contact_consent=excluded.contact_consent,marketing_consent=excluded.marketing_consent,updated=excluded.updated,
        street=excluded.street,postal_code=excluded.postal_code,city=excluded.city''',
        (user_id, values['name'], values['email'], values['street'] + ', ' + values['postal_code'] + ' ' + values['city'], values['birth_date'], int(data['contact_consent']), int(data['marketing_consent']), updated, values['street'], values['postal_code'], values['city']))
    return read(c, user_id)

@lru_cache(maxsize=1)
def _postcodes():
    with (Path(__file__).parent / 'data' / 'dk_postcodes.json').open(encoding='utf-8') as source:
        return json.load(source)['postcodes']


def postcode_city(code):
    """Bundled GeoNames data; no per-lookup network dependency."""
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{4}', code):
        raise ValueError('Invalid postal code')
    return _postcodes().get(code)

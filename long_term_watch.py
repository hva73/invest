"""SQLite persistence for user-owned long-term observations."""

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from report_v2 import ID
from report_validation import stamp

OBSERVER = "Observer"
INTERESTING = "Interessant langsigtet"
REASSESS = "Revurdér"
STATUSES = (OBSERVER, INTERESTING, REASSESS)


def init(connection):
    """Explicitly initialize the observation table on the supplied connection."""
    connection.execute("""
        CREATE TABLE IF NOT EXISTS long_term_observations (
            user_id INTEGER NOT NULL REFERENCES users(id),
            asset_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            name TEXT,
            exchange TEXT NOT NULL,
            currency TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            reference_price TEXT,
            reference_at TEXT,
            reference_source TEXT,
            status TEXT NOT NULL CHECK (status IN ('Observer', 'Interessant langsigtet', 'Revurdér')),
            active INTEGER NOT NULL CHECK (active IN (0, 1)),
            PRIMARY KEY (user_id, asset_id)
        )
    """)


def validate_asset_id(value):
    if not isinstance(value, str) or not re.fullmatch(ID["pattern"], value):
        raise ValueError("A stable Pluto asset ID is required")
    return value


def add(connect, uid, *, verified_identity=None, reference_price=None,
        reference_at=None, reference_source=None):
    """Accept identity from the caller's Pluto verification step.

    The caller must pass the verified instrument fields, even for a previously
    owned instrument. A repeat add returns the original observation as stored.
    Use reopen to explicitly reactivate an inactive observation.
    """
    if not isinstance(verified_identity, dict):
        raise ValueError("Verified Pluto identity is required")
    asset_id = validate_asset_id(verified_identity.get("asset_id"))
    ticker = verified_identity.get("ticker")
    exchange = verified_identity.get("exchange")
    currency = verified_identity.get("currency")
    name = verified_identity.get("name")
    if (not isinstance(ticker, str) or not ticker.strip()
            or not isinstance(exchange, str) or exchange.strip().upper() in ("", "UKENDT", "UNKNOWN")
            or not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)
            or (name is not None and not isinstance(name, str))):
        raise ValueError("Incomplete verified Pluto identity")
    if reference_price is not None:
        try:
            price = Decimal(str(reference_price))
        except InvalidOperation as exc:
            raise ValueError("Invalid reference price") from exc
        if not price.is_finite() or price <= 0:
            raise ValueError("Invalid reference price")
        if not isinstance(reference_source, str) or not reference_source.strip():
            raise ValueError("Reference source is required")
        reference_price = str(price)
        reference_at = stamp(reference_at).astimezone(timezone.utc).isoformat()
    elif reference_at is not None or reference_source is not None:
        raise ValueError("Reference metadata requires a price")
    with connect() as connection:
        connection.execute("""
            INSERT INTO long_term_observations (
                user_id, asset_id, ticker, name, exchange, currency, observed_at,
                reference_price, reference_at, reference_source, status, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT (user_id, asset_id) DO NOTHING
        """, (uid, asset_id, ticker, name, exchange, currency,
              datetime.now(timezone.utc).isoformat(), reference_price, reference_at,
              reference_source, OBSERVER))
        return dict(connection.execute("""
            SELECT * FROM long_term_observations WHERE user_id = ? AND asset_id = ?
        """, (uid, asset_id)).fetchone())


def list_observations(connect, uid, *, include_inactive=False):
    with connect() as connection:
        return [dict(row) for row in connection.execute("""
            SELECT * FROM long_term_observations
            WHERE user_id = ? AND (active = 1 OR ?)
            ORDER BY observed_at DESC, asset_id
        """, (uid, include_inactive))]


def set_status(connect, uid, asset_id, status):
    """Set the label of an active observation and report whether it exists."""
    if status not in STATUSES:
        raise ValueError("Unknown observation status")
    with connect() as connection:
        return connection.execute("""
            UPDATE long_term_observations SET status = ?
            WHERE user_id = ? AND asset_id = ? AND active = 1
        """, (status, uid, validate_asset_id(asset_id))).rowcount == 1


def _set_active(connect, uid, asset_id, active):
    with connect() as connection:
        return connection.execute("""
            UPDATE long_term_observations SET active = ?
            WHERE user_id = ? AND asset_id = ? AND active != ?
        """, (active, uid, validate_asset_id(asset_id), active)).rowcount == 1


def remove(connect, uid, asset_id):
    """Deactivate an observation and report whether it changed."""
    return _set_active(connect, uid, asset_id, False)


def reopen(connect, uid, asset_id):
    """Reactivate an observation and report whether it changed."""
    return _set_active(connect, uid, asset_id, True)

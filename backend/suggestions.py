import json
import logging
import os
import re
import smtplib
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from .tmdb_service import normalize_tmdb_id

LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_PATH = PROJECT_ROOT / "movie_project" / "data" / "suggestions" / "suggestions.jsonl"
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
_SUGGESTION_LOCK = threading.Lock()


class ValidationError(ValueError):
    pass


def _text(payload, key, max_len):
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError(f"'{key}' must be text.")
    value = re.sub(r"[\r\n\t\v\f]+", " ", value).strip()
    if len(value) > max_len:
        raise ValidationError(f"'{key}' must be {max_len} characters or fewer.")
    return value


def _list(payload, key, max_items=10, max_len=60):
    value = payload.get(key)
    if value in (None, ""):
        return []
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list) or len(value) > max_items:
        raise ValidationError(f"'{key}' must be a list of at most {max_items} items.")
    cleaned = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise ValidationError(f"'{key}' must contain text only.")
        item = re.sub(r"[\r\n\t\v\f]+", " ", item).strip()
        if len(item) > max_len:
            raise ValidationError(f"Each '{key}' item must be {max_len} characters or fewer.")
        key_value = item.casefold()
        if item and key_value not in seen:
            cleaned.append(item)
            seen.add(key_value)
    return cleaned


def _integer(value, field, minimum, maximum):
    if isinstance(value, bool):
        raise ValidationError(f"'{field}' must be an integer.")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and re.fullmatch(r"\d+", value.strip()):
        number = int(value.strip())
    else:
        raise ValidationError(f"'{field}' must be an integer.")
    if not minimum <= number <= maximum:
        raise ValidationError(f"'{field}' must be between {minimum} and {maximum}.")
    return number


def validate_suggestion(payload):
    """Only the title is required; all other fields are optional."""
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")
    if payload.get("website"):
        raise ValidationError("Rejected.")

    title = _text(payload, "title", 200)
    if not title:
        raise ValidationError("Please enter the movie title.")

    year = payload.get("year")
    if year in (None, ""):
        year = None
    else:
        year = _integer(year, "year", 1880, datetime.now().year + 3)

    tmdb_id = payload.get("tmdb_id")
    if tmdb_id in (None, ""):
        tmdb_id = None
    else:
        tmdb_id = normalize_tmdb_id(tmdb_id)
        if tmdb_id is None:
            raise ValidationError("'tmdb_id' must be a positive integer.")
        tmdb_id = int(tmdb_id)

    contact = _text(payload, "contact_email", 254)
    if contact and not EMAIL_PATTERN.fullmatch(contact):
        raise ValidationError("That e-mail address does not look right.")

    autofilled = payload.get("autofilled", False)
    if not isinstance(autofilled, bool):
        raise ValidationError("'autofilled' must be a boolean.")

    return {
        "title": title,
        "year": year,
        "tmdb_id": tmdb_id,
        "languages": _list(payload, "languages"),
        "genres": _list(payload, "genres"),
        "director": _text(payload, "director", 120),
        "cast": _list(payload, "cast"),
        "overview": _text(payload, "overview", 1500),
        "note": _text(payload, "note", 1000),
        "contact_email": contact,
        "autofilled": autofilled,
    }


class RateLimiter:
    """In-memory request limiter: allow `limit` attempts per key and time window."""

    def __init__(self, limit=5, window=3600):
        self.limit, self.window = limit, window
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key):
        now = time.monotonic()
        with self._lock:
            hits = [timestamp for timestamp in self._hits.get(key, []) if now - timestamp < self.window]
            if len(hits) >= self.limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 5000:
                self._hits = {
                    item_key: values
                    for item_key, values in self._hits.items()
                    if values and now - values[-1] < self.window
                }
            return True


def _format_email(record):
    lines = [
        "A user would like this movie added to the catalogue.",
        "",
        f"Title      : {record['title']}",
        f"Year       : {record['year'] or '-'}",
        f"TMDB id    : {record['tmdb_id'] or '-'}",
        f"Languages  : {', '.join(record['languages']) or '-'}",
        f"Genres     : {', '.join(record['genres']) or '-'}",
        f"Director   : {record['director'] or '-'}",
        f"Cast       : {', '.join(record['cast']) or '-'}",
        f"Autofilled from TMDB: {'yes' if record['autofilled'] else 'no'}",
        f"Contact    : {record['contact_email'] or '(not given)'}",
        "",
        "Overview:",
        record["overview"] or "-",
        "",
        "Note:",
        record["note"] or "-",
    ]
    if record["tmdb_id"]:
        lines += ["", "To add it:", f"  python -m scripts.add_movie --tmdb-id {record['tmdb_id']}"]
    return "\n".join(lines)


def send_email(record):
    """Send an optional notification; mail failures never discard a saved suggestion."""
    to_addr = (
        os.getenv("SUGGESTION_TO", "").strip()
        or os.getenv("SUGGESTION_DEFAULT_TO", "").strip()
    )
    host = os.getenv("SMTP_HOST", "").strip()
    if not (to_addr and host):
        return False
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", "").strip() or user or to_addr
    if not EMAIL_PATTERN.fullmatch(to_addr) or not EMAIL_PATTERN.fullmatch(sender):
        LOGGER.warning("Suggestion email is not configured with valid addresses.")
        return False
    try:
        port = _integer(os.getenv("SMTP_PORT", "587"), "SMTP_PORT", 1, 65535)
        message = EmailMessage()
        message["Subject"] = f"[Movie request] {record['title']}"[:150]
        message["From"], message["To"] = sender, to_addr
        if record["contact_email"]:
            message["Reply-To"] = record["contact_email"]
        message.set_content(_format_email(record))
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if user:
                server.login(user, password)
            server.send_message(message)
        return True
    except Exception as error:
        LOGGER.warning("Could not send suggestion e-mail (%s).", type(error).__name__)
        return False


def _is_duplicate(existing, candidate):
    candidate_tmdb = normalize_tmdb_id(candidate.get("tmdb_id"))
    existing_tmdb = normalize_tmdb_id(existing.get("tmdb_id"))
    if candidate_tmdb and existing_tmdb and candidate_tmdb == existing_tmdb:
        return True
    title_matches = (
        str(existing.get("title", "")).strip().casefold()
        == candidate["title"].strip().casefold()
    )
    return title_matches and existing.get("year") == candidate["year"]


def save_suggestion(record, log_path=None):
    """Append a suggestion, returning False when a matching record already exists."""
    path = Path(log_path or os.getenv("SUGGESTIONS_LOG", "") or DEFAULT_LOG_PATH).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **record,
    }
    with _SUGGESTION_LOCK:
        if path.is_file():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        existing = json.loads(line)
                    except json.JSONDecodeError:
                        LOGGER.warning("Skipping malformed line in suggestion log.")
                        continue
                    if isinstance(existing, dict) and _is_duplicate(existing, record):
                        return False
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return True

import json
import logging
import os
import re
import threading
import time
from copy import deepcopy
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

TMDB_API_BASE = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
IMAGE_SIZES = {"poster": "w500", "backdrop": "w1280"}
IMAGE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9/_-]+\.(?:jpg|jpeg|png|webp)$", re.IGNORECASE)
IMDB_ID_PATTERN = re.compile(r"^tt\d{7,12}$", re.IGNORECASE)
LOGGER = logging.getLogger(__name__)


class TMDBServiceError(RuntimeError):
    """A failed TMDB lookup with an HTTP status suitable for the local API."""

    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code


def normalize_tmdb_id(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric_id = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not numeric_id.is_finite() or numeric_id <= 0 or numeric_id != numeric_id.to_integral_value():
        return None
    return str(int(numeric_id))


def tmdb_image_url(path, size):
    if size not in {"w342", "w500", "w780", "w1280", "original"}:
        return None
    if not isinstance(path, str) or not IMAGE_PATH_PATTERN.fullmatch(path):
        return None
    return f"{TMDB_IMAGE_BASE}/{size}{path}"


def _empty_artwork():
    return {
        "poster_path": None,
        "backdrop_path": None,
        "poster_url": None,
        "backdrop_url": None,
    }


class TMDBService:
    CACHE_TTL_SECONDS = 12 * 60 * 60
    FAILURE_CACHE_TTL_SECONDS = 15
    BACKOFF_SECONDS = 10
    AUTH_BACKOFF_SECONDS = 5 * 60
    MAX_CACHE_ITEMS = 4096
    MAX_WORKERS = 8
    MAX_RETRIES = 2
    RETRY_DELAYS_SECONDS = (0.1, 0.3)
    RETRYABLE_HTTP_STATUSES = {408, 425, 500, 502, 503, 504}

    def __init__(self, token=None, timeout=3.0):
        configured_token = os.getenv("TMDB_READ_ACCESS_TOKEN", "") if token is None else token
        self._token = configured_token.strip() if isinstance(configured_token, str) else ""
        self._timeout = timeout
        self._cache = {}
        self._inflight = {}
        self._lookup_cache = {}
        self._lookup_inflight = {}
        self._lock = threading.Lock()
        self._backoff_until = 0.0
        self._backoff_status = 503

    @staticmethod
    def _identity(tmdb_id, imdb_id):
        normalized_tmdb_id = normalize_tmdb_id(tmdb_id)
        if normalized_tmdb_id is not None:
            return f"tmdb:{normalized_tmdb_id}", "tmdb", normalized_tmdb_id

        normalized_imdb_id = imdb_id.strip() if isinstance(imdb_id, str) else ""
        if IMDB_ID_PATTERN.fullmatch(normalized_imdb_id):
            normalized_imdb_id = normalized_imdb_id.lower()
            return f"imdb:{normalized_imdb_id}", "imdb", normalized_imdb_id
        return None

    def get_movie_artwork(self, tmdb_id=None, imdb_id=None):
        identity = self._identity(tmdb_id, imdb_id)
        if not self._token or identity is None:
            return _empty_artwork()

        cache_key, identity_type, identity_value = identity
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and cached[0] > now:
                return dict(cached[1])
            if cached:
                self._cache.pop(cache_key, None)
            if self._backoff_until > now:
                return _empty_artwork()

            pending = self._inflight.get(cache_key)
            is_owner = pending is None
            if is_owner:
                pending = threading.Event()
                self._inflight[cache_key] = pending

        if not is_owner:
            if pending.wait(self._timeout + 1):
                with self._lock:
                    cached = self._cache.get(cache_key)
                    if cached and cached[0] > time.monotonic():
                        return dict(cached[1])
            return _empty_artwork()

        artwork = _empty_artwork()
        cache_ttl = self.FAILURE_CACHE_TTL_SECONDS
        try:
            artwork, cache_ttl = self._fetch_artwork(identity_type, identity_value)
        finally:
            with self._lock:
                self._cache[cache_key] = (time.monotonic() + cache_ttl, artwork)
                self._trim_cache()
                event = self._inflight.pop(cache_key, None)
                if event is not None:
                    event.set()
        return dict(artwork)

    def get_movie_artworks(self, movies):
        records = list(movies)
        identities = []
        requests_by_key = {}
        for movie in records:
            tmdb_id = movie.get("tmdb_id") if isinstance(movie, Mapping) else None
            imdb_id = movie.get("imdb_id") if isinstance(movie, Mapping) else None
            identity = self._identity(tmdb_id, imdb_id) if self._token else None
            identities.append(identity)
            if identity is not None:
                requests_by_key.setdefault(identity[0], (tmdb_id, imdb_id))

        if not requests_by_key:
            return [_empty_artwork() for _ in records]

        with ThreadPoolExecutor(max_workers=min(self.MAX_WORKERS, len(requests_by_key))) as executor:
            fetched = executor.map(
                lambda ids: self.get_movie_artwork(*ids),
                requests_by_key.values(),
            )
            artwork_by_key = dict(zip(requests_by_key, fetched))
        return [
            dict(artwork_by_key[identity[0]]) if identity is not None else _empty_artwork()
            for identity in identities
        ]

    def _fetch_artwork(self, identity_type, identity_value):
        if identity_type == "imdb":
            query = urlencode({"external_source": "imdb_id"})
            url = f"{TMDB_API_BASE}/find/{quote(identity_value, safe='')}?{query}"
            payload, cacheable = self._request_json(url)
            if payload is None:
                return _empty_artwork(), (
                    self.CACHE_TTL_SECONDS if cacheable else self.FAILURE_CACHE_TTL_SECONDS
                )
            movie_results = payload.get("movie_results")
            if not isinstance(movie_results, list):
                return _empty_artwork(), self.FAILURE_CACHE_TTL_SECONDS
            match = next(
                (
                    result for result in movie_results
                    if isinstance(result, dict)
                    and normalize_tmdb_id(result.get("id")) is not None
                ),
                None,
            )
            if match is None:
                return _empty_artwork(), self.CACHE_TTL_SECONDS
            artwork = self._artwork_from_payload(match)
            if artwork["poster_url"] or artwork["backdrop_url"]:
                return artwork, self.CACHE_TTL_SECONDS
            movie_id = normalize_tmdb_id(match.get("id"))
        else:
            movie_id = identity_value

        payload, cacheable = self._request_json(f"{TMDB_API_BASE}/movie/{quote(movie_id, safe='')}")
        if payload is None:
            return _empty_artwork(), (
                self.CACHE_TTL_SECONDS if cacheable else self.FAILURE_CACHE_TTL_SECONDS
            )

        return self._artwork_from_payload(payload), self.CACHE_TTL_SECONDS

    @staticmethod
    def _artwork_from_payload(payload):
        poster_path = payload.get("poster_path")
        backdrop_path = payload.get("backdrop_path")
        return {
            "poster_path": poster_path if tmdb_image_url(poster_path, "w500") else None,
            "backdrop_path": backdrop_path if tmdb_image_url(backdrop_path, "w1280") else None,
            "poster_url": tmdb_image_url(poster_path, IMAGE_SIZES["poster"]),
            "backdrop_url": tmdb_image_url(backdrop_path, IMAGE_SIZES["backdrop"]),
        }

    def _request_json(self, url, strict=False):
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
        )
        request_path = urlsplit(url).path

        def failed(message, status):
            if strict:
                raise TMDBServiceError(message, status)
            return None, False

        def retry(attempt, reason):
            if attempt >= self.MAX_RETRIES:
                return False
            delay = self.RETRY_DELAYS_SECONDS[min(attempt, len(self.RETRY_DELAYS_SECONDS) - 1)]
            LOGGER.warning(
                "Retrying TMDB request to %s after %s (retry %s/%s).",
                request_path,
                reason,
                attempt + 1,
                self.MAX_RETRIES,
            )
            time.sleep(delay)
            return True

        for attempt in range(self.MAX_RETRIES + 1):
            try:
                with self._lock:
                    in_backoff = time.monotonic() < self._backoff_until
                    backoff_status = self._backoff_status
                if in_backoff:
                    return failed(
                        "TMDB is temporarily unavailable. Please try again shortly.",
                        backoff_status,
                    )

                with urlopen(request, timeout=self._timeout) as response:
                    payload = json.loads(response.read())
            except HTTPError as error:
                if error.code == 404:
                    return None, True
                if error.code in {429, 401, 403}:
                    backoff = (
                        self.BACKOFF_SECONDS
                        if error.code == 429
                        else self.AUTH_BACKOFF_SECONDS
                    )
                    status = 429 if error.code == 429 else 503
                    with self._lock:
                        self._backoff_status = status
                        self._backoff_until = max(
                            self._backoff_until,
                            time.monotonic() + backoff,
                        )
                    LOGGER.warning(
                        "TMDB returned HTTP %s for %s; applying service-wide cooldown.",
                        error.code,
                        request_path,
                    )
                    return failed(
                        "TMDB is temporarily unavailable. Please try again shortly.",
                        status,
                    )
                if error.code in self.RETRYABLE_HTTP_STATUSES and retry(
                    attempt,
                    f"HTTP {error.code}",
                ):
                    continue
                LOGGER.warning("TMDB returned HTTP %s for %s.", error.code, request_path)
                return failed(
                    "TMDB is temporarily unavailable. Please try again shortly.",
                    502,
                )
            except TimeoutError:
                if retry(attempt, "request timeout"):
                    continue
                LOGGER.warning(
                    "TMDB request to %s timed out after %s seconds.",
                    request_path,
                    self._timeout,
                )
                return failed(
                    "TMDB is temporarily unavailable. Please try again shortly.",
                    503,
                )
            except URLError as error:
                reason = str(error.reason)
                if self._token:
                    reason = reason.replace(self._token, "[redacted]")
                if retry(attempt, f"URL error ({type(error.reason).__name__})"):
                    continue
                LOGGER.warning(
                    "TMDB request to %s failed with URL error: %s.",
                    request_path,
                    reason,
                )
                return failed(
                    "TMDB is temporarily unavailable. Please try again shortly.",
                    503,
                )
            except OSError as error:
                error_type = type(error).__name__
                if retry(attempt, error_type):
                    continue
                LOGGER.warning(
                    "TMDB request to %s failed with %s.",
                    request_path,
                    error_type,
                )
                return failed(
                    "TMDB is temporarily unavailable. Please try again shortly.",
                    503,
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                if retry(attempt, "invalid JSON response"):
                    continue
                LOGGER.warning("TMDB returned invalid JSON for %s.", request_path)
                return failed(
                    "TMDB returned an invalid response. Please try again later.",
                    502,
                )

            if isinstance(payload, dict):
                return payload, True
            if retry(attempt, "invalid response format"):
                continue
            LOGGER.warning("TMDB returned an invalid response for %s.", request_path)
            return failed(
                "TMDB returned an invalid response. Please try again later.",
                502,
            )

        return failed(
            "TMDB is temporarily unavailable. Please try again shortly.",
            503,
        )

    @property
    def configured(self):
        return bool(self._token)

    def search_movies(self, query, limit=8):
        """Search TMDB by title and cache the small result set."""
        query = query.strip() if isinstance(query, str) else ""
        if not query:
            raise ValueError("A non-empty TMDB search query is required.")
        if len(query) > 100:
            raise ValueError("TMDB search query must be 100 characters or fewer.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 8:
            raise ValueError("TMDB search limit must be between 1 and 8.")
        if not self._token:
            return []

        def fetch():
            url = f"{TMDB_API_BASE}/search/movie?" + urlencode(
                {"query": query, "include_adult": "false", "page": 1}
            )
            payload, _cacheable = self._request_json(url, strict=True)
            results = payload.get("results") if payload is not None else []
            if not isinstance(results, list):
                raise TMDBServiceError("TMDB returned invalid search results.", 502)
            output = []
            for item in results[:8]:
                if not isinstance(item, dict):
                    continue
                tmdb_id = normalize_tmdb_id(item.get("id"))
                title = item.get("title")
                if tmdb_id is None or not isinstance(title, str) or not title.strip():
                    continue
                release = item.get("release_date")
                release = release if isinstance(release, str) else ""
                output.append({
                    "tmdb_id": int(tmdb_id),
                    "title": title,
                    "year": int(release[:4]) if release[:4].isdigit() else None,
                    "overview": item.get("overview") if isinstance(item.get("overview"), str) else "",
                    "original_language": item.get("original_language"),
                    "poster_url": tmdb_image_url(item.get("poster_path"), "w342"),
                })
            return output

        results = self._cached_lookup(f"search:{query.casefold()}", fetch, 120)
        return results[:limit]

    def get_movie_for_suggestion(self, tmdb_id):
        """Fetch only the fields needed to prefill a movie suggestion."""
        tmdb_id = normalize_tmdb_id(tmdb_id)
        if not self._token or tmdb_id is None:
            return None

        def names(items, field="name"):
            return [
                item[field].strip()
                for item in items
                if isinstance(item, dict)
                and isinstance(item.get(field), str)
                and item[field].strip()
            ]

        def fetch():
            url = f"{TMDB_API_BASE}/movie/{tmdb_id}?" + urlencode(
                {"append_to_response": "credits,keywords"}
            )
            data, _cacheable = self._request_json(url, strict=True)
            if data is None:
                return None
            credits = data.get("credits")
            credits = credits if isinstance(credits, dict) else {}
            crew = credits.get("crew")
            cast = credits.get("cast")
            spoken = data.get("spoken_languages")
            genres = data.get("genres")
            keyword_data = data.get("keywords")
            keywords = keyword_data.get("keywords") if isinstance(keyword_data, dict) else []
            crew = crew if isinstance(crew, list) else []
            cast = cast if isinstance(cast, list) else []
            spoken = spoken if isinstance(spoken, list) else []
            genres = genres if isinstance(genres, list) else []
            keywords = keywords if isinstance(keywords, list) else []
            language_rows = [
                item for item in spoken
                if isinstance(item, dict)
                and isinstance(item.get("english_name"), str)
                and item["english_name"].strip()
            ]
            original_code = data.get("original_language")
            primary_language = next(
                (
                    item["english_name"] for item in language_rows
                    if item.get("iso_639_1") == original_code
                ),
                language_rows[0]["english_name"] if language_rows else None,
            )
            release = data.get("release_date")
            release = release if isinstance(release, str) else ""
            return {
                "tmdb_id": int(tmdb_id),
                "imdb_id": data.get("imdb_id") if isinstance(data.get("imdb_id"), str) else None,
                "primary_language": primary_language,
                "title": data.get("title") if isinstance(data.get("title"), str) else None,
                "original_title": data.get("original_title") if isinstance(data.get("original_title"), str) else None,
                "year": int(release[:4]) if release[:4].isdigit() else None,
                "release_date": release or None,
                "runtime": data.get("runtime") if isinstance(data.get("runtime"), int) else None,
                "genres": names(genres),
                "languages": names(language_rows, "english_name"),
                "overview": data.get("overview") if isinstance(data.get("overview"), str) else "",
                "tagline": data.get("tagline") if isinstance(data.get("tagline"), str) else "",
                "keywords": names(keywords),
                "directors": [
                    item["name"].strip() for item in crew
                    if isinstance(item, dict)
                    and item.get("job") == "Director"
                    and isinstance(item.get("name"), str)
                    and item["name"].strip()
                ],
                "cast": names(cast[:10]),
                "rating": data.get("vote_average") if isinstance(data.get("vote_average"), (int, float)) else None,
                "votes": data.get("vote_count") if isinstance(data.get("vote_count"), int) else None,
                "poster_url": tmdb_image_url(data.get("poster_path"), "w342"),
            }

        return self._cached_lookup(f"movie:{tmdb_id}", fetch, self.CACHE_TTL_SECONDS)

    def _cached_lookup(self, key, fetch, ttl):
        now = time.monotonic()
        with self._lock:
            cached = self._lookup_cache.get(key)
            if cached and cached[0] > now:
                return deepcopy(cached[1])
            if cached:
                self._lookup_cache.pop(key, None)
            pending = self._lookup_inflight.get(key)
            owner = pending is None
            if owner:
                pending = threading.Event()
                self._lookup_inflight[key] = pending

        if not owner:
            if pending.wait(self._timeout + 1):
                with self._lock:
                    cached = self._lookup_cache.get(key)
                    if cached and cached[0] > time.monotonic():
                        return deepcopy(cached[1])
            raise TMDBServiceError("TMDB lookup did not complete. Please try again.", 503)

        try:
            value = fetch()
        except Exception:
            with self._lock:
                event = self._lookup_inflight.pop(key, None)
                if event is not None:
                    event.set()
            raise
        with self._lock:
            self._lookup_cache[key] = (time.monotonic() + ttl, value)
            event = self._lookup_inflight.pop(key, None)
            if event is not None:
                event.set()
            now = time.monotonic()
            for cached_key in [
                cached_key for cached_key, entry in self._lookup_cache.items()
                if entry[0] <= now
            ]:
                self._lookup_cache.pop(cached_key, None)
            while len(self._lookup_cache) > 512:
                self._lookup_cache.pop(next(iter(self._lookup_cache)))
        return deepcopy(value)

    def _trim_cache(self):
        now = time.monotonic()
        for key in [key for key, entry in self._cache.items() if entry[0] <= now]:
            self._cache.pop(key, None)
        while len(self._cache) > self.MAX_CACHE_ITEMS:
            self._cache.pop(next(iter(self._cache)))

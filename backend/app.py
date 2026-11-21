import math
import logging
import os

import numpy as np
import pandas as pd
from flask import Flask, current_app, jsonify, request

from .model_loader import load_recommender
from .recommender import LANGUAGE_MODES, PRESETS
from .suggestions import (
    RateLimiter,
    ValidationError,
    save_suggestion,
    send_email,
    validate_suggestion,
)
from .tmdb_service import TMDBService, TMDBServiceError, normalize_tmdb_id, tmdb_image_url

LOGGER = logging.getLogger(__name__)


def _rate_limit_from_env(name, default):
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _json_value(value):
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if pd.isna(value):
        return None
    return value


def _movie_details(movie, artwork=None):
    artwork = artwork or {}
    poster_path = artwork.get("poster_path") or _json_value(movie.get("poster_path"))
    backdrop_path = artwork.get("backdrop_path") or _json_value(movie.get("backdrop_path"))
    return {
        "movie_id": _json_value(movie.get("movie_id")),
        "tmdb_id": _json_value(movie.get("tmdb_id")),
        "imdb_id": _json_value(movie.get("imdb_id")),
        "title": _json_value(movie.get("title")),
        "original_title": _json_value(movie.get("original_title")),
        "year": _json_value(movie.get("year")),
        "release_date": _json_value(movie.get("release_date")),
        "runtime": _json_value(movie.get("runtime")),
        "genres": list(movie.get("genres", [])),
        "languages": list(movie.get("languages", [])),
        "primary_language": _json_value(movie.get("primary_language")),
        "overview": _json_value(movie.get("overview")),
        "tagline": _json_value(movie.get("tagline")),
        "rating": _json_value(movie.get("rating")),
        "votes": _json_value(movie.get("votes")),
        "director": _json_value(movie.get("director")),
        "directors": list(movie.get("directors_list", [])),
        "cast": list(movie.get("cast_display", [])),
        "poster_path": poster_path,
        "backdrop_path": backdrop_path,
        "poster_url": artwork.get("poster_url") or tmdb_image_url(poster_path, "w500"),
        "backdrop_url": artwork.get("backdrop_url") or tmdb_image_url(backdrop_path, "w1280"),
        "source": _json_value(movie.get("source")),
    }


def _error(message, status):
    return jsonify({"error": message}), status


def create_app(recommender=None, tmdb_service=None, suggestions_log=None):
    """Create the API and initialize the engine once for this app instance."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    app.config["MOVIE_RECOMMENDER"] = (
        recommender if recommender is not None else load_recommender()
    )
    app.config["TMDB_SERVICE"] = tmdb_service if tmdb_service is not None else TMDBService()
    app.config["SUGGESTIONS_LOG"] = suggestions_log
    suggestion_limiter = RateLimiter(
        limit=_rate_limit_from_env("RATE_LIMIT_SUGGESTIONS_PER_HOUR", 5),
        window=3600,
    )
    recommend_limiter = RateLimiter(
        limit=_rate_limit_from_env("RATE_LIMIT_RECOMMEND_PER_HOUR", 600),
        window=3600,
    )
    lookup_limiter = RateLimiter(
        limit=_rate_limit_from_env("RATE_LIMIT_TMDB_PER_HOUR", 600),
        window=3600,
    )

    @app.errorhandler(413)
    def request_too_large(_exception):
        return _error("Request body must be no larger than 64 KB.", 413)

    @app.route("/api/health", methods=["GET"])
    def health():
        engine = current_app.config["MOVIE_RECOMMENDER"]
        return jsonify({
            "status": "ok",
            "catalogue_count": engine.N,
            "language_count": len(engine.languages()),
        })

    @app.route("/api/languages", methods=["GET"])
    def languages():
        engine = current_app.config["MOVIE_RECOMMENDER"]
        counts = np.asarray(engine.L.sum(axis=0)).ravel()
        eligible_counts = np.asarray(engine.L[engine.eligible].sum(axis=0)).ravel()
        results = [
            {
                "id": name,
                "name": name,
                "movies": int(counts[index]),
                "recommendable": int(eligible_counts[index]),
            }
            for name, index in engine.lang_idx.items()
        ]
        results.sort(key=lambda item: (-item["movies"], item["name"].casefold()))
        return jsonify({"count": len(results), "languages": results})

    @app.route("/api/movies/search", methods=["GET"])
    def search_movies():
        query = request.args.get("q", "").strip()
        if not query:
            return _error("Query parameter 'q' is required.", 400)
        if len(query) > 100:
            return _error("Search query must be 100 characters or fewer.", 400)

        try:
            limit = int(request.args.get("limit", "20"))
        except ValueError:
            return _error("Query parameter 'limit' must be an integer.", 400)
        if not 1 <= limit <= 50:
            return _error("Query parameter 'limit' must be between 1 and 50.", 400)

        catalogue = current_app.config["MOVIE_RECOMMENDER"].m
        matching = catalogue.loc[
            catalogue["title"].fillna("").str.contains(query, case=False, regex=False)
        ].copy()
        matching["_exact_title"] = (
            matching["title"].fillna("").str.casefold() == query.casefold()
        )
        matching = matching.sort_values(
            ["_exact_title", "votes"],
            ascending=[False, False],
            na_position="last",
        ).head(limit)

        movie_rows = [movie for _, movie in matching.iterrows()]
        artwork = current_app.config["TMDB_SERVICE"].get_movie_artworks([
            {"tmdb_id": movie.get("tmdb_id"), "imdb_id": movie.get("imdb_id")}
            for movie in movie_rows
        ])

        results = []
        for movie, movie_artwork in zip(movie_rows, artwork):
            details = _movie_details(movie, movie_artwork)
            results.append({
                key: details[key]
                for key in [
                    "movie_id", "title", "year", "genres", "languages",
                    "primary_language", "rating", "overview", "poster_path", "tmdb_id",
                    "poster_url",
                ]
            })
        return jsonify({"count": len(results), "results": results})

    @app.route("/api/movie/<movie_id>", methods=["GET"])
    def get_movie(movie_id):
        engine = current_app.config["MOVIE_RECOMMENDER"]
        index = engine.id_to_index.get(movie_id)
        if index is None:
            return _error(f"Movie '{movie_id}' was not found.", 404)
        movie = engine.m.iloc[index]
        artwork = current_app.config["TMDB_SERVICE"].get_movie_artwork(
            movie.get("tmdb_id"),
            movie.get("imdb_id"),
        )
        return jsonify(_movie_details(movie, artwork))

    @app.route("/api/recommend", methods=["POST"])
    def recommend():
        if not recommend_limiter.allow(request.remote_addr or "unknown"):
            return _error("Too many recommendations. Please try again later.", 429)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("Request body must be a JSON object.", 400)

        movie_id = payload.get("movie_id")
        if not isinstance(movie_id, str) or not movie_id.strip():
            return _error("A non-empty 'movie_id' is required.", 400)
        movie_id = movie_id.strip()

        engine = current_app.config["MOVIE_RECOMMENDER"]
        if movie_id not in engine.id_to_index:
            return _error(f"Movie '{movie_id}' was not found.", 404)

        n = payload.get("n", 10)
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 50:
            return _error("'n' must be an integer between 1 and 50.", 400)

        language_mode = payload.get("language_mode", "balanced")
        if not isinstance(language_mode, str) or language_mode not in LANGUAGE_MODES:
            return _error(
                f"'language_mode' must be one of: {', '.join(LANGUAGE_MODES)}.",
                400,
            )

        language = payload.get("language")
        if language is not None and not isinstance(language, str):
            return _error("'language' must be a string.", 400)
        language = language.strip() if language else None
        language_lookup = {name.casefold(): name for name in engine.lang_idx}
        if language:
            language = language_lookup.get(language.casefold())
            if language is None:
                return _error(f"Unknown language '{payload.get('language')}'.", 400)

        languages = payload.get("languages")
        if languages is not None:
            if (
                not isinstance(languages, list)
                or len(languages) > 5
                or not all(isinstance(item, str) and item.strip() for item in languages)
            ):
                return _error("'languages' must be a list of at most 5 non-empty language names.", 400)
            canonical_languages = []
            for item in languages:
                canonical = language_lookup.get(item.strip().casefold())
                if canonical is None:
                    return _error(f"Unknown language '{item.strip()}'.", 400)
                if canonical not in canonical_languages:
                    canonical_languages.append(canonical)
            languages = canonical_languages

        language_balance = payload.get("language_balance", False)
        if not isinstance(language_balance, bool):
            return _error("'language_balance' must be a boolean.", 400)
        if language_balance and (languages is None or len(languages) < 2):
            return _error("'language_balance' requires at least two selected languages.", 400)

        diversify = payload.get("diversify", False)
        if not isinstance(diversify, bool):
            return _error("'diversify' must be a boolean.", 400)

        quality_weight = payload.get("quality_weight", 0.1)
        if (
            isinstance(quality_weight, bool)
            or not isinstance(quality_weight, (int, float))
            or not math.isfinite(quality_weight)
            or not 0 <= quality_weight <= 1
        ):
            return _error("'quality_weight' must be a number between 0 and 1.", 400)

        preset = payload.get("preset")
        if preset is not None and (
            not isinstance(preset, str) or preset not in PRESETS
        ):
            return _error(
                f"'preset' must be one of: {', '.join(PRESETS)}.",
                400,
            )

        try:
            recommendations = engine.recommend_by_movie_id(
                movie_id,
                n=n,
                language=language,
                language_mode=language_mode,
                quality_weight=quality_weight,
                diversify=diversify,
                weights=PRESETS[preset] if preset else None,
                verbose=False,
                languages=languages or None,
                lang_balance=language_balance,
            )
        except KeyError as error:
            return _error(str(error.args[0]), 400)

        results = [
            {key: _json_value(value) for key, value in row.items()}
            for row in recommendations.to_dict(orient="records")
        ]
        movie_rows = []
        for result in results:
            index = engine.id_to_index.get(result.get("Movie_ID"))
            movie_rows.append(engine.m.iloc[index] if index is not None else None)
        artwork = current_app.config["TMDB_SERVICE"].get_movie_artworks([
            {"tmdb_id": movie.get("tmdb_id"), "imdb_id": movie.get("imdb_id")}
            if movie is not None else {}
            for movie in movie_rows
        ])
        for result, movie, movie_artwork in zip(results, movie_rows, artwork):
            existing_path = _json_value(movie.get("poster_path")) if movie is not None else None
            result["poster_url"] = (
                movie_artwork.get("poster_url")
                or tmdb_image_url(existing_path, "w500")
            )
        return jsonify({"count": len(results), "recommendations": results})

    @app.route("/api/tmdb/search", methods=["GET"])
    def tmdb_search():
        if not lookup_limiter.allow(request.remote_addr or "unknown"):
            return _error("Too many TMDB lookups. Please try again later.", 429)
        query = request.args.get("q", "").strip()
        if not query:
            return _error("Query parameter 'q' is required.", 400)
        if len(query) > 100:
            return _error("Search query must be 100 characters or fewer.", 400)
        service = current_app.config["TMDB_SERVICE"]
        if not service.configured:
            return jsonify({"available": False, "results": []})
        try:
            results = service.search_movies(query)
        except ValueError as error:
            return _error(str(error), 400)
        except TMDBServiceError as error:
            return _error(str(error), error.status_code)
        return jsonify({"available": True, "results": results})

    @app.route("/api/tmdb/movie/<int:tmdb_id>", methods=["GET"])
    def tmdb_movie(tmdb_id):
        if not lookup_limiter.allow(request.remote_addr or "unknown"):
            return _error("Too many TMDB lookups. Please try again later.", 429)
        if tmdb_id <= 0:
            return _error("TMDB movie ID must be positive.", 400)
        service = current_app.config["TMDB_SERVICE"]
        if not service.configured:
            return _error("TMDB lookup is not configured.", 503)
        try:
            details = service.get_movie_for_suggestion(tmdb_id)
        except TMDBServiceError as error:
            return _error(str(error), error.status_code)
        if details is None:
            return _error("Movie details were not found on TMDB.", 404)
        return jsonify(details)

    @app.route("/api/suggestions", methods=["POST"])
    def suggest_movie():
        if not suggestion_limiter.allow(request.remote_addr or "unknown"):
            return _error("You have sent several requests recently. Please try again later.", 429)
        try:
            record = validate_suggestion(request.get_json(silent=True))
        except ValidationError as error:
            return _error(str(error), 400)

        engine = current_app.config["MOVIE_RECOMMENDER"]
        known = engine.m
        existing = None
        if record["tmdb_id"] is not None:
            matching = known["tmdb_id"].map(normalize_tmdb_id) == str(record["tmdb_id"])
            if matching.any():
                existing = known.loc[matching, "movie_id"].iloc[0]
        if existing is not None:
            return jsonify({"status": "exists", "movie_id": str(existing)})

        saved = None
        try:
            saved = save_suggestion(record, current_app.config["SUGGESTIONS_LOG"])
        except OSError:
            LOGGER.exception("Could not save a movie suggestion.")
        if saved is False:
            return jsonify({"status": "duplicate", "message": "A similar suggestion was already received."})

        emailed = send_email(record)
        if saved is None and not emailed:
            return _error("The suggestion could not be saved or emailed. Please try again later.", 500)
        return jsonify({
            "status": "received",
            "emailed": emailed,
            "saved": saved is True,
        }), 201

    return app


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)

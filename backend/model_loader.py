import os
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from .recommender import (
    MovieRecommender,
    REQUIRED_CATALOGUE_COLUMNS,
    build_feature_matrices,
    prepare_catalogue,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "movie_project" / "data"
DEFAULT_CATALOGUE_PATH = DATA_DIR / "final" / "movies_model_ready.csv"
DEFAULT_ADDED_PATH = DATA_DIR / "user_added" / "movies_added.csv"

load_dotenv(PROJECT_ROOT / ".env")

KEEP_COLUMNS = [
    "movie_id", "source_primary", "tmdb_id", "imdb_id", "title", "original_title",
    "year", "release_date", "runtime", "genres", "genres_recommender", "keywords",
    "overview", "tagline", "director", "directors", "directors_recommender",
    "cast_top10", "cast_recommender", "languages_available", "primary_language",
    "rating", "votes", "poster_path", "recsys_query_ok", "recsys_candidate_default",
]


def _normalise_tmdb_id(value):
    if pd.isna(value):
        return None
    try:
        numeric_id = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not numeric_id.is_finite() or numeric_id <= 0 or numeric_id != numeric_id.to_integral_value():
        return None
    return str(int(numeric_id))


def _project_path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def resolve_catalogue_path(catalogue_path=None):
    if catalogue_path is not None:
        return Path(catalogue_path).expanduser()

    env_path = os.getenv("MOVIE_DATA_PATH", "").strip()
    if env_path:
        return _project_path(env_path)

    compressed_path = DEFAULT_CATALOGUE_PATH.with_name("movies_model_ready.csv.gz")
    if compressed_path.is_file():
        return compressed_path
    return DEFAULT_CATALOGUE_PATH


def read_table(path):
    """Read the app's required columns from a CSV or gzip-compressed CSV."""
    path = Path(path)
    if path.suffix.lower() not in {".csv", ".gz"}:
        raise ValueError(f"Unsupported catalogue format: {path.suffix or '(no extension)'}")
    return pd.read_csv(path, low_memory=False, usecols=lambda column: column in KEEP_COLUMNS)


def load_catalogue_frame(catalogue_path=None, added_path=None):
    path = resolve_catalogue_path(catalogue_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Model-ready catalogue not found: {path}\n"
            "Put movies_model_ready.csv or movies_model_ready.csv.gz in "
            "movie_project/data/final, or set MOVIE_DATA_PATH."
        )
    movies = read_table(path)

    extra_value = (
        str(added_path)
        if added_path is not None
        else os.getenv("MOVIE_ADDED_PATH", "").strip()
    )
    extra = _project_path(extra_value) if extra_value else DEFAULT_ADDED_PATH
    if extra.is_file():
        added = pd.read_csv(extra, low_memory=False)
        if "movie_id" not in added.columns:
            raise ValueError(f"Added-movie file has no 'movie_id' column: {extra}")
        missing_columns = [
            column for column in REQUIRED_CATALOGUE_COLUMNS
            if column not in added.columns
        ]
        if missing_columns:
            raise ValueError(
                f"Added-movie file is missing required columns: {missing_columns}"
            )
        if (
            added["movie_id"].isna().any()
            or added["movie_id"].astype(str).str.strip().eq("").any()
            or added["title"].isna().any()
            or added["title"].astype(str).str.strip().eq("").any()
        ):
            raise ValueError("Added-movie records must have non-empty movie IDs and titles.")
        if added["movie_id"].duplicated().any():
            raise ValueError("Added-movie file contains duplicate movie_id values.")
        added = added.reindex(columns=movies.columns)
        added = added.dropna(subset=["movie_id"])

        known_movie_ids = set(movies["movie_id"].dropna().astype(str))
        known_tmdb_ids = {
            identifier for identifier in movies["tmdb_id"].map(_normalise_tmdb_id)
            if identifier is not None
        }
        known_imdb_ids = {
            identifier.casefold() for identifier in movies["imdb_id"].dropna().astype(str)
        }
        keep_rows = []
        for row in added.to_dict(orient="records"):
            movie_id = str(row.get("movie_id", "")).strip()
            tmdb_id = _normalise_tmdb_id(row.get("tmdb_id"))
            imdb_value = row.get("imdb_id")
            imdb_id = (
                imdb_value.strip().casefold()
                if isinstance(imdb_value, str)
                else ""
            )
            if (
                not movie_id
                or movie_id in known_movie_ids
                or (tmdb_id is not None and tmdb_id in known_tmdb_ids)
                or (imdb_id and imdb_id in known_imdb_ids)
            ):
                continue
            keep_rows.append(row)
            known_movie_ids.add(movie_id)
            if tmdb_id is not None:
                known_tmdb_ids.add(tmdb_id)
            if imdb_id:
                known_imdb_ids.add(imdb_id)
        if keep_rows:
            movies = pd.concat(
                [movies, pd.DataFrame(keep_rows, columns=movies.columns)],
                ignore_index=True,
            )
    return movies


def load_recommender(catalogue_path=None, added_path=None):
    """Build one recommender instance; call once during backend startup."""
    movies_raw = load_catalogue_frame(catalogue_path, added_path)
    movies = prepare_catalogue(movies_raw)
    vectorizers, matrices = build_feature_matrices(movies)
    return MovieRecommender(movies, matrices, vectorizers)

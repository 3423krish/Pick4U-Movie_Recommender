import argparse
import json
import os
import tempfile
from pathlib import Path

import pandas as pd

from backend.model_loader import DEFAULT_ADDED_PATH, KEEP_COLUMNS, load_catalogue_frame
from backend.suggestions import DEFAULT_LOG_PATH
from backend.tmdb_service import TMDBService, TMDBServiceError, normalize_tmdb_id


def _names(value):
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def row_from_tmdb(movie):
    genres = "|".join(_names(movie.get("genres", [])))
    languages = "|".join(_names(movie.get("languages", [])))
    if not languages and movie.get("primary_language"):
        languages = str(movie["primary_language"]).strip()
    directors = "|".join(_names(movie.get("directors", [])))
    cast = "|".join(_names(movie.get("cast", [])))
    row = {column: None for column in KEEP_COLUMNS}
    row.update({
        "movie_id": f"tmdb:{movie['tmdb_id']}",
        "source_primary": "tmdb",
        "tmdb_id": movie["tmdb_id"],
        "imdb_id": movie.get("imdb_id"),
        "title": movie["title"],
        "original_title": movie.get("original_title"),
        "year": movie.get("year"),
        "release_date": movie.get("release_date"),
        "runtime": movie.get("runtime"),
        "genres": genres,
        "genres_recommender": genres,
        "keywords": "|".join(_names(movie.get("keywords", []))),
        "overview": movie.get("overview") or "",
        "tagline": movie.get("tagline") or "",
        "director": directors,
        "directors": directors,
        "directors_recommender": directors,
        "cast_top10": cast,
        "cast_recommender": cast,
        "languages_available": languages,
        "primary_language": movie.get("primary_language"),
        "rating": movie.get("rating"),
        "votes": movie.get("votes"),
        "recsys_query_ok": True,
        "recsys_candidate_default": True,
    })
    return row


def _suggestion_ids(path):
    if not path.is_file():
        return []
    ids = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON in suggestion log at line {line_number}.") from error
            if not isinstance(record, dict):
                raise ValueError(f"Invalid suggestion record at line {line_number}.")
            tmdb_id = normalize_tmdb_id(record.get("tmdb_id"))
            if tmdb_id is not None:
                ids.append(int(tmdb_id))
    return ids


def _atomic_write(frame, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            frame.to_csv(handle, index=False)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tmdb-id", type=int, nargs="*", default=[])
    parser.add_argument("--from-suggestions", action="store_true")
    parser.add_argument("--out", default=str(DEFAULT_ADDED_PATH))
    args = parser.parse_args(argv)
    if any(tmdb_id <= 0 for tmdb_id in args.tmdb_id):
        parser.error("TMDB IDs must be positive integers.")

    ids = list(args.tmdb_id)
    if args.from_suggestions:
        suggestions_path = Path(
            os.getenv("SUGGESTIONS_LOG", "").strip() or DEFAULT_LOG_PATH
        ).expanduser()
        if not suggestions_path.is_absolute():
            suggestions_path = Path.cwd() / suggestions_path
        try:
            ids.extend(_suggestion_ids(suggestions_path))
        except (OSError, ValueError) as error:
            parser.error(str(error))
    ids = list(dict.fromkeys(ids))
    if not ids:
        parser.error("Nothing to add. Pass --tmdb-id or --from-suggestions.")

    tmdb = TMDBService(timeout=10)
    if not tmdb.configured:
        parser.error("TMDB_READ_ACCESS_TOKEN is not set in the repository .env file.")

    output = Path(args.out).expanduser()
    if not output.is_absolute():
        output = Path.cwd() / output
    try:
        catalogue = load_catalogue_frame(added_path=output)
    except (OSError, ValueError) as error:
        parser.error(f"Could not validate the current catalogue: {error}")

    known_movie_ids = set(catalogue["movie_id"].dropna().astype(str))
    known_tmdb_ids = {
        identifier for identifier in catalogue["tmdb_id"].map(normalize_tmdb_id)
        if identifier is not None
    }
    known_imdb_ids = {
        identifier.casefold() for identifier in catalogue["imdb_id"].dropna().astype(str)
    }
    rows = []
    for tmdb_id in ids:
        identifier = str(tmdb_id)
        if identifier in known_tmdb_ids or f"tmdb:{identifier}" in known_movie_ids:
            print(f"skip   tmdb:{identifier}: already in the catalogue")
            continue
        try:
            details = tmdb.get_movie_for_suggestion(tmdb_id)
        except TMDBServiceError as error:
            parser.error(f"TMDB lookup failed for {tmdb_id}: {error}")
        if not details or not details.get("title"):
            print(f"skip   tmdb:{identifier}: TMDB returned no usable movie details")
            continue
        imdb_id = details.get("imdb_id")
        if isinstance(imdb_id, str) and imdb_id.casefold() in known_imdb_ids:
            print(f"skip   tmdb:{identifier}: IMDb ID is already in the catalogue")
            continue

        row = row_from_tmdb(details)
        rows.append(row)
        known_movie_ids.add(row["movie_id"])
        known_tmdb_ids.add(identifier)
        if isinstance(imdb_id, str) and imdb_id:
            known_imdb_ids.add(imdb_id.casefold())

    if not rows:
        print("No new movies to add.")
        return

    additions = pd.DataFrame(rows, columns=KEEP_COLUMNS)
    if output.is_file():
        current = pd.read_csv(output, low_memory=False)
        current = current.reindex(columns=KEEP_COLUMNS)
        additions = pd.concat([current, additions], ignore_index=True)
    if additions["movie_id"].isna().any() or additions["movie_id"].duplicated().any():
        parser.error("The added-movie file contains missing or duplicate movie IDs.")

    _atomic_write(additions, output)
    print(f"Saved {len(rows)} movie(s) to {output}. Restart Flask to rebuild the model.")


if __name__ == "__main__":
    main()

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from backend.model_loader import KEEP_COLUMNS, load_catalogue_frame, read_table
from scripts import add_movie, make_slim_dataset


def catalogue_row(movie_id, tmdb_id, title):
    row = {column: None for column in KEEP_COLUMNS}
    row.update({
        "movie_id": movie_id,
        "source_primary": "tmdb",
        "tmdb_id": tmdb_id,
        "imdb_id": None,
        "title": title,
        "year": 2020,
        "genres": "Drama",
        "genres_recommender": "Drama",
        "keywords": "family",
        "overview": "A story.",
        "tagline": "",
        "director": "",
        "directors": "",
        "directors_recommender": "",
        "cast_top10": "",
        "cast_recommender": "",
        "languages_available": "Hindi",
        "primary_language": "Hindi",
        "rating": 7.0,
        "votes": 100,
        "runtime": 100,
        "recsys_query_ok": True,
        "recsys_candidate_default": True,
    })
    return row


class CatalogueScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp_dir.cleanup)
        self.directory = Path(self.temp_dir.name)

    def test_slim_csv_gzip_round_trip_retains_app_columns(self):
        source = self.directory / "movies_model_ready.csv"
        pd.DataFrame(
            [catalogue_row("tmdb:1", 1, "Original")],
            columns=KEEP_COLUMNS,
        ).to_csv(source, index=False)
        source_bytes = source.read_bytes()
        original = read_table(source)

        make_slim_dataset.main([
            "--src", str(source),
            "--out-dir", str(self.directory),
        ])

        compressed = self.directory / "movies_model_ready.csv.gz"
        round_trip = read_table(compressed)
        pd.testing.assert_frame_equal(
            original,
            round_trip[original.columns],
            check_dtype=False,
        )
        for column in original.columns:
            if original[column].notna().any():
                self.assertEqual(original[column].dtype, round_trip[column].dtype, column)
        self.assertEqual(source.read_bytes(), source_bytes)

    def test_loader_deduplicates_user_added_movies_by_tmdb_id(self):
        source = self.directory / "movies_model_ready.csv"
        added_path = self.directory / "movies_added.csv"
        pd.DataFrame([catalogue_row("tmdb:9", 9.0, "Original")], columns=KEEP_COLUMNS).to_csv(source, index=False)
        pd.DataFrame([
            catalogue_row("tmdb:10", "9", "Duplicate TMDB ID"),
            catalogue_row("tmdb:11", 11, "New"),
        ], columns=KEEP_COLUMNS).to_csv(added_path, index=False)

        loaded = load_catalogue_frame(source, added_path)

        self.assertEqual(loaded["movie_id"].tolist(), ["tmdb:9", "tmdb:11"])
        self.assertEqual(loaded["title"].tolist(), ["Original", "New"])

    def test_add_movie_script_is_idempotent_and_preserves_source(self):
        source = self.directory / "movies_model_ready.csv"
        output = self.directory / "movies_added.csv"
        original = pd.DataFrame([catalogue_row("tmdb:19995", 19995, "Avatar")], columns=KEEP_COLUMNS)
        original.to_csv(source, index=False)
        original_bytes = source.read_bytes()

        class FakeTMDB:
            configured = True

            def __init__(self, **_kwargs):
                pass

            def get_movie_for_suggestion(self, tmdb_id):
                return {
                    "tmdb_id": tmdb_id,
                    "imdb_id": "tt9999999",
                    "title": "New Film",
                    "original_title": "New Film",
                    "year": 2022,
                    "release_date": "2022-01-01",
                    "runtime": 110,
                    "genres": ["Drama"],
                    "languages": ["Hindi"],
                    "primary_language": "Hindi",
                    "overview": "A new story.",
                    "tagline": "",
                    "keywords": ["family"],
                    "directors": ["Director"],
                    "cast": ["Actor"],
                    "rating": 7.5,
                    "votes": 200,
                }

        with (
            patch("backend.model_loader.DEFAULT_CATALOGUE_PATH", source),
            patch.object(add_movie, "TMDBService", FakeTMDB),
        ):
            add_movie.main(["--tmdb-id", "777", "19995", "--out", str(output)])
            add_movie.main(["--tmdb-id", "777", "--out", str(output)])

        additions = pd.read_csv(output, low_memory=False)
        self.assertEqual(additions["movie_id"].tolist(), ["tmdb:777"])
        self.assertEqual(list(additions.columns), KEEP_COLUMNS)
        self.assertEqual(source.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()

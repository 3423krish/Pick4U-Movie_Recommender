import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from backend.app import create_app
from backend.model_loader import load_recommender
from backend.suggestions import RateLimiter
from backend.tmdb_service import TMDBServiceError


class OfflineTMDBService:
    configured = False

    def get_movie_artwork(self, tmdb_id=None, imdb_id=None):
        return {}

    def get_movie_artworks(self, movies):
        return [{} for _movie in movies]


class RecommenderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recommender = load_recommender()
        cls.client = create_app(
            cls.recommender,
            tmdb_service=OfflineTMDBService(),
        ).test_client()

    def test_avatar_matches_v2_notebook_baseline(self):
        results = self.recommender.recommend(
            "Avatar",
            year=2009,
            n=10,
            language_mode="ignore",
            diversify=False,
            verbose=False,
        )
        self.assertEqual(
            results["Movie_ID"].head(3).tolist(),
            ["tmdb:54138", "imdb:tt1349460", "tmdb:13475"],
        )

    def test_strict_language_mode_with_mmr(self):
        results = self.recommender.recommend(
            "3 Idiots",
            year=2009,
            language="Hindi",
            language_mode="strict",
            diversify=True,
            n=5,
            verbose=False,
        )
        self.assertTrue(len(results))
        self.assertEqual(results["Movie_ID"].nunique(), len(results))
        self.assertTrue(
            all("Hindi" in languages.split(", ") for languages in results["Language"])
        )

    def test_cold_start_preference_recommendations(self):
        results = self.recommender.recommend_by_preferences(
            genres=["Comedy"],
            language_mode="ignore",
            diversify=True,
            n=5,
        )
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 5)

    def test_api_health_search_and_movie_details(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json["catalogue_count"], self.recommender.N)

        search = self.client.get("/api/movies/search?q=Inception")
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json["results"][0]["title"], "Inception")

        movie_id = search.json["results"][0]["movie_id"]
        details = self.client.get(f"/api/movie/{movie_id}")
        self.assertEqual(details.status_code, 200)
        self.assertEqual(details.json["movie_id"], movie_id)
        self.assertIn("overview", details.json)

    def test_api_recommendations_are_rate_limited(self):
        with patch.dict(os.environ, {"RATE_LIMIT_RECOMMEND_PER_HOUR": "1"}):
            client = create_app(
                self.recommender,
                tmdb_service=OfflineTMDBService(),
            ).test_client()

        payload = {"movie_id": "tmdb:19995", "n": 1, "language_mode": "ignore"}
        first = client.post("/api/recommend", json=payload)
        limited = client.post("/api/recommend", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(limited.status_code, 429)
        self.assertIn("too many recommendations", limited.json["error"].lower())

    def _configured_rate_limits(self, environment):
        real_limiter = RateLimiter
        limits = []

        def capture_limiter(limit, window):
            limits.append((limit, window))
            return real_limiter(limit=limit, window=window)

        with (
            patch.dict(os.environ, environment, clear=True),
            patch("backend.app.RateLimiter", side_effect=capture_limiter),
        ):
            create_app(
                self.recommender,
                tmdb_service=OfflineTMDBService(),
            )
        return limits

    def test_rate_limit_environment_defaults(self):
        self.assertEqual(
            self._configured_rate_limits({}),
            [(5, 3600), (600, 3600), (600, 3600)],
        )

    def test_rate_limit_environment_overrides(self):
        self.assertEqual(
            self._configured_rate_limits({
                "RATE_LIMIT_RECOMMEND_PER_HOUR": "45",
                "RATE_LIMIT_TMDB_PER_HOUR": "90",
                "RATE_LIMIT_SUGGESTIONS_PER_HOUR": "8",
            }),
            [(8, 3600), (45, 3600), (90, 3600)],
        )

    def test_invalid_rate_limit_environment_uses_defaults(self):
        self.assertEqual(
            self._configured_rate_limits({
                "RATE_LIMIT_RECOMMEND_PER_HOUR": "not-a-number",
                "RATE_LIMIT_TMDB_PER_HOUR": "-1",
                "RATE_LIMIT_SUGGESTIONS_PER_HOUR": "0",
            }),
            [(5, 3600), (600, 3600), (600, 3600)],
        )

    def test_api_adds_tmdb_artwork_urls_to_current_movie_responses(self):
        class FakeTMDBService:
            def __init__(self):
                self.artwork_batches = []

            def get_movie_artwork(self, tmdb_id=None, imdb_id=None):
                return {
                    "poster_path": "/poster.jpg",
                    "backdrop_path": "/backdrop.jpg",
                    "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
                    "backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
                }

            def get_movie_artworks(self, movies):
                self.artwork_batches.append(movies)
                return [
                    {
                        "poster_path": "/poster.jpg",
                        "backdrop_path": "/backdrop.jpg",
                        "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
                        "backdrop_url": "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
                    }
                    for _ in movies
                ]

        fake_service = FakeTMDBService()
        with patch("backend.app.TMDBService", return_value=fake_service):
            client = create_app(self.recommender).test_client()

        search = client.get("/api/movies/search?q=3%20Idiots")
        self.assertEqual(search.status_code, 200)
        movie = search.json["results"][0]
        self.assertEqual(movie["title"], "3 Idiots")
        self.assertIsNone(movie["tmdb_id"])
        self.assertEqual(fake_service.artwork_batches[0][0]["imdb_id"], "tt1187043")
        self.assertEqual(movie["poster_path"], "/poster.jpg")
        self.assertEqual(
            movie["poster_url"],
            "https://image.tmdb.org/t/p/w500/poster.jpg",
        )

        details = client.get(f"/api/movie/{movie['movie_id']}")
        self.assertEqual(details.status_code, 200)
        self.assertIn("overview", details.json)
        self.assertEqual(details.json["backdrop_path"], "/backdrop.jpg")
        self.assertEqual(
            details.json["backdrop_url"],
            "https://image.tmdb.org/t/p/w1280/backdrop.jpg",
        )

        recommendations = client.post(
            "/api/recommend",
            json={
                "movie_id": movie["movie_id"],
                "n": 5,
                "language_mode": "ignore",
                "diversify": False,
                "quality_weight": 0.1,
                "preset": "balanced",
            },
        )
        self.assertEqual(recommendations.status_code, 200)
        self.assertTrue(recommendations.json["recommendations"])
        self.assertTrue(
            all(
                result["poster_url"].startswith("https://image.tmdb.org/t/p/w500/")
                and "Why" in result
                for result in recommendations.json["recommendations"]
            )
        )

    def test_api_recommendation_options_and_validation(self):
        seed_index = self.recommender.find_movie("3 Idiots", year=2009)
        movie_id = self.recommender.keys[seed_index]
        response = self.client.post(
            "/api/recommend",
            json={
                "movie_id": movie_id,
                "n": 5,
                "language": "Hindi",
                "language_mode": "strict",
                "diversify": True,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.json["count"], 0)
        self.assertTrue(
            all(
                "Hindi" in movie["Language"].split(", ")
                for movie in response.json["recommendations"]
            )
        )

        invalid = self.client.post("/api/recommend", json={"movie_id": "missing"})
        self.assertEqual(invalid.status_code, 404)
        self.assertIn("error", invalid.json)

        bad_query = self.client.get("/api/movies/search")
        self.assertEqual(bad_query.status_code, 400)
        self.assertIn("error", bad_query.json)

    def test_api_rejects_invalid_options(self):
        seed_index = self.recommender.find_movie("Avatar", year=2009)
        movie_id = self.recommender.keys[seed_index]
        invalid_bodies = [
            {"movie_id": movie_id, "n": 0},
            {"movie_id": movie_id, "language_mode": "unknown"},
            {"movie_id": movie_id, "language": "Not A Language"},
        ]
        for body in invalid_bodies:
            with self.subTest(body=body):
                response = self.client.post("/api/recommend", json=body)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json)

        invalid_limit = self.client.get("/api/movies/search?q=Avatar&limit=1000")
        self.assertEqual(invalid_limit.status_code, 400)

    def test_api_languages_and_balanced_multi_language_recommendations(self):
        response = self.client.get("/api/languages")
        self.assertEqual(response.status_code, 200)
        language_rows = response.json["languages"]
        names = [row["name"] for row in language_rows]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all(row["id"] == row["name"] for row in language_rows))

        response = self.client.post(
            "/api/recommend",
            json={
                "movie_id": "tmdb:19995",
                "n": 10,
                "languages": ["hindi", "tamil"],
                "language_mode": "strict",
                "language_balance": True,
                "diversify": True,
            },
        )
        self.assertEqual(response.status_code, 200, response.json)
        results = response.json["recommendations"]
        self.assertEqual(response.json["count"], 10)
        self.assertEqual(len({result["Movie_ID"] for result in results}), 10)
        language_values = [result["Language"].split(", ") for result in results]
        self.assertTrue(all({"Hindi", "Tamil"} & set(languages) for languages in language_values))
        for language in ("Hindi", "Tamil"):
            self.assertGreaterEqual(
                sum(language in values for values in language_values),
                5,
            )

    def test_api_validates_multi_language_parameters(self):
        invalid_bodies = [
            {"movie_id": "tmdb:19995", "languages": "Hindi"},
            {"movie_id": "tmdb:19995", "languages": ["Klingon"]},
            {"movie_id": "tmdb:19995", "languages": ["Hindi"] * 6},
            {"movie_id": "tmdb:19995", "languages": ["Hindi"], "language_balance": True},
        ]
        for payload in invalid_bodies:
            with self.subTest(payload=payload):
                response = self.client.post("/api/recommend", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json)

    def test_tmdb_lookup_endpoints_and_suggestion_submission(self):
        class FakeTMDBService:
            configured = True

            def search_movies(self, query):
                return [{"tmdb_id": 991, "title": query, "year": 2022, "poster_url": None}]

            def get_movie_for_suggestion(self, tmdb_id):
                return {"tmdb_id": tmdb_id, "title": "Suggested Film"}

            def get_movie_artwork(self, tmdb_id=None, imdb_id=None):
                return {}

            def get_movie_artworks(self, movies):
                return [{} for _movie in movies]

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            log_path = Path(directory) / "suggestions.jsonl"
            client = create_app(
                self.recommender,
                tmdb_service=FakeTMDBService(),
                suggestions_log=log_path,
            ).test_client()
            search = client.get("/api/tmdb/search?q=Kantara")
            self.assertEqual(search.status_code, 200)
            self.assertEqual(search.json["results"][0]["tmdb_id"], 991)
            details = client.get("/api/tmdb/movie/991")
            self.assertEqual(details.status_code, 200)
            self.assertEqual(details.json["title"], "Suggested Film")

            with patch("backend.app.send_email", return_value=False):
                submitted = client.post(
                    "/api/suggestions",
                    json={"title": "New Film", "year": 2022, "contact_email": "a@example.com"},
                )
                duplicate = client.post(
                    "/api/suggestions",
                    json={"title": "new film", "year": 2022},
                )
            self.assertEqual(submitted.status_code, 201)
            self.assertEqual(submitted.json["status"], "received")
            self.assertEqual(duplicate.status_code, 200)
            self.assertEqual(duplicate.json["status"], "duplicate")
            self.assertTrue(log_path.is_file())

            exists = client.post(
                "/api/suggestions",
                json={"title": "Avatar", "tmdb_id": 19995},
            )
            self.assertEqual(exists.status_code, 200)
            self.assertEqual(exists.json["status"], "exists")
            self.assertEqual(exists.json["movie_id"], "tmdb:19995")

    def test_suggestion_email_succeeds_when_local_save_fails(self):
        client = create_app(
            self.recommender,
            tmdb_service=OfflineTMDBService(),
        ).test_client()
        with (
            patch("backend.app.save_suggestion", side_effect=OSError("disk unavailable")),
            patch("backend.app.send_email", return_value=True) as send_email,
        ):
            response = client.post(
                "/api/suggestions",
                json={"title": "Mail-delivered Film"},
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["status"], "received")
        self.assertTrue(response.json["emailed"])
        self.assertFalse(response.json["saved"])
        send_email.assert_called_once()

    def test_tmdb_routes_report_upstream_rate_limit(self):
        class RateLimitedTMDBService:
            configured = True

            def search_movies(self, _query):
                raise TMDBServiceError("TMDB rate limit reached.", 429)

        client = create_app(self.recommender, tmdb_service=RateLimitedTMDBService()).test_client()
        response = client.get("/api/tmdb/search?q=Kantara")
        self.assertEqual(response.status_code, 429)
        self.assertIn("rate limit", response.json["error"].lower())


if __name__ == "__main__":
    unittest.main()

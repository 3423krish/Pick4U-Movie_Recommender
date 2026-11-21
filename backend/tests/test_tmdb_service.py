import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from backend.tmdb_service import (
    TMDBService,
    TMDBServiceError,
    normalize_tmdb_id,
    tmdb_image_url,
)


class TMDBServiceTests(unittest.TestCase):
    def response(self, payload):
        return BytesIO(json.dumps(payload).encode("utf-8"))

    def test_normalizes_float_ids_and_rejects_invalid_ids(self):
        self.assertEqual(normalize_tmdb_id(19995.0), "19995")
        self.assertEqual(normalize_tmdb_id("19995.0"), "19995")
        self.assertIsNone(normalize_tmdb_id("tt1187043"))
        self.assertIsNone(normalize_tmdb_id(float("nan")))
        self.assertIsNone(normalize_tmdb_id(True))

    def test_image_urls_use_official_host_and_requested_size(self):
        self.assertEqual(
            tmdb_image_url("/abc123.jpg", "w500"),
            "https://image.tmdb.org/t/p/w500/abc123.jpg",
        )
        self.assertIsNone(tmdb_image_url("//example.com/poster.jpg", "w500"))
        self.assertIsNone(tmdb_image_url("/poster.jpg", "w999"))

    def test_tmdb_id_uses_bearer_auth_and_caches_metadata(self):
        service = TMDBService(token="test-token")
        payload = {"poster_path": "/poster.jpg", "backdrop_path": "/backdrop.jpg"}
        with patch("backend.tmdb_service.urlopen", return_value=self.response(payload)) as fetch:
            result = service.get_movie_artwork(19995.0)
            cached = service.get_movie_artwork("19995.0")

        request = fetch.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.themoviedb.org/3/movie/19995")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["poster_url"], "https://image.tmdb.org/t/p/w500/poster.jpg")
        self.assertEqual(result["backdrop_url"], "https://image.tmdb.org/t/p/w1280/backdrop.jpg")
        self.assertEqual(cached, result)

    def test_artwork_and_movie_details_cache_for_24_hours(self):
        service = TMDBService(token="test-token")
        clock = [1000.0]
        artwork_response = {"poster_path": "/poster.jpg"}
        details_response = {"title": "Sample Movie"}
        with (
            patch("backend.tmdb_service.time.monotonic", side_effect=lambda: clock[0]),
            patch(
                "backend.tmdb_service.urlopen",
                side_effect=[
                    self.response(artwork_response),
                    self.response(details_response),
                    self.response(artwork_response),
                    self.response(details_response),
                ],
            ) as fetch,
        ):
            service.get_movie_artwork(123)
            service.get_movie_for_suggestion(123)
            clock[0] += 24 * 60 * 60 - 1
            service.get_movie_artwork(123)
            service.get_movie_for_suggestion(123)
            self.assertEqual(fetch.call_count, 2)

            clock[0] += 2
            service.get_movie_artwork(123)
            service.get_movie_for_suggestion(123)
            self.assertEqual(fetch.call_count, 4)

    def test_missing_tmdb_id_resolves_exact_imdb_id_without_title_search(self):
        service = TMDBService(token="test-token")
        responses = [
            self.response({
                "movie_results": [{
                    "id": 20453,
                    "title": "3 Idiots",
                    "release_date": "2009-12-23",
                    "poster_path": "/three-idiots.jpg",
                    "backdrop_path": "/three-idiots-backdrop.jpg",
                }]
            }),
        ]
        with patch("backend.tmdb_service.urlopen", side_effect=responses) as fetch:
            result = service.get_movie_artwork(None, "tt1187043")
            cached = service.get_movie_artwork(None, "tt1187043")

        find_request = fetch.call_args_list[0].args[0]
        self.assertIn("/find/tt1187043?", find_request.full_url)
        self.assertIn("external_source=imdb_id", find_request.full_url)
        self.assertEqual(fetch.call_count, 1)
        self.assertNotIn("/search/", find_request.full_url)
        self.assertEqual(cached, result)
        self.assertEqual(result["poster_url"], "https://image.tmdb.org/t/p/w500/three-idiots.jpg")
        self.assertEqual(
            result["backdrop_url"],
            "https://image.tmdb.org/t/p/w1280/three-idiots-backdrop.jpg",
        )

    def test_imdb_lookup_falls_back_to_movie_details_when_find_has_no_artwork(self):
        service = TMDBService(token="test-token")
        responses = [
            self.response({"movie_results": [{"id": 20453, "poster_path": None}]}),
            self.response({"poster_path": "/three-idiots.jpg", "backdrop_path": None}),
        ]
        with patch("backend.tmdb_service.urlopen", side_effect=responses) as fetch:
            result = service.get_movie_artwork(None, "tt1187043")

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(
            fetch.call_args_list[1].args[0].full_url,
            "https://api.themoviedb.org/3/movie/20453",
        )
        self.assertEqual(result["poster_url"], "https://image.tmdb.org/t/p/w500/three-idiots.jpg")

    def test_temporary_url_error_retries_and_succeeds_without_logging_token(self):
        service = TMDBService(token="do-not-log-this-token")
        payload = {"poster_path": "/poster.jpg", "backdrop_path": None}
        with (
            self.assertLogs("backend.tmdb_service", level="WARNING") as captured,
            patch("backend.tmdb_service.urlopen", side_effect=[
                URLError("temporary network issue"),
                self.response(payload),
            ]) as fetch,
            patch("backend.tmdb_service.time.sleep"),
        ):
            artwork = service.get_movie_artwork(19995)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(artwork["poster_url"], "https://image.tmdb.org/t/p/w500/poster.jpg")
        messages = "\n".join(captured.output)
        self.assertIn("/movie/19995", messages)
        self.assertIn("URL error", messages)
        self.assertNotIn("do-not-log-this-token", messages)

    def test_timeout_and_invalid_json_are_retried_separately(self):
        service = TMDBService(token="test-token")
        payload = {"poster_path": "/poster.jpg", "backdrop_path": None}
        with (
            patch("backend.tmdb_service.urlopen", side_effect=[
                TimeoutError("request timed out"),
                self.response({"movie_results": []}),
                BytesIO(b"not-json"),
                self.response(payload),
            ]) as fetch,
            patch("backend.tmdb_service.time.sleep"),
        ):
            timeout_payload, _ = service._request_json("https://api.themoviedb.org/3/find/tt4161520?external_source=imdb_id")
            artwork = service.get_movie_artwork(19995)

        self.assertEqual(timeout_payload, {"movie_results": []})
        self.assertEqual(artwork["poster_url"], "https://image.tmdb.org/t/p/w500/poster.jpg")
        self.assertEqual(fetch.call_count, 4)

    def test_retryable_http_error_retries_without_global_backoff(self):
        service = TMDBService(token="test-token")
        error = HTTPError("https://api.themoviedb.org/3/movie/19995", 503, "unavailable", {}, None)
        payload = {"poster_path": "/poster.jpg", "backdrop_path": None}
        with (
            patch("backend.tmdb_service.urlopen", side_effect=[error, self.response(payload)]) as fetch,
            patch("backend.tmdb_service.time.sleep"),
        ):
            artwork = service.get_movie_artwork(19995)

        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(service._backoff_until, 0)
        self.assertEqual(artwork["poster_url"], "https://image.tmdb.org/t/p/w500/poster.jpg")

    def test_one_movie_network_failure_does_not_block_another_movie(self):
        service = TMDBService(token="test-token")
        service.MAX_RETRIES = 0
        payload = {"poster_path": "/other-movie.jpg", "backdrop_path": None}
        with patch(
            "backend.tmdb_service.urlopen",
            side_effect=[URLError("temporary network issue"), self.response(payload)],
        ) as fetch:
            failed = service.get_movie_artwork(111)
            succeeded = service.get_movie_artwork(222)

        self.assertIsNone(failed["poster_url"])
        self.assertEqual(
            succeeded["poster_url"],
            "https://image.tmdb.org/t/p/w500/other-movie.jpg",
        )
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(service._backoff_until, 0)

    def test_failure_cache_expires_and_allows_a_fresh_lookup(self):
        service = TMDBService(token="test-token")
        service.MAX_RETRIES = 0
        service.FAILURE_CACHE_TTL_SECONDS = 5
        clock = [100.0]
        payload = {"poster_path": "/poster.jpg", "backdrop_path": None}
        with (
            patch("backend.tmdb_service.time.monotonic", side_effect=lambda: clock[0]),
            patch(
                "backend.tmdb_service.urlopen",
                side_effect=[URLError("temporary network issue"), self.response(payload)],
            ) as fetch,
        ):
            failed = service.get_movie_artwork(19995)
            cached_failure = service.get_movie_artwork(19995)
            self.assertEqual(fetch.call_count, 1)

            clock[0] += service.FAILURE_CACHE_TTL_SECONDS + 1
            recovered = service.get_movie_artwork(19995)

        self.assertIsNone(failed["poster_url"])
        self.assertEqual(cached_failure, failed)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(
            recovered["poster_url"],
            "https://image.tmdb.org/t/p/w500/poster.jpg",
        )

    def test_missing_id_and_api_failure_return_empty_artwork(self):
        service = TMDBService(token="test-token")
        with patch("backend.tmdb_service.urlopen") as fetch:
            missing = service.get_movie_artwork()
            self.assertIsNone(missing["poster_url"])
            self.assertIsNone(missing["backdrop_url"])
            self.assertEqual(fetch.call_count, 0)

        with (
            patch("backend.tmdb_service.urlopen", side_effect=URLError("offline")),
            patch("backend.tmdb_service.time.sleep"),
        ):
            result = service.get_movie_artwork(12345)
        self.assertIsNone(result["poster_url"])
        self.assertIsNone(result["backdrop_url"])

    def test_batch_deduplicates_movie_ids(self):
        service = TMDBService(token="test-token")
        response = self.response({"poster_path": "/poster.jpg", "backdrop_path": None})
        movies = [
            {"tmdb_id": 19995.0, "imdb_id": "tt0499549"},
            {"tmdb_id": "19995.0", "imdb_id": "tt0499549"},
        ]
        with patch("backend.tmdb_service.urlopen", return_value=response) as fetch:
            results = service.get_movie_artworks(movies)

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(results[0], results[1])

    def test_suggestion_search_caches_and_validates_results(self):
        service = TMDBService(token="test-token")
        payload = {
            "results": [
                {
                    "id": 123,
                    "title": "Kantara",
                    "release_date": "2022-09-30",
                    "overview": "A story.",
                    "original_language": "kn",
                    "poster_path": "/kantara.jpg",
                }
            ]
        }
        with patch("backend.tmdb_service.urlopen", return_value=self.response(payload)) as fetch:
            results = service.search_movies("Kantara")
            cached = service.search_movies("Kantara")

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(results, cached)
        self.assertEqual(results[0]["tmdb_id"], 123)
        self.assertEqual(results[0]["year"], 2022)
        self.assertEqual(results[0]["poster_url"], "https://image.tmdb.org/t/p/w342/kantara.jpg")

    def test_suggestion_search_surfaces_rate_limit_and_invalid_response(self):
        service = TMDBService(token="test-token")
        with patch(
            "backend.tmdb_service.urlopen",
            side_effect=HTTPError("https://api.themoviedb.org/3/search/movie", 429, "rate limited", {}, None),
        ) as fetch:
            with self.assertRaises(TMDBServiceError) as raised:
                service.search_movies("Kantara")
            self.assertEqual(raised.exception.status_code, 429)
            with self.assertRaises(TMDBServiceError) as backed_off:
                service.search_movies("Kantara")
            self.assertEqual(backed_off.exception.status_code, 429)
            self.assertEqual(fetch.call_count, 1)

        invalid_service = TMDBService(token="test-token")
        with patch(
            "backend.tmdb_service.urlopen",
            return_value=self.response({"results": {}}),
        ):
            with self.assertRaises(TMDBServiceError) as invalid:
                invalid_service.search_movies("Kantara")
        self.assertEqual(invalid.exception.status_code, 502)

    def test_suggestion_details_extracts_only_supported_metadata_and_caches(self):
        service = TMDBService(token="test-token")
        payload = {
            "id": 123,
            "imdb_id": "tt9999999",
            "title": "Kantara",
            "original_title": "Kantara",
            "release_date": "2022-09-30",
            "runtime": 148,
            "genres": [{"name": "Drama"}],
            "spoken_languages": [{"english_name": "Kannada", "iso_639_1": "kn"}],
            "original_language": "kn",
            "overview": "A forest story.",
            "tagline": "A tagline",
            "keywords": {"keywords": [{"name": "forest"}]},
            "credits": {
                "crew": [{"job": "Director", "name": "Director One"}],
                "cast": [{"name": "Actor One"}],
            },
            "vote_average": 8.0,
            "vote_count": 1000,
            "poster_path": "/kantara.jpg",
        }
        with patch("backend.tmdb_service.urlopen", return_value=self.response(payload)) as fetch:
            details = service.get_movie_for_suggestion(123)
            cached = service.get_movie_for_suggestion(123)

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(details, cached)
        self.assertEqual(details["languages"], ["Kannada"])
        self.assertEqual(details["directors"], ["Director One"])
        self.assertEqual(details["cast"], ["Actor One"])
        self.assertEqual(details["poster_url"], "https://image.tmdb.org/t/p/w342/kantara.jpg")


if __name__ == "__main__":
    unittest.main()

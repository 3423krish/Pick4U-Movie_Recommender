# Picks4U

Picks4U is a movie discovery and recommendation application. The React
single-page frontend searches a local movie catalogue, shows movie profiles,
and lets a user generate recommendations with selectable content, language,
quality, and diversity preferences. A Flask API loads the Python
recommendation engine once at startup and serves both the frontend and optional
TMDB lookups.

The recommendation catalogue and ranking are local. TMDB is an optional,
server-side integration for catalogue artwork and movie suggestions; it does
not supply or reorder recommendations.

## Features

- Search the real model-ready catalogue and select a movie profile.
- View available catalogue details and TMDB poster/backdrop artwork.
- Generate similar-movie lists with selectable result count, language mode,
  recommendation preset, diversity, and quality weight.
- Select multiple target languages and optionally balance results among them.
- Read the recommender's `Why` explanation when returned.
- Suggest a missing movie, optionally fill its details from TMDB, and record
  the request locally.
- Add approved TMDB movies to a separate, small catalogue file without
  modifying the source dataset.
- Use the application without TMDB credentials; missing artwork falls back to
  the existing branded placeholder.
- Use a responsive dark, forest-and-gold interface with keyboard-accessible
  search suggestions and an accessible suggestion dialog.

There are no user accounts, authentication, watchlists, database server, or
separate JavaScript backend.

## Visual identity

The website uses a premium cinematic forest-green and antique-gold palette.
These are frontend CSS tokens, documented here as a reference rather than
applied as a custom GitHub README background. GitHub controls this page's
background, typeface, and light/dark rendering. The README uses standard
Markdown and restrained accents so it remains readable in either theme. The
website's display headings use Georgia/Times serif fonts.

| UI role | Color |
|---|---|
| Main background | `#071A14` |
| Section background | `#0B241B` |
| Card surface | `#102D22` |
| Elevated surface | `#17392B` |
| Hover surface | `#214633` |
| Antique gold | `#C2A66A` |
| Champagne gold | `#D9C99F` |
| Muted gold | `#9F8653` |
| Pale gold | `#E7D9B5` |
| Primary text | `#E9E5D9` |
| Body text | `#C4CEC5` |
| Secondary text | `#A4B1A5` |
| Sage accent | `#829889` |

## Screenshots

No screenshots are currently included. Capture these views from the running
application and place the real images in a new `docs/screenshots/` directory.
The paths below are proposed destinations, not existing assets; this README
does not embed fabricated images.

| View to capture | Save the screenshot as |
|---|---|
| Homepage and hero | `docs/screenshots/homepage.png` |
| Movie search/results | `docs/screenshots/movie-search-results.png` |
| Movie details and recommendations | `docs/screenshots/movie-details-recommendations.png` |
| Suggest Movie dialog | `docs/screenshots/suggest-movie-dialog.png` |

## Technology

The frontend lockfile resolves React and React DOM to 19.3.1 and Vite to
8.3.8. The package manifest declares compatible version ranges. Backend
dependency ranges and the versions installed in the verified Python 3.10.0
environment are:

| Area | Declared requirements | Verified version |
|---|---|---|
| Frontend | React/React DOM `^19.3.1`, Vite `^8.3.6`, `@vitejs/plugin-react` `^6.1.2`, Oxlint `^1.90.0` | React/React DOM 19.3.1; Vite 8.3.8; plugin-react 6.3.0; Oxlint 1.94.0 |
| Backend/API | Python 3.10+, Flask `>=3.0,<4.0` | Python 3.10.0; Flask 3.1.3 |
| Data and recommendation | NumPy `>=2.2,<3.0`; pandas `>=2.3,<3.0`; SciPy `>=1.15,<2.0`; scikit-learn `>=1.7,<2.0` | NumPy 2.2.6; pandas 2.3.3; SciPy 1.15.3; scikit-learn 1.7.2 |
| Configuration | python-dotenv `>=1.0,<2.0` | python-dotenv 1.2.4 |
| TMDB | Optional server-side API v4 Read Access Token | Not required for local catalogue recommendations |

The verified Node.js version was 24.14.0. Vite 8 requires Node.js 20.19+ or
22.12+.

Dependency manifests are [backend/requirements.txt](./backend/requirements.txt)
and [frontend/package.json](./frontend/package.json). The frontend lockfile is
[frontend/package-lock.json](./frontend/package-lock.json).

## How it works

1. Flask reads the model-ready CSV or gzip CSV at startup, prepares its
   catalogue and feature matrices, and constructs one recommender.
2. The frontend calls relative `/api` paths. In development, Vite proxies them
   to `http://127.0.0.1:5000`.
3. The recommender uses TF-IDF content features and its existing scoring,
   language, quality, and optional Maximal Marginal Relevance (MMR)
   diversification behavior. Existing single-movie recommendation behavior
   remains the default; optional multi-language selection and balancing are
   additional request options.
4. Flask optionally looks up artwork for only the movies needed for the
   current search, detail, or recommendation response. TMDB credentials remain
   on the backend, and returned artwork URLs are not used to compute
   recommendations.

## Recommendation engine

The catalogue is represented with six TF-IDF content blocks. The engine
computes cosine similarity within each block and combines available
similarities using feature weights; missing candidate features are accounted
for when the weighted score is normalized.

| Block | Catalogue content |
|---|---|
| Genres | Recommender genre tokens |
| Keywords | Movie keywords |
| Story | Overview and tagline text, using word and two-word features |
| Cast | Cast tokens |
| Director | Director tokens |
| Title | Cleaned title tokens |

Year is a separate similarity signal, not a TF-IDF block. Its contribution
decreases with the distance between release years.

The `preset` changes the relative feature weights. Each row gives the weights
in this order: genres, keywords, story, cast, director, title, year.

| Preset | Weight vector | Emphasis |
|---|---|---|
| `balanced` | `3, 2, 1.5, 1.5, 1, 0.5, 0.75` | Default combination |
| `genre_first` | `6, 1.5, 1, 1, 0.5, 0.5, 0.75` | Genres |
| `story_first` | `2, 3.5, 3, 0.75, 0.5, 0.5, 0.5` | Keywords and story |
| `cast_crew_first` | `2, 1, 1, 3, 2.5, 0.5, 0.5` | Cast and director |

Language modes affect target-language candidates as follows:

| Mode | Behavior |
|---|---|
| `ignore` | No language bonus or strict filter; explicitly supplied targets can still be used for balancing |
| `balanced` | Adds a 0.15 score bonus for target-language matches |
| `prefer` | Adds a 0.6 score bonus for target-language matches |
| `strict` | Hard-filters candidates outside the target language set |

When no target is supplied, non-`ignore` modes use the selected movie's primary
language. The optional `languages` list can target up to five catalogue
languages. When `language_balance` is enabled for multiple targets, the engine
allocates result quotas across them and interleaves those results. If a target
cannot fill its quota, remaining slots are filled from the broader ranked
pool.

The `quality_weight` multiplies a source-normalized, vote-weighted rating
percentile and adds it to the recommendation score. Its API range is 0–1 and
its default is 0.1. Optional MMR diversification first gathers additional
candidates, then balances relevance against redundancy with previously
selected movies (default lambda 0.7). The MMR diversity representation uses
genre, keyword, story, and cast features.

The engine also supports cold-start preference recommendations internally;
the current Flask `/api/recommend` endpoint requires a catalogue `movie_id`.

## Recommendation options

`POST /api/recommend` accepts the following relevant fields:

| Field | Accepted values and defaults |
|---|---|
| `movie_id` | Required exact ID returned by catalogue search |
| `n` | Integer 1–50; default 10 (the UI offers 5, 10, or 20) |
| `language` | Optional single known language name |
| `language_mode` | `ignore`, `balanced`, `prefer`, or `strict`; default `balanced` |
| `languages` | Optional list of up to 5 known language names |
| `language_balance` | Boolean; default `false`; requires at least 2 selected languages |
| `preset` | `balanced`, `genre_first`, `story_first`, or `cast_crew_first`; omitted means default balanced weights |
| `diversify` | Boolean; default `false`; enables/disables MMR |
| `quality_weight` | Finite number from 0 to 1; default 0.1 |

The frontend does not invent a similarity percentage. The backend may return a
`Score` value and a `Why` explanation; the score is not a percentage.

## Project layout

```text
Movie-Recommendation-System/
├── .gitignore
├── backend/
│   ├── __init__.py
│   ├── app.py                 # Flask routes and input validation
│   ├── model_loader.py        # Catalogue loading and startup initialization
│   ├── recommender.py         # Recommendation features and ranking
│   ├── suggestions.py         # Suggestion validation, storage, notifications
│   ├── tmdb_service.py        # Artwork and TMDB movie lookup
│   ├── requirements.txt
│   └── tests/
│       ├── test_new_features.py
│       ├── test_recommender.py
│       ├── test_suggestions.py
│       └── test_tmdb_service.py
├── frontend/
│   ├── .gitignore
│   ├── .oxlintrc.json
│   ├── public/                # Static icons
│   ├── src/
│   │   ├── components/        # Hero, movie cards/details, controls, suggestion UI
│   │   ├── hooks/useDebounce.js
│   │   ├── services/api.js    # Centralized Flask API client
│   │   ├── App.jsx
│   │   ├── App.css
│   │   ├── index.css
│   │   └── main.jsx
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   └── vite.config.js         # Development /api proxy
├── movie_project/
│   ├── README.md
│   └── data/
│       ├── excluded/          # Excluded source rows
│       ├── final/             # Model-ready and intermediate catalogue files
│       ├── lookup/            # Lookup tables and compressed IMDb data
│       ├── user_added/        # Optional approved additions, created when used
│       └── suggestions/       # Local suggestion log; ignored by Git
├── original_data/             # Source CSVs; ignored by Git
├── scripts/
│   ├── __init__.py
│   ├── add_movie.py           # Add approved TMDB movies separately
│   └── make_slim_dataset.py   # Create compact CSV or gzip catalogue
├── Movie_Recommendation_System_Final_v2.ipynb
└── README.md
```

The active runtime uses `backend/` and `frontend/`. The notebook is an offline
data-preparation artifact; Flask does not execute it at startup. The frontend
manifest and lockfile are both under `frontend/`.

## Model-ready catalogue

### Runtime catalogue

Flask needs one of the model-ready CSV catalogues below when it starts. It
does not run the notebook or create the catalogue itself.

The source model-ready file is:

```text
movie_project/data/final/movies_model_ready.csv
```

It contains 50,403 rows and 68 columns (43,363,372 bytes; 43.36 MB or
41.35 MiB in the current workspace). The application selects 26 columns from
it. The generated compact catalogue is:

```text
movie_project/data/final/movies_model_ready.csv.gz
```

It contains 50,403 rows and the 26 application columns (4,952,679 bytes;
4.95 MB or 4.72 MiB in the current workspace). When no `MOVIE_DATA_PATH` is
set, the loader prefers the gzip file if present; otherwise it uses the
original CSV. Both formats remain supported.

The loader's 26 retained columns are:

| Group | Columns |
|---|---|
| Identity | `movie_id`, `source_primary`, `tmdb_id`, `imdb_id`, `title`, `original_title` |
| Display and release | `year`, `release_date`, `runtime`, `genres` |
| Recommendation content | `genres_recommender`, `keywords`, `overview`, `tagline`, `director`, `directors`, `directors_recommender`, `cast_top10`, `cast_recommender`, `languages_available`, `primary_language` |
| Quality and artwork | `rating`, `votes`, `poster_path` |
| Eligibility | `recsys_query_ok`, `recsys_candidate_default` |

The source CSV and gzip catalogue were compared after arranging the source
columns in loader order. All 26 retained columns match in value across all
50,403 rows.

### Create the compact catalogue

To generate or regenerate the compact file from the original CSV:

```powershell
.\.venv\Scripts\python.exe -m scripts.make_slim_dataset
```

If the output already exists, pass `--force` to replace it. The script writes
the gzip file beside the source by default, checks the CSV round-trip, and
never overwrites the source. It can also write an uncompressed compact CSV with
`--format csv`. `scripts.make_slim_dataset` only compresses an existing
`movies_model_ready.csv`; it does not rebuild that file from the original
sources.

The root `.gitignore` explicitly allows the compact gzip catalogue;
the uncompressed CSV and intermediate files under `movie_project/data/final/`
remain ignored. Whether to publish the catalogue is a repository and
data-rights decision. If it is not included in the repository, obtain an
authorized `movies_model_ready.csv.gz` or
`movies_model_ready.csv` from the project owner or an approved project/data
backup, then place it at the path above. There is no automatic dataset download.

### Reproducing preprocessing from source datasets

The notebook
[Movie_Recommendation_System_Final_v2.ipynb](./Movie_Recommendation_System_Final_v2.ipynb)
is an offline preprocessing artifact. Its input is
`movie_project/data/final/movies_unified_enriched_v4.csv`; it writes the
model-ready CSV. The current ignore rules exclude that input from normal Git
publication, so provide it separately if you want to reproduce preprocessing
from a clean clone. The notebook does not run when Flask starts, and cannot
rebuild that input without any earlier source tables required to create it.

The lookup directory currently contains four large compressed IMDb tables.
`name.basics.tsv.gz`, `title.basics.tsv.gz`, and `title.principals.tsv.gz`
exceed GitHub's 100 MiB regular-file limit; `title.crew.tsv.gz` is large but
below that limit. These files are ignored and are not needed to run the Flask
application. If they are needed to reproduce notebook preprocessing, prefer
documented retrieval from the original provider or authorized external dataset
hosting. Git LFS is an option only if versioning these files is necessary and
its storage and download quotas are acceptable. Confirm redistribution terms
before publishing any source dataset.

The loader requires the columns defined in
[backend/recommender.py](./backend/recommender.py). Do not rename or remove
those fields without updating and testing the loader and recommender.

## Requirements

- Python 3.10 or newer.
- Node.js supported by Vite 8 (Node.js 20.19+ or 22.12+).
- npm.
- The model-ready catalogue at the path above, as CSV or gzip CSV.
- A TMDB v4 API Read Access Token only for live TMDB lookups and artwork.

Check installed versions:

```powershell
python --version
node --version
npm --version
```

## Clone and configure

After committing the project, substitute your repository URL:

```powershell
git clone <your-repository-url> Movie-Recommendation-System
Set-Location Movie-Recommendation-System
```

Replace `<your-repository-url>` with the actual GitHub clone URL. The
destination argument keeps the following `Set-Location` command consistent
even if the GitHub repository has a different name.

If the catalogue was not committed, copy it to
`movie_project\data\final\movies_model_ready.csv.gz` or
`movie_project\data\final\movies_model_ready.csv`.

The root `.gitignore` excludes `.env`, virtual environments, `node_modules`,
Python/test caches, generated frontend output, local source/intermediate data
directories, and suggestion records. It explicitly allows only the compact
gzip catalogue from `movie_project/data/final/`. Create a root `.env` file
locally and add only the settings you need; never commit `.env`:

```powershell
notepad .env
```

### Optional TMDB artwork and lookups

Set the TMDB v4 Read Access Token in `.env` if you want live TMDB artwork and
suggestion autofill. Replace the placeholder with your own token; leave the
setting empty if you do not need TMDB:

```env
TMDB_READ_ACCESS_TOKEN=YOUR_FULL_TMDB_V4_READ_ACCESS_TOKEN
```

Use the TMDB **API Read Access Token (v4)**, not the v3 API key. Do not include
the `Bearer ` prefix; the backend adds it. Restart Flask after changing the
token. The frontend never receives the credential.

When a catalogue TMDB ID is missing, artwork lookup can use an exact IMDb ID
with TMDB's find endpoint; it does not guess by title. Failures or absent
artwork leave the app usable and preserve the branded placeholder.

Other supported optional root `.env` settings include:

- `MOVIE_DATA_PATH`: catalogue path; relative paths are rooted at the project.
- `MOVIE_ADDED_PATH`: approved additional-movie CSV path.
- `SUGGESTIONS_LOG`: private local JSON Lines suggestion log path.
- `SUGGESTION_DEFAULT_TO`: fallback recipient for suggestion notifications.
- `SUGGESTION_TO`: optional per-deployment recipient override; takes
  precedence over `SUGGESTION_DEFAULT_TO`.
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`:
  optional email transport configuration.

Suggestion email is optional. To send notifications, set
`SUGGESTION_DEFAULT_TO`, add the relevant settings to `.env`, and
configure SMTP. Without a valid recipient and SMTP host, suggestions are still
saved locally but no email is sent. `SUGGESTION_TO` is an optional recipient
override; `SUGGESTION_DEFAULT_TO` is used when it is empty. Keep the suggestion
log under `movie_project/data/suggestions/` (ignored by Git), since records may
include contact details.

## Run on Windows

Open PowerShell at the repository root.

### 1. Create the backend environment

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### 2. Start Flask

In the first terminal, from the repository root:

```powershell
.\.venv\Scripts\python.exe -m backend.app
```

Flask loads the catalogue and initializes the recommender at startup. Wait for
startup to finish. Check health at
`http://127.0.0.1:5000/api/health`; a healthy response includes `status`,
`catalogue_count`, and `language_count`.

### 3. Start the frontend

In a second terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open the local URL printed by Vite, normally `http://127.0.0.1:5173`. Keep both
servers running. Vite forwards `/api` requests to Flask.

## Build, lint, and test

From the repository root, run all backend tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -v
```

Run frontend checks from `frontend/`:

```powershell
npm ci
npm run lint
npm run build
```

The production build is written to `frontend/dist/`. Flask is not configured
to serve that directory; deploy the built frontend as static files and route
`/api` requests to Flask through your hosting server or reverse proxy.

## Flask API

All routes are served by Flask at `http://127.0.0.1:5000` in local development.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Backend, catalogue, and language health |
| `GET` | `/api/languages` | Catalogue language names and counts |
| `GET` | `/api/movies/search?q=<title>&limit=<n>` | Search the real local catalogue |
| `GET` | `/api/movie/<movie_id>` | Get a selected movie's catalogue profile |
| `POST` | `/api/recommend` | Generate recommendations for an exact catalogue movie ID |
| `GET` | `/api/tmdb/search?q=<title>` | Search TMDB for a user-submitted movie |
| `GET` | `/api/tmdb/movie/<int:tmdb_id>` | Fetch TMDB fields used to autofill a suggestion |
| `POST` | `/api/suggestions` | Validate and store a movie suggestion |

### Search and movie IDs

Example:

```http
GET /api/movies/search?q=Avatar&limit=20
```

Search requires a non-empty query of at most 100 characters; `limit` defaults
to 20 and must be between 1 and 50. Use the returned `movie_id` for details
and recommendations. It may look like `tmdb:19995` or `imdb:tt...`; do not
substitute the separate `tmdb_id`.

Search returns `{"count": ..., "results": [...]}`. Each result includes
`movie_id`, `title`, `year`, `genres`, `languages`, `primary_language`,
`rating`, `overview`, `poster_path`, `tmdb_id`, and `poster_url`.

`GET /api/movie/<movie_id>` returns the movie profile, including
`original_title`, `release_date`, `runtime`, `tagline`, `votes`, `director`,
`directors`, `cast`, `backdrop_path`, `backdrop_url`, and `source` in addition
to the search fields. Unavailable catalogue values may be null or empty.
Artwork URL fields are populated when supported artwork is available; missing
images remain null and the frontend keeps its existing placeholder.

### Recommendations

Example request (replace the ID with a real catalogue result):

```json
{
  "movie_id": "MOVIE_ID_FROM_SEARCH",
  "n": 10,
  "language_mode": "balanced",
  "languages": ["Hindi", "Tamil"],
  "language_balance": true,
  "diversify": true,
  "quality_weight": 0.1,
  "preset": "balanced"
}
```

The response contains a `count` and a `recommendations` array with the
recommender's movie fields (for example `Movie_ID`, `Title`, `Year`, `Genres`,
`Language`, `Rating`, `Score`, and `Why`) plus `poster_url` when available.
`Score` is not a similarity percentage. The API does not promise a
recommendation overview.

The request must be a JSON object. The `movie_id` must exist in the local
catalogue; the API does not look up or create recommendation candidates from
TMDB.

### Common validation responses

Errors are JSON objects with an `error` message. Important status codes and
conditions include:

| Status | Example condition |
|---|---|
| `400` | Missing/overlong search query; invalid `limit`; malformed recommendation JSON; invalid option values, unknown languages, `language_balance` with fewer than two selected languages, or non-positive TMDB ID |
| `404` | Unknown catalogue `movie_id`; missing TMDB movie |
| `413` | Request body exceeds 64 KB |
| `429` | Process-local limit exceeded: 5 suggestion submissions per hour or 60 TMDB lookups per hour per client key |
| `503` | TMDB movie-detail lookup requested while TMDB is not configured |

`GET /api/tmdb/search?q=<title>` returns `{"available": false, "results": []}`
when no TMDB token is configured. Otherwise it returns `available: true` and
the TMDB results. TMDB does not generate or rank local recommendations.

### Suggestions

Suggestion requests require a title; other movie details and contact email
are optional. The endpoint validates and deduplicates submissions, applies a
process-local limit of five requests per hour and stores records as JSON Lines
by default under the ignored `movie_project/data/suggestions/` directory.
The JSON body accepts `title`, `year`, `tmdb_id`, `languages`, `genres`,
`director`, `cast`, `overview`, `note`, `contact_email`, and `autofilled`.
The title is required and limited to 200 characters; year must be from 1880
through three years beyond the current year; `tmdb_id` must be positive; and a
supplied contact address must be valid and no longer than 254 characters.
`director`, `overview`, and `note` are limited to 120, 1,500, and 1,000
characters respectively. Each `languages`, `genres`, or `cast` list can have
up to 10 text items, each no longer than 60 characters; these fields also
accept comma-separated text. `autofilled` must be a boolean and defaults to
`false`.

Minimal valid request:

```json
{
  "title": "A title supplied by the user"
}
```

New suggestions return HTTP `201` with `{"status": "received", "emailed": ...}`.
Already-known TMDB movies and duplicate submissions return a status of
`exists` or `duplicate`; they are not saved again. Suggestions are saved
locally even when optional SMTP notification is unavailable or fails.

TMDB search and detail lookups are limited to 60 requests per hour per
process-local client key. These in-memory limits are not shared across
multiple server processes.

To add approved movies from TMDB, configure a token and run from the project
root:

```powershell
.\.venv\Scripts\python.exe -m scripts.add_movie --tmdb-id 123456
```

To import all pending suggestion records that include TMDB IDs:

```powershell
.\.venv\Scripts\python.exe -m scripts.add_movie --from-suggestions
```

The script writes to `movie_project/data/user_added/movies_added.csv` by
default, deduplicates against the existing catalogue, and does not edit the
model-ready source. Restart Flask to rebuild the in-memory model and include
new additions. The default `user_added/` directory is ignored by Git; only
include approved additions in a public repository if you intend to distribute
them and have confirmed the applicable data rights.

## Troubleshooting

### Catalogue not found

Confirm that
`movie_project\data\final\movies_model_ready.csv.gz` or
`movie_project\data\final\movies_model_ready.csv` exists, or set
`MOVIE_DATA_PATH` in the root `.env`. The gzip catalogue is preferred by
default when present.

### Frontend API requests fail

- Ensure Flask is running at `http://127.0.0.1:5000`.
- Check the Flask terminal for startup errors.
- Start Vite from the `frontend/` directory with `npm run dev`.
- Check both terminals for API or proxy errors.

### TMDB returns an error or artwork is missing

- Confirm `.env` is in the repository root and the variable name is
  `TMDB_READ_ACCESS_TOKEN`.
- Use the v4 API Read Access Token without a `Bearer ` prefix.
- Restart Flask after editing `.env`.
- Some movies have no usable TMDB/IMDb identifier or no TMDB artwork. The app
  remains usable and displays its branded placeholder.

## Known limitations

- Search is limited to the local model-ready catalogue; TMDB is used for
  optional artwork and suggestion autofill, not as the recommendation source.
- Artwork and suggestion autofill depend on a valid server-side TMDB token,
  network access, and TMDB availability.
- Suggestions are stored in a local JSON Lines file by default. Email
  notifications require working SMTP settings; a failed email does not remove
  a saved suggestion.
- Suggestion and TMDB lookup rate limits are held in process memory, so they
  are not shared across multiple Flask workers and reset when the process
  restarts.
- The Flask development server binds to localhost and is not a production
  deployment configuration. Production hosting needs a suitable WSGI server,
  static frontend hosting, and `/api` routing.
- The notebook and source/intermediate data are not required at runtime, but
  reproducing all preprocessing may require the ignored source and lookup
  datasets.

## Future improvements

- Document a reproducible, rights-compliant way to obtain source and lookup
  datasets without storing oversized files in normal Git history.
- Add continuous integration for backend tests and frontend lint/build checks.
- Use shared persistent storage for rate limits and suggestions if the
  application is deployed with multiple workers.
- Add deployment-specific configuration and operational monitoring after a
  hosting target is selected.

## Data and attribution

Keep credentials out of source control. The project keeps the recommendation
catalogue local and does not introduce another backend framework or database.

Movie artwork and TMDB lookup data are provided by
[The Movie Database (TMDB)](https://www.themoviedb.org/). This product uses
the TMDB API but is not endorsed or certified by TMDB.

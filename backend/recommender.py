import difflib
import re

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.preprocessing import normalize


def split_pipe(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if pd.isna(value) or not str(value).strip():
        return []
    return [x.strip() for x in str(value).split("|") if x.strip()]


GENRE_SYNONYMS = {
    "sci-fi": "Science Fiction", "scifi": "Science Fiction", "sci fi": "Science Fiction",
    "science fiction": "Science Fiction", "musical": "Music", "romcom": "Romance",
    "film-noir": "Film Noir", "film noir": "Film Noir", "tv movie": "TV Movie",
}


def canon_genre(g):
    """One canonical casing for genre labels from both sources."""
    key = re.sub(r"\s+", " ", str(g).strip().lower())
    return GENRE_SYNONYMS.get(key, key.title())


def norm_token(value):
    if pd.isna(value):
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def parse_bool(value):
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


REQUIRED_CATALOGUE_COLUMNS = [
    "movie_id", "source_primary", "imdb_id", "title", "year",
    "genres", "genres_recommender", "keywords", "overview", "tagline",
    "director", "directors", "directors_recommender", "cast_top10",
    "cast_recommender", "languages_available", "primary_language",
    "rating", "votes", "runtime", "recsys_query_ok",
    "recsys_candidate_default",
]


def prepare_catalogue(movies_raw):
    """Apply the v2 notebook's catalogue preprocessing without notebook state."""
    missing_columns = [
        column for column in REQUIRED_CATALOGUE_COLUMNS
        if column not in movies_raw.columns
    ]
    if missing_columns:
        raise ValueError(f"Required columns missing from catalogue: {missing_columns}")
    if movies_raw["movie_id"].duplicated().any():
        raise ValueError("Duplicate movie_id values found. Resolve duplicates before modelling.")

    movies = movies_raw.copy()
    movies["source"] = movies["source_primary"].map({
        "tmdb": "TMDB",
        "imdb_indian_csv": "Indian",
    }).fillna(movies["source_primary"].astype(str))
    movies["genres"] = movies["genres_recommender"].apply(
        lambda value: sorted({canon_genre(genre) for genre in split_pipe(value)})
    )
    movies["keywords"] = movies["keywords"].apply(split_pipe)
    movies["cast_display"] = movies["cast_recommender"].apply(split_pipe)
    movies["directors_list"] = movies["directors_recommender"].apply(split_pipe)
    movies["languages"] = movies["languages_available"].apply(split_pipe)

    for column in ["year", "rating", "votes", "runtime"]:
        movies[column] = pd.to_numeric(movies[column], errors="coerce")

    movies["text"] = (
        movies["overview"].fillna("").astype(str) + " " +
        movies["tagline"].fillna("").astype(str)
    ).str.strip()
    movies["keyword_text"] = movies["keywords"].apply(lambda values: " ".join(values))
    movies["cast_tok"] = movies["cast_display"].apply(
        lambda names: [norm_token(name) for name in names if norm_token(name)]
    )
    movies["director_tok"] = movies["directors_list"].apply(
        lambda names: [norm_token(name) for name in names if norm_token(name)]
    )
    movies["title_clean"] = (
        movies["title"].fillna("").astype(str)
        .str.lower()
        .str.replace(r"[^a-z0-9\s]", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    def title_tokens(title):
        tokens = title.split()
        kept = [word for word in tokens if word not in ENGLISH_STOP_WORDS]
        return kept or tokens

    movies["title_tok"] = movies["title_clean"].apply(title_tokens)

    min_votes_prior = 50
    movies["quality"] = 0.0
    for source, group in movies.groupby("source"):
        valid_votes = group.loc[group["votes"] > 0, "votes"]
        mean_rating = group["rating"].mean()
        prior_weight = max(valid_votes.quantile(0.60), min_votes_prior) if len(valid_votes) else float(min_votes_prior)
        ratings = group["rating"].fillna(mean_rating if pd.notna(mean_rating) else 0.0)
        votes = group["votes"].fillna(0.0)
        denominator = votes + prior_weight
        weighted_rating = np.where(
            denominator > 0,
            (votes / np.where(denominator > 0, denominator, 1)) * ratings +
            (prior_weight / np.where(denominator > 0, denominator, 1)) *
            (mean_rating if pd.notna(mean_rating) else 0.0),
            ratings,
        )
        movies.loc[group.index, "quality"] = pd.Series(
            weighted_rating, index=group.index
        ).rank(pct=True).fillna(0.0)

    movies["query_ok"] = movies["recsys_query_ok"].apply(parse_bool)
    movies["eligible"] = movies["recsys_candidate_default"].apply(parse_bool)
    invalid_title = movies["title"].fillna("").str.strip().str.casefold().eq("404: error not found")
    movies.loc[invalid_title, "eligible"] = False
    movies["uid"] = np.arange(len(movies))
    return movies


def build_feature_matrices(movies):
    """Fit the v2 notebook's six TF-IDF blocks once for this catalogue."""
    def identity_analyzer(tokens):
        return tokens

    vectorizers = {
        "genres": TfidfVectorizer(analyzer=identity_analyzer),
        "keywords": TfidfVectorizer(stop_words="english", min_df=2, sublinear_tf=True),
        "text": TfidfVectorizer(
            stop_words="english", ngram_range=(1, 2), min_df=2,
            max_features=40000, sublinear_tf=True,
        ),
        "cast": TfidfVectorizer(analyzer=identity_analyzer),
        "director": TfidfVectorizer(analyzer=identity_analyzer),
        "title": TfidfVectorizer(analyzer=identity_analyzer),
    }
    feature_inputs = {
        "genres": movies["genres"].tolist(),
        "keywords": movies["keyword_text"].tolist(),
        "text": movies["text"].tolist(),
        "cast": movies["cast_tok"].tolist(),
        "director": movies["director_tok"].tolist(),
        "title": movies["title_tok"].tolist(),
    }
    matrices = {
        block: vectorizers[block].fit_transform(feature_inputs[block])
        .tocsr().astype(np.float32)
        for block in vectorizers
    }
    return vectorizers, matrices


DEFAULT_WEIGHTS = {"genres": 3.0, "keywords": 2.0, "text": 1.5, "cast": 1.5, "director": 1.0, "title": 0.5, "year": 0.75}
# "What matters most to you?"  -> ready-made weight sets (usable as  weights=PRESETS["story_first"])
PRESETS = {
    "balanced":        DEFAULT_WEIGHTS,
    "genre_first":     {"genres": 6.0, "keywords": 1.5, "text": 1.0, "cast": 1.0, "director": 0.5, "title": 0.5, "year": 0.75},
    "story_first":     {"genres": 2.0, "keywords": 3.5, "text": 3.0, "cast": 0.75, "director": 0.5, "title": 0.5, "year": 0.5},
    "cast_crew_first": {"genres": 2.0, "keywords": 1.0, "text": 1.0, "cast": 3.0, "director": 2.5, "title": 0.5, "year": 0.5},
}
LANGUAGE_MODES  = {"ignore": 0.0, "balanced": 0.15, "prefer": 0.6, "strict": 0.0}   # strict = hard filter on top


class MovieRecommender:
    def __init__(self, movies, X, vecs, weights=DEFAULT_WEIGHTS, year_scale=12.0, missing_penalty=0.5):
        self.m, self.X, self.vecs, self.weights, self.tau = movies.reset_index(drop=True), X, vecs, dict(weights), year_scale
        self.missing_penalty = missing_penalty
        self.N        = len(self.m)
        self.year     = self.m.year.to_numpy(float)
        self.quality  = self.m.quality.to_numpy(float)
        self.eligible = self.m.eligible.to_numpy(bool)
        # Track which movies have usable data in each feature block
        self.block_available = {
            b: np.asarray(X[b].getnnz(axis=1) > 0)
            for b in X
        }

        # Year is available only when it is not missing
        self.block_available["year"] = np.isfinite(self.year)
        self.keys = self.m.movie_id.to_numpy()
        self.id_to_index = {movie_id: index for index, movie_id in enumerate(self.keys)}
        self.titles_lc = self.m.title.fillna("").str.lower().to_numpy()

        # multi-hot language matrix  (a film dubbed in 3 languages matches all 3)
        langs = sorted({l for ls in self.m.languages for l in ls})
        self.lang_idx = {l: i for i, l in enumerate(langs)}
        language_pairs = [(i, self.lang_idx[l]) for i, ls in enumerate(self.m.languages) for l in ls]
        if language_pairs:
            r, c = zip(*language_pairs)
            self.L = sparse.csc_matrix(
                (np.ones(len(r), dtype=bool), (r, c)),
                shape=(self.N, len(langs))
            )
        else:
            self.L = sparse.csc_matrix((self.N, len(langs)), dtype=bool)
        self._lm = {}

        # binary "has this token" matrices, used for preference queries ("I want Sci-Fi AND Leonardo DiCaprio")
        self.B = {b: (X[b] > 0).astype(np.float32).tocsr() for b in ["genres", "cast", "director", "keywords"]}

        # space used for the diversity (MMR) step
        self.Xdiv = normalize(sparse.hstack([X["genres"], X["keywords"], X["text"], X["cast"]]).tocsr())

        # people lookup (display name by normalised token)
        self.people = {}
        for cast, director_list in zip(
            self.m.cast_display,
            self.m.directors_list
        ):

            for p in cast + director_list:
                token = norm_token(p)
                if token:
                    self.people[token] = p

    # ---------------------------------------------------------------- helpers
    def languages(self):
        return sorted(self.lang_idx)

    def lang_mask(self, language):
        language = str(language).strip()
        language_lookup = {name.casefold(): name for name in self.lang_idx}
        language = language_lookup.get(language.casefold(), language)
        if language not in self.lang_idx:
            raise KeyError(f"Unknown language '{language}'. Available: {', '.join(self.languages())}")
        if language not in self._lm:
            self._lm[language] = self.L[:, self.lang_idx[language]].toarray().ravel()
        return self._lm[language]

    @staticmethod
    def _as_language_list(languages):
        if languages is None:
            return []
        if isinstance(languages, str):
            return [languages.strip()] if languages.strip() else []
        return [language.strip() for language in languages if isinstance(language, str) and language.strip()]

    def lang_mask_any(self, languages):
        mask = np.zeros(self.N, dtype=bool)
        for language in self._as_language_list(languages):
            mask |= self.lang_mask(language)
        return mask

    def find_movie(self, title, year=None, language=None):
        t = title.lower().strip()
        mask = self.titles_lc == t
        if year is not None:     mask &= (self.year == year)
        if language is not None: mask &= self.lang_mask(language)
        cand = np.flatnonzero(mask)
        if len(cand) == 0:
            close = difflib.get_close_matches(t, set(self.titles_lc), n=5, cutoff=0.7)
            sugg = [self.m.title[np.flatnonzero(self.titles_lc == c)[0]] for c in close]
            raise KeyError(f"'{title}' not found. Did you mean: {sugg}")
        if len(cand) > 1:
            cand = cand[np.argsort(-self.m.votes.to_numpy()[cand])]
            others = [
                f"{self.m.title.iloc[j]} "
                f"({int(self.year[j]) if not np.isnan(self.year[j]) else '?'}, "
                f"{self.m.primary_language.iloc[j]})"
                for j in cand[1:4]
            ]
            print(f"ℹ︎ {len(cand)} movies titled '{title}' – using the most-voted one. Others: {others}. Use year= / language= to choose.")
        return int(cand[0])

    def find_person(self, fragment, limit=8):
        f = norm_token(fragment)
        return [self.people[t] for t in self.people if f in t][:limit]

    # ---------------------------------------------------------------- similarity
    def block_sims(self, q, q_year=None, coverage=None):
        # cosine per block. For preference queries `coverage` = {block: alpha} blends in "share of requested tokens present":
        # a movie with Sci-Fi + Action + Thriller still fully satisfies a request for "Sci-Fi" (plain cosine would punish the extras).
        coverage, sims = coverage or {}, {}
        for b, qb in q.items():
            if qb is None or qb.nnz == 0: continue
            s = (self.X[b] @ qb.T).toarray().ravel()
            if b in coverage:
                qbin = (qb > 0).astype(np.float32)
                cov = (self.B[b] @ qbin.T).toarray().ravel() / qbin.sum()
                s = coverage[b] * cov + (1 - coverage[b]) * s
            sims[b] = s
        if q_year is not None and not np.isnan(q_year):
            sims["year"] = np.nan_to_num(np.exp(-np.abs(self.year - q_year) / self.tau))
        return sims

    def query_sims(self, i):
        return self.block_sims({b: self.X[b][i] for b in self.X}, self.year[i])


    def combine(self, sims, weights=None):
        w = weights or self.weights

        num = np.zeros(self.N, dtype=float)
        den = np.zeros(self.N, dtype=float)

        for b, s in sims.items():
            weight = w.get(b, 0)

            if weight <= 0:
                continue

            available = self.block_available[b]

            num += weight * np.nan_to_num(s, nan=0.0)
            # A block the query uses but the candidate lacks still counts
            # missing_penalty * weight, so sparse films cannot win on 2-3 blocks.
            den += weight * (available + self.missing_penalty * (~available))

        return np.divide(
            num,
            den,
            out=np.zeros(self.N, dtype=float),
            where=den > 0
        )


    # ---------------------------------------------------------------- ranking
    def select(self, score, exclude_key=None, n=10, mask=None):
        s = score.astype(float).copy()

        s[~self.eligible] = -np.inf

        if mask is not None:
            s[~mask] = -np.inf

        k = min(n * 8 + 50, self.N)

        if k == 0:
            return np.array([], dtype=int)

        order = np.argpartition(-s, k - 1)[:k]
        order = order[np.argsort(-s[order])]

        out = []
        seen = {exclude_key}

        for j in order:
            if not np.isfinite(s[j]):
                break

            if self.keys[j] in seen:
                continue

            seen.add(self.keys[j])
            out.append(j)

            if len(out) == n:
                break

        return np.array(out, dtype=int)

    def _balanced_by_language(self, score, exclude_key, n, mask, targets, diversify, lam):
        quotas = [n // len(targets) + (index < n % len(targets)) for index in range(len(targets))]
        pools = []
        for language, quota in zip(targets, quotas):
            language_mask = mask & self.lang_mask(language)
            pool = self.select(
                score,
                exclude_key,
                quota * 4 if diversify else quota,
                language_mask,
            )
            if diversify and len(pool) > quota:
                pool = self._mmr(pool, score, quota, lam)
            pools.append(pool.tolist())

        chosen = []
        for position in range(max(quotas, default=0)):
            for pool in pools:
                if position < len(pool) and pool[position] not in chosen:
                    chosen.append(pool[position])
        if len(chosen) < n:
            for index in self.select(score, exclude_key, n + len(chosen), mask):
                if index not in chosen:
                    chosen.append(int(index))
                if len(chosen) == n:
                    break
        return np.asarray(chosen[:n], dtype=int)

    def _mmr(self, cand, score, n, lam):
        M = self.Xdiv[cand]; S = (M @ M.T).toarray()
        sel, rem = [], list(range(len(cand)))
        while rem and len(sel) < n:
            best = max(rem, key=lambda r: lam * score[cand[r]] - (1 - lam) * (max(S[r][s] for s in sel) if sel else 0))
            sel.append(best); rem.remove(best)
        return cand[sel]

    def rank(self, sims, qi=None, n=10, weights=None, lang_target=None,
         lang_bonus=0.15, strict=False, quality_weight=0.1,
         diversify=False, mmr_lambda=0.7, extra_mask=None, lang_balance=False):

        score = self.combine(sims, weights)

        # Exclude movies with zero content similarity
        mask = score > 0

        if extra_mask is not None:
            mask &= extra_mask

        targets = self._as_language_list(lang_target)
        if targets:
            lm = self.lang_mask_any(targets)
            score = score + lang_bonus * lm

            if strict:
                mask &= lm

        if quality_weight:
            score = score + quality_weight * self.quality

        excl = self.keys[qi] if qi is not None else None

        if lang_balance and len(targets) > 1:
            idx = self._balanced_by_language(
                score, excl, n, mask, targets, diversify, mmr_lambda
            )
            return idx, score[idx]

        idx = self.select(score, excl, n * 4 if diversify else n, mask)

        if diversify and len(idx) > n:
            idx = self._mmr(idx, score, n, mmr_lambda)

        return idx, score[idx]

    # ---------------------------------------------------------------- explanations & display
    def _why_movie(self, qi, j):
        a, b, r = self.m.iloc[qi], self.m.iloc[j], []
        sg = [g for g in a.genres if g in b.genres]
        if sg: r.append("genre: " + "/".join(sg))
        shared_languages = set(a.languages) & set(b.languages)
        if shared_languages: r.append("language: " + ", ".join(sorted(shared_languages)[:2]))
        shared_directors = (
            set(a.directors_list) & set(b.directors_list)
        )

        if shared_directors:
            r.append(
                "director: " + ", ".join(sorted(shared_directors))
            )
        sc = [c for c in a.cast_display if c in b.cast_display]
        if sc: r.append("cast: " + ", ".join(sc[:2]))
        sk = [k for k in a.keywords if k in b.keywords]
        if sk: r.append("themes: " + ", ".join(sk[:3]))
        if not np.isnan(a.year) and not np.isnan(b.year) and abs(a.year - b.year) <= 3: r.append("same era")
        return "; ".join(r)

    def _present(self, idx, scores, why):
        m = self.m.iloc[idx]

        out = pd.DataFrame({
            "Movie_ID": m.movie_id.values,
            "Title": m.title.values,
            "Year": m.year.astype("Int64").values,
            "Language": m.languages.apply(", ".join).values,
            "Genres": m.genres.apply(", ".join).values,
            "Director": m.directors_list.apply(
                lambda names: ", ".join(names)
            ).values,
            "Rating": m.rating.round(1).values,
            "Votes": m.votes.astype("Int64").values,
            "Score": np.round(scores, 3),
            "Why": [why(j) for j in idx]
        })

        out.index = range(1, len(out) + 1)
        return out

    # ---------------------------------------------------------------- public API
    def recommend(self, title, n=10, year=None, language=None, language_mode="balanced", quality_weight=0.1,
                  diversify=False, weights=None, source_language=None, verbose=True):
        # title: query movie.  language: target language of the results (default: language of the query movie).
        qi = self.find_movie(title, year, source_language)
        return self._recommend_from_index(
            qi, n, language, language_mode, quality_weight, diversify, weights, verbose
        )

    def recommend_by_movie_id(self, movie_id, n=10, language=None, language_mode="balanced",
                              quality_weight=0.1, diversify=False, weights=None, verbose=True,
                              languages=None, lang_balance=False):
        """Recommend from an exact catalogue ID, avoiding ambiguous title lookups."""
        try:
            qi = self.id_to_index[movie_id]
        except KeyError:
            raise KeyError(f"Movie ID '{movie_id}' not found.") from None
        return self._recommend_from_index(
            qi, n, language, language_mode, quality_weight, diversify, weights, verbose,
            languages=languages, lang_balance=lang_balance,
        )

    def _recommend_from_index(self, qi, n, language, language_mode, quality_weight,
                              diversify, weights, verbose, languages=None, lang_balance=False):
        if isinstance(language_mode, str):
            bonus, strict = LANGUAGE_MODES[language_mode], language_mode == "strict"
        else:
            bonus, strict = float(language_mode), False
        use_lang = language_mode != "ignore"
        default_language = self.m.primary_language.iloc[qi]
        if pd.isna(default_language) or not default_language:
            available_languages = self.m.languages.iloc[qi]
            default_language = (
                available_languages[0] if available_languages else None
            )

        chosen_languages = self._as_language_list(languages)
        target = (
            chosen_languages
            if chosen_languages
            else (language or default_language) if use_lang else None
        )
        q = self.m.iloc[qi]
        if verbose:
            print(f"Because you picked: {q.title} ({'' if np.isnan(q.year) else int(q.year)}) · {', '.join(q.languages)} · {', '.join(q.genres)}"
                  f"   |  language_mode={language_mode}" + (f", target={target}" if target else ""))
        idx, sc = self.rank(
            self.query_sims(qi), qi, n, weights, target, bonus, strict,
            quality_weight, diversify, lang_balance=lang_balance,
        )
        return self._present(idx, sc, lambda j: self._why_movie(qi, j))

    def recommend_by_preferences(self, genres=None, language=None, actors=None, director=None, keywords=None,
                                 plot=None, year=None, n=10, language_mode="prefer", quality_weight=0.1,
                                 diversify=False, weights=None):
        # cold-start: no movie needed, describe what you want
        q, notes = {}, []
        if genres:
            gs = [canon_genre(g) for g in genres]
            bad = [g for g in gs if g not in self.vecs["genres"].vocabulary_]
            if bad: notes.append(f"unknown genre(s) ignored: {bad}. Available: {sorted(self.vecs['genres'].vocabulary_)}")
            q["genres"] = self.vecs["genres"].transform([[g for g in gs if g not in bad]])
        if actors:
            toks = [norm_token(a) for a in actors]
            bad = [a for a, t in zip(actors, toks) if t not in self.vecs["cast"].vocabulary_]
            if bad: notes.append(f"actor(s) not in data: {bad} (try .find_person('name'))")
            q["cast"] = self.vecs["cast"].transform([[t for t in toks if t in self.vecs["cast"].vocabulary_]])
        if director:
            t = norm_token(director)
            if t in self.vecs["director"].vocabulary_: q["director"] = self.vecs["director"].transform([[t]])
            else: notes.append(f"director not in data: {director} (try .find_person('name'))")
        if keywords: q["keywords"] = self.vecs["keywords"].transform([" ".join(keywords)])
        if plot:     q["text"]     = self.vecs["text"].transform([plot.lower()])
        for nt in notes: print("⚠", nt)

        if isinstance(language_mode, str):
            bonus, strict = LANGUAGE_MODES[language_mode], language_mode == "strict"
        else:
            bonus, strict = float(language_mode), False
        target = language if (language and language_mode != "ignore") else None
        sims = self.block_sims(q, year, coverage={"genres": 0.7, "keywords": 0.7, "cast": 1.0, "director": 1.0})
        idx, sc = self.rank(sims, None, n, weights, target, bonus, strict, quality_weight, diversify)

        want_g, want_a = set(gs) if genres else set(), {norm_token(a) for a in actors or []}
        def why(j):
            r, mj = [], self.m.iloc[j]
            sg = [g for g in mj.genres if g in want_g]
            if sg: r.append("genre: " + "/".join(sg))
            if language and language.title() in mj.languages: r.append(f"language: {language.title()}")
            sa = [a for a, t in zip(mj.cast_display, mj.cast_tok) if t in want_a]
            if sa: r.append("cast: " + ", ".join(sa))
            if director and norm_token(director) in mj.director_tok: r.append(f"director: {mj.director}")
            if not r and plot: r.append("plot / theme similarity")
            return "; ".join(r)
        return self._present(idx, sc, why)

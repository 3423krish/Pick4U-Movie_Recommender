import { useEffect, useRef, useState } from 'react'
import './App.css'
import Hero from './components/Hero.jsx'
import MovieDetails from './components/MovieDetails.jsx'
import MovieGrid from './components/MovieGrid.jsx'
import Navbar from './components/Navbar.jsx'
import RecommendationControls from './components/RecommendationControls.jsx'
import SuggestionModal from './components/SuggestionModal.jsx'
import { getMovieDetails, getRecommendations, searchMovies } from './services/api.js'
import { useDebounce } from './hooks/useDebounce.js'

function StatusMessage({ kind = 'empty', title, children, onRetry, actionLabel, onAction }) {
  return (
    <div className={`status-message status-message--${kind}`} role={kind === 'error' ? 'alert' : 'status'}>
      {kind === 'loading' && <span className="loader" aria-hidden="true" />}
      <div>
        <strong>{title}</strong>
        {children && <p>{children}</p>}
        {onRetry && <button className="text-button" type="button" onClick={onRetry}>Try again</button>}
        {onAction && <button className="text-button" type="button" onClick={onAction}>{actionLabel}</button>}
      </div>
    </div>
  )
}

function App() {
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebounce(query, 350)
  const [searchResult, setSearchResult] = useState({
    query: '',
    attempt: -1,
    movies: [],
    status: 'idle',
    error: '',
  })
  const [searchAttempt, setSearchAttempt] = useState(0)
  const [selectedId, setSelectedId] = useState('')
  const [detailsResult, setDetailsResult] = useState({
    movieId: '',
    attempt: -1,
    movie: null,
    status: 'idle',
    error: '',
  })
  const [detailsAttempt, setDetailsAttempt] = useState(0)
  const [recommendations, setRecommendations] = useState([])
  const [recommendationState, setRecommendationState] = useState({ status: 'idle', error: '' })
  const [suggestionOpen, setSuggestionOpen] = useState(false)
  const [suggestionTitle, setSuggestionTitle] = useState('')
  const [options, setOptions] = useState({
    n: 10,
    language_mode: 'balanced',
    preset: 'balanced',
    diversify: true,
    quality_weight: 0.1,
    languages: [],
    language_balance: true,
  })
  const suggestionReturnFocusRef = useRef(null)
  const searchInputRef = useRef(null)
  const homeSearchInputRef = useRef(null)
  const detailsRef = useRef(null)
  const [selectionVersion, setSelectionVersion] = useState(0)
  const selectionVersionRef = useRef(0)
  const pendingDetailsScrollRef = useRef(0)
  const normalizedQuery = query.trim()
  const normalizedDebouncedQuery = debouncedQuery.trim()
  const isDebouncing = normalizedQuery.length > 0 && normalizedQuery !== normalizedDebouncedQuery
  const isCurrentSearch = searchResult.query === normalizedDebouncedQuery && searchResult.attempt === searchAttempt
  const searchStatus = !normalizedQuery
    ? 'idle'
    : isDebouncing || !isCurrentSearch
      ? 'loading'
      : searchResult.status
  const isCurrentDetails = detailsResult.movieId === selectedId && detailsResult.attempt === detailsAttempt
  const detailsStatus = !selectedId
    ? 'idle'
    : isCurrentDetails
      ? detailsResult.status
      : 'loading'
  const movie = isCurrentDetails ? detailsResult.movie : null

  useEffect(() => {
    if (!normalizedDebouncedQuery) return undefined

    const controller = new AbortController()

    searchMovies(normalizedDebouncedQuery, 20, controller.signal)
      .then((results) => {
        setSearchResult({
          query: normalizedDebouncedQuery,
          attempt: searchAttempt,
          movies: results,
          status: 'success',
          error: '',
        })
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setSearchResult({
            query: normalizedDebouncedQuery,
            attempt: searchAttempt,
            movies: [],
            status: 'error',
            error: error.message,
          })
        }
      })

    return () => controller.abort()
  }, [normalizedDebouncedQuery, searchAttempt])

  useEffect(() => {
    if (!selectedId) return undefined

    const controller = new AbortController()

    getMovieDetails(selectedId, controller.signal)
      .then((details) => {
        setDetailsResult({
          movieId: selectedId,
          attempt: detailsAttempt,
          movie: details,
          status: 'success',
          error: '',
        })
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setDetailsResult({
            movieId: selectedId,
            attempt: detailsAttempt,
            movie: null,
            status: 'error',
            error: error.message,
          })
        }
      })

    return () => controller.abort()
  }, [selectedId, detailsAttempt])

  useEffect(() => {
    const pendingVersion = pendingDetailsScrollRef.current
    if (
      detailsStatus !== 'success'
      || !pendingVersion
      || pendingVersion !== selectionVersion
    ) return

    pendingDetailsScrollRef.current = 0
    detailsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [detailsStatus, selectionVersion])

  function handleSelectMovie(movieId) {
    if (!movieId) return
    const nextVersion = selectionVersionRef.current + 1
    selectionVersionRef.current = nextVersion
    pendingDetailsScrollRef.current = nextVersion
    setSelectionVersion(nextVersion)
    setSelectedId(movieId)
    setRecommendations([])
    setRecommendationState({ status: 'idle', error: '' })
  }

  function handleSearchQueryChange(value) {
    pendingDetailsScrollRef.current = 0
    setQuery(value)
  }

  function openSuggestion(title = '') {
    suggestionReturnFocusRef.current = document.activeElement
    setSuggestionTitle(title)
    setSuggestionOpen(true)
  }

  async function handleRecommend() {
    if (!movie?.movie_id) return
    setRecommendationState({ status: 'loading', error: '' })
    try {
      const { languages, language_balance: balanceLanguages, ...recommendationOptions } = options
      const results = await getRecommendations(movie.movie_id, {
        ...recommendationOptions,
        ...(languages.length ? { languages } : {}),
        language_balance: languages.length > 1 && balanceLanguages,
      })
      setRecommendations(results)
      setRecommendationState({ status: 'success', error: '' })
    } catch (error) {
      setRecommendations([])
      setRecommendationState({ status: 'error', error: error.message })
    }
  }

  function focusHomeSearch() {
    homeSearchInputRef.current?.focus()
  }

  return (
    <div className="app-shell" id="home">
      <Navbar
        query={query}
        onQueryChange={handleSearchQueryChange}
        inputRef={searchInputRef}
        suggestions={isCurrentSearch ? searchResult.movies : []}
        searchStatus={searchStatus}
        onSelectMovie={handleSelectMovie}
        onSuggest={openSuggestion}
      />
      <main>
        <Hero onExplore={focusHomeSearch} />

        <section className="content-section discover-section" id="discover">
          <div className="section-heading">
            <div>
              <span className="eyebrow">OUR NEXT FAVORITE FILM</span>
              <h2>Find your kind of movie</h2>
              <p>Search the catalogue by title and choose a film to explore.</p>
            </div>
            {normalizedQuery && (
              <span className="result-count">
                {searchStatus === 'success' ? `${searchResult.movies.length} ${searchResult.movies.length === 1 ? 'title' : 'titles'}` : 'Searching'}
              </span>
            )}
          </div>

          <form className="home-search" role="search" onSubmit={(event) => event.preventDefault()}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <circle cx="10.8" cy="10.8" r="6.8" />
              <path d="m16 16 4.5 4.5" />
            </svg>
            <input
              ref={homeSearchInputRef}
              type="search"
              aria-label="Search the catalogue by movie title"
              placeholder="Search the catalogue by title…"
              autoComplete="off"
              value={query}
              onChange={(event) => handleSearchQueryChange(event.target.value)}
            />
          </form>

          {!normalizedQuery && (
            <StatusMessage kind="empty" title="Start with a movie title">
              Search the catalogue to see real movies and build a recommendation from your pick.
            </StatusMessage>
          )}
          {normalizedQuery && searchStatus === 'loading' && (
            <StatusMessage kind="loading" title="Searching the catalogue">
              Looking for “{normalizedQuery}”…
            </StatusMessage>
          )}
          {normalizedQuery && searchStatus === 'error' && (
            <StatusMessage kind="error" title="Search could not be completed" onRetry={() => setSearchAttempt((attempt) => attempt + 1)}>
              {searchResult.error}
            </StatusMessage>
          )}
          {normalizedQuery && searchStatus === 'success' && searchResult.movies.length === 0 && (
            <StatusMessage
              kind="empty"
              title={`No movies found for “${normalizedQuery}”`}
              actionLabel="Can’t find it? Suggest this movie"
              onAction={() => openSuggestion(normalizedQuery)}
            >
              Try a different title or check the spelling.
            </StatusMessage>
          )}
          {normalizedQuery && searchStatus === 'success' && searchResult.movies.length > 0 && (
            <MovieGrid movies={searchResult.movies} onSelect={handleSelectMovie} />
          )}
        </section>

        {selectedId && (
          <section className="content-section details-section" id="movie-details" ref={detailsRef}>
            {detailsStatus === 'loading' && (
              <StatusMessage kind="loading" title="Loading movie details">Gathering information from the catalogue…</StatusMessage>
            )}
            {detailsStatus === 'error' && (
              <StatusMessage kind="error" title="Movie details could not be loaded" onRetry={() => setDetailsAttempt((attempt) => attempt + 1)}>
                {detailsResult.error}
              </StatusMessage>
            )}
            {detailsStatus === 'success' && movie && (
              <>
                <MovieDetails movie={movie} />
                <div className="recommendation-workspace">
                  <div className="section-heading recommendation-heading">
                    <div>
                      <span className="eyebrow">MADE FOR YOUR TASTE</span>
                      <h2>Find similar movies</h2>
                      <p>Fine-tune what matters, then let Picks4U find your next watch.</p>
                    </div>
                  </div>
                  <RecommendationControls
                    options={options}
                    onChange={setOptions}
                    onSubmit={handleRecommend}
                    isLoading={recommendationState.status === 'loading'}
                  />
                  {recommendationState.status === 'loading' && (
                    <StatusMessage kind="loading" title="Finding your next favorite">
                      Comparing themes, genres, language, and more…
                    </StatusMessage>
                  )}
                  {recommendationState.status === 'error' && (
                    <StatusMessage kind="error" title="Recommendations could not be generated" onRetry={handleRecommend}>
                      {recommendationState.error}
                    </StatusMessage>
                  )}
                  {recommendationState.status === 'success' && recommendations.length === 0 && (
                    <StatusMessage kind="empty" title="No similar movies found">
                      Try a different language mode or another movie.
                    </StatusMessage>
                  )}
                  {recommendations.length > 0 && (
                    <div className="recommendation-results">
                      <div className="results-subheading">
                        <h3>Picked for you</h3>
                        <span>{recommendations.length} recommendations</span>
                      </div>
                      <MovieGrid
                        movies={recommendations}
                        variant="recommendation"
                        onSelect={handleSelectMovie}
                      />
                    </div>
                  )}
                </div>
              </>
            )}
          </section>
        )}

        <section className="content-section about-section" id="about">
          <div className="about-copy">
            <span className="eyebrow">THOUGHTFUL BY DESIGN</span>
            <h2>Recommendations with a little more meaning.</h2>
            <p>
              Picks4U uses a content-based movie recommender. On the Python and
              Scikit-learn backend, TF-IDF feature extraction helps represent
              catalogue content; weighted movie similarity, your language
              preference, and optional MMR diversification shape each list.
              React brings those controls and discoveries together in one place.
            </p>
          </div>
          <div className="about-facts" aria-label="How Picks4U works">
            <div><span>01</span><strong>Content signals</strong><small>Genres, keywords, story, cast &amp; crew</small></div>
            <div><span>02</span><strong>Your preferences</strong><small>Language mode and recommendation style</small></div>
            <div><span>03</span><strong>More variety</strong><small>Optional MMR diversification</small></div>
          </div>
        </section>
      </main>
      <footer className="site-footer">
        <a className="brand brand--footer" href="#home"><span className="brand-mark" aria-hidden="true">P</span><span>Picks4U</span></a>
        <span>A better movie night starts with a good match.</span>
        <div className="tmdb-attribution">
          <a href="https://www.themoviedb.org/" target="_blank" rel="noreferrer" aria-label="TMDB website">
            <img
              src="https://www.themoviedb.org/assets/v4/logos/v2/blue_square_1-5bdc75aaebeb75dc7ae79426ddd9be3b2be1e342510f8202baf6bffa71d7f5c4.svg"
              alt="TMDB"
            />
          </a>
          <span>This product uses the TMDB API but is not endorsed or certified by TMDB.</span>
        </div>
        <a href="#home">Back to top ↑</a>
      </footer>
      {suggestionOpen && (
        <SuggestionModal
          initialTitle={suggestionTitle}
          returnFocusRef={suggestionReturnFocusRef}
          onClose={() => setSuggestionOpen(false)}
          onSelectMovie={(movieId) => {
            setSuggestionOpen(false)
            handleSelectMovie(movieId)
          }}
        />
      )}
    </div>
  )
}

export default App

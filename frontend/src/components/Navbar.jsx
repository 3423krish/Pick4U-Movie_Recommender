import { useEffect, useRef, useState } from 'react'
import MovieArtwork from './MovieArtwork.jsx'

function SearchIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="10.8" cy="10.8" r="6.8" />
      <path d="m16 16 4.5 4.5" />
    </svg>
  )
}

function Navbar({
  query,
  onQueryChange,
  inputRef,
  suggestions,
  searchStatus,
  onSelectMovie,
  onSuggest,
}) {
  const [focused, setFocused] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [dismissed, setDismissed] = useState(false)
  const wrapperRef = useRef(null)
  const queryText = query.trim()
  const visibleSuggestions = suggestions.slice(0, 6)
  const expanded = focused && !dismissed && queryText.length > 0
  const listId = 'movie-search-results'

  useEffect(() => {
    if (!focused) return undefined
    function closeOnOutsideClick(event) {
      if (!wrapperRef.current?.contains(event.target)) setFocused(false)
    }
    document.addEventListener('pointerdown', closeOnOutsideClick)
    return () => document.removeEventListener('pointerdown', closeOnOutsideClick)
  }, [focused])

  function choose(movie) {
    const movieId = movie.movie_id ?? movie.Movie_ID
    setFocused(false)
    setDismissed(true)
    setActiveIndex(-1)
    onSelectMovie(movieId)
    inputRef.current?.blur()
  }

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown' && visibleSuggestions.length) {
      event.preventDefault()
      setActiveIndex((index) => (index + 1) % visibleSuggestions.length)
    } else if (event.key === 'ArrowUp' && visibleSuggestions.length) {
      event.preventDefault()
      setActiveIndex((index) => (index <= 0 ? visibleSuggestions.length - 1 : index - 1))
    } else if (event.key === 'Enter' && activeIndex >= 0) {
      event.preventDefault()
      choose(visibleSuggestions[activeIndex])
    } else if (event.key === 'Escape' && expanded) {
      event.preventDefault()
      setDismissed(true)
      setActiveIndex(-1)
    }
  }

  function suggestTypedMovie() {
    setFocused(false)
    setDismissed(true)
    onSuggest(queryText)
  }

  return (
    <header className="site-header">
      <nav className="nav-wrap" aria-label="Main navigation">
        <a className="brand" href="#home" aria-label="Picks4U home">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span>Picks4U</span>
        </a>
        <div className="nav-search-wrap" ref={wrapperRef}>
          <form
            className="nav-search"
            role="search"
            onSubmit={(event) => {
              event.preventDefault()
              if (activeIndex >= 0 && visibleSuggestions[activeIndex]) {
                choose(visibleSuggestions[activeIndex])
              }
            }}
          >
            <SearchIcon />
            <input
              ref={inputRef}
              type="search"
              role="combobox"
              aria-label="Search movies"
              aria-autocomplete="list"
              aria-expanded={expanded}
              aria-controls={listId}
              aria-activedescendant={activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
              placeholder="Search movies"
              value={query}
              onFocus={() => setFocused(true)}
              onChange={(event) => {
                onQueryChange(event.target.value)
                setActiveIndex(-1)
                setDismissed(false)
              }}
              onKeyDown={handleKeyDown}
            />
          </form>
          {expanded && (
            <div className="search-panel" id={listId} role="listbox" aria-label="Movie search suggestions">
              {searchStatus === 'loading' && (
                <p className="search-panel__message" role="status">Searching the catalogue…</p>
              )}
              {searchStatus === 'error' && (
                <p className="search-panel__message search-panel__message--error" role="status">
                  Search suggestions are temporarily unavailable.
                </p>
              )}
              {searchStatus === 'success' && visibleSuggestions.map((movie, index) => {
                const movieId = movie.movie_id ?? movie.Movie_ID
                const title = movie.title ?? movie.Title
                const languages = movie.languages ?? movie.Language?.split(', ') ?? []
                const languageText = Array.isArray(languages) ? languages.join(' · ') : languages
                return (
                  <button
                    className="search-option"
                    id={`${listId}-${index}`}
                    key={movieId}
                    type="button"
                    role="option"
                    tabIndex={-1}
                    aria-selected={index === activeIndex}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => choose(movie)}
                  >
                    <span className="search-option__art"><MovieArtwork url={movie.poster_url} title={title} /></span>
                    <span className="search-option__copy">
                      <strong>{title}</strong>
                      <span>{movie.year || movie.Year || 'Year unknown'}{languageText ? ` · ${languageText}` : ''}</span>
                    </span>
                  </button>
                )
              })}
              {searchStatus === 'success' && visibleSuggestions.length === 0 && (
                <p className="search-panel__message">No matching titles in the catalogue.</p>
              )}
              {searchStatus === 'success' && visibleSuggestions.length > 0 && suggestions.length > 6 && (
                <p className="search-panel__message">More results are shown below.</p>
              )}
              <button
                className="search-panel__suggest"
                type="button"
                onMouseDown={(event) => event.preventDefault()}
                onClick={suggestTypedMovie}
              >
                Can’t find it? Suggest this movie
              </button>
            </div>
          )}
        </div>
        <button className="button button--outline nav-suggest" type="button" onClick={() => onSuggest('')}>
          Suggest a movie
        </button>
      </nav>
    </header>
  )
}

export default Navbar

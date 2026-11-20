import { useEffect, useRef, useState } from 'react'
import { useDebounce } from '../hooks/useDebounce.js'
import { submitSuggestion, tmdbMovie, tmdbSearch } from '../services/api.js'
import MovieArtwork from './MovieArtwork.jsx'

const MAX_MOVIE_YEAR = new Date().getFullYear() + 3

function splitList(value) {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

function SuggestionModal({ initialTitle, returnFocusRef, onClose, onSelectMovie }) {
  const [form, setForm] = useState({
    title: initialTitle,
    year: '',
    languages: '',
    genres: '',
    director: '',
    cast: '',
    overview: '',
    note: '',
    contact_email: '',
    website: '',
  })
  const [searchState, setSearchState] = useState({ query: '', status: 'idle', results: [], error: '' })
  const [detailsState, setDetailsState] = useState({ status: 'idle', error: '' })
  const [selectedTmdbId, setSelectedTmdbId] = useState(null)
  const [autofilled, setAutofilled] = useState(false)
  const [submitState, setSubmitState] = useState({ status: 'idle', error: '', result: null })
  const debouncedTitle = useDebounce(form.title, 500)
  const dialogRef = useRef(null)
  const titleRef = useRef(null)
  const detailsControllerRef = useRef(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => () => detailsControllerRef.current?.abort(), [])

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const query = debouncedTitle.trim()
    if (!query) return undefined
    tmdbSearch(query, controller.signal)
      .then((response) => {
        setSearchState({
          query,
          status: response.available ? 'success' : 'unavailable',
          results: response.results.slice(0, 8),
          error: '',
        })
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setSearchState({ query, status: 'error', results: [], error: error.message })
        }
      })
    return () => controller.abort()
  }, [debouncedTitle])

  useEffect(() => {
    titleRef.current?.focus()
    const dialog = dialogRef.current
    const returnFocusElement = returnFocusRef.current
    function trapFocus(event) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !dialog) return
      const focusable = [...dialog.querySelectorAll(
        'button:not(:disabled), input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
      )]
      if (!focusable.length) {
        event.preventDefault()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    dialog?.addEventListener('keydown', trapFocus)
    return () => {
      dialog?.removeEventListener('keydown', trapFocus)
      returnFocusElement?.focus()
    }
  }, [returnFocusRef])

  const currentSearch = Boolean(form.title.trim())
    && form.title.trim() === debouncedTitle.trim()
    && searchState.query === debouncedTitle.trim()
  const searchPending = Boolean(form.title.trim()) && !currentSearch
  const currentSearchResults = currentSearch ? searchState.results : []

  function updateField(key, value) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  async function selectTmdbMovie(result) {
    detailsControllerRef.current?.abort()
    const controller = new AbortController()
    detailsControllerRef.current = controller
    setSelectedTmdbId(result.tmdb_id)
    setAutofilled(true)
    setDetailsState({ status: 'loading', error: '' })
    try {
      const details = await tmdbMovie(result.tmdb_id, controller.signal)
      setForm((current) => ({
        ...current,
        title: details.title || result.title,
        year: details.year ? String(details.year) : '',
        languages: (details.languages || []).join(', '),
        genres: (details.genres || []).join(', '),
        director: (details.directors || []).join(', '),
        cast: (details.cast || []).join(', '),
        overview: details.overview || '',
      }))
      setDetailsState({ status: 'success', error: '' })
    } catch (error) {
      if (error.name !== 'AbortError') {
        setDetailsState({ status: 'error', error: error.message })
      }
    }
  }

  function switchToManualEntry() {
    detailsControllerRef.current?.abort()
    setSelectedTmdbId(null)
    setAutofilled(false)
    setDetailsState({ status: 'idle', error: '' })
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSubmitState({ status: 'loading', error: '', result: null })
    const payload = {
      title: form.title.trim(),
      year: form.year.trim() || null,
      tmdb_id: selectedTmdbId,
      languages: splitList(form.languages),
      genres: splitList(form.genres),
      director: form.director.trim(),
      cast: splitList(form.cast),
      overview: form.overview.trim(),
      note: form.note.trim(),
      contact_email: form.contact_email.trim(),
      autofilled,
      website: form.website,
    }
    try {
      const result = await submitSuggestion(payload)
      setSubmitState({ status: result.status, error: result.message || '', result })
    } catch (error) {
      setSubmitState({
        status: 'error',
        error: error.message,
        result: null,
        httpStatus: error.status,
      })
    }
  }

  const alreadyExists = submitState.status === 'exists'
  const duplicate = submitState.status === 'duplicate'
  const submitted = submitState.status === 'received'

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        className="suggestion-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="suggestion-title"
        ref={dialogRef}
      >
        <div className="suggestion-modal__heading">
          <div>
            <span className="eyebrow">HELP COMPLETE THE CATALOGUE</span>
            <h2 id="suggestion-title">Suggest a movie</h2>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close suggestion form">×</button>
        </div>

        {submitted && (
          <div className="suggestion-result suggestion-result--success" role="status">
            <strong>Thank you for the suggestion.</strong>
            <p>
              {submitState.result.emailed
                ? 'Your movie details were saved and an email notification was sent to the catalogue administrator.'
                : 'Your movie details were saved, but the email could not be sent. The Flask server may need SMTP configuration.'}
            </p>
            <button className="button button--primary" type="button" onClick={onClose}>Done</button>
          </div>
        )}
        {alreadyExists && (
          <div className="suggestion-result" role="status">
            <strong>This movie is already in the catalogue.</strong>
            <p>You can open its existing Picks4U profile.</p>
            <button
              className="button button--primary"
              type="button"
              onClick={() => onSelectMovie(submitState.result.movie_id)}
            >
              Open movie
            </button>
          </div>
        )}
        {duplicate && (
          <div className="suggestion-result" role="status">
            <strong>A similar suggestion was already received.</strong>
            <p>{submitState.error}</p>
            <button className="button button--primary" type="button" onClick={onClose}>Done</button>
          </div>
        )}

        {!submitted && !alreadyExists && !duplicate && (
          <form className="suggestion-form" onSubmit={handleSubmit}>
            <label className="form-field">
              <span>Movie title <b aria-hidden="true">*</b></span>
              <input
                ref={titleRef}
                type="text"
                required
                maxLength={200}
                value={form.title}
                onChange={(event) => {
                  detailsControllerRef.current?.abort()
                  updateField('title', event.target.value)
                  setSelectedTmdbId(null)
                  setAutofilled(false)
                  setDetailsState({ status: 'idle', error: '' })
                }}
              />
            </label>

            {form.title.trim() && (
              <div className="tmdb-lookup" aria-live="polite">
                <span className="form-section-label">TMDB MATCHES</span>
                {searchPending && <p className="control-help" role="status">Searching TMDB…</p>}
                {currentSearch && searchState.status === 'unavailable' && (
                  <p className="control-help">TMDB lookup is not configured; you can enter details manually.</p>
                )}
                {currentSearch && searchState.status === 'error' && <p className="language-error" role="alert">{searchState.error}</p>}
                {currentSearch && searchState.status === 'success' && searchState.results.length === 0 && (
                  <p className="control-help">No TMDB matches. Continue with manual entry.</p>
                )}
                {detailsState.status === 'loading' && <p className="control-help" role="status">Loading selected movie details…</p>}
                {detailsState.status === 'error' && <p className="language-error" role="alert">{detailsState.error}</p>}
                {currentSearchResults.length > 0 && (
                  <div className="tmdb-results" role="list" aria-label="TMDB movie matches">
                    {currentSearchResults.map((result) => (
                      <button
                        className={`tmdb-result${selectedTmdbId === result.tmdb_id ? ' tmdb-result--selected' : ''}`}
                        key={result.tmdb_id}
                        type="button"
                        role="listitem"
                        aria-pressed={selectedTmdbId === result.tmdb_id}
                        onClick={() => selectTmdbMovie(result)}
                      >
                        <span className="tmdb-result__poster">
                          <MovieArtwork url={result.poster_url} title={result.title} />
                        </span>
                        <span><strong>{result.title}</strong><small>{result.year || 'Year unknown'}</small></span>
                      </button>
                    ))}
                    <button className="text-button manual-entry" type="button" onClick={switchToManualEntry}>
                      None of these / enter manually
                    </button>
                  </div>
                )}
              </div>
            )}

            <div className="suggestion-fields">
              <label className="form-field">
                <span>Year</span>
                <input type="number" min="1880" max={MAX_MOVIE_YEAR} value={form.year} onChange={(event) => updateField('year', event.target.value)} />
              </label>
              <label className="form-field">
                <span>Languages</span>
                <input value={form.languages} onChange={(event) => updateField('languages', event.target.value)} placeholder="Separate with commas" />
              </label>
              <label className="form-field">
                <span>Genres</span>
                <input value={form.genres} onChange={(event) => updateField('genres', event.target.value)} placeholder="Separate with commas" />
              </label>
              <label className="form-field">
                <span>Director</span>
                <input maxLength={120} value={form.director} onChange={(event) => updateField('director', event.target.value)} />
              </label>
              <label className="form-field">
                <span>Main cast</span>
                <input value={form.cast} onChange={(event) => updateField('cast', event.target.value)} placeholder="Separate with commas" />
              </label>
              <label className="form-field form-field--wide">
                <span>Short plot</span>
                <textarea maxLength={1500} rows="3" value={form.overview} onChange={(event) => updateField('overview', event.target.value)} />
              </label>
              <label className="form-field form-field--wide">
                <span>Note to the admin</span>
                <textarea maxLength={1000} rows="2" value={form.note} onChange={(event) => updateField('note', event.target.value)} />
              </label>
              <label className="form-field form-field--wide">
                <span>Email address <small>(optional; only for updates if the movie is added)</small></span>
                <input type="email" maxLength={254} value={form.contact_email} onChange={(event) => updateField('contact_email', event.target.value)} />
              </label>
              <label className="honeypot" aria-hidden="true">
                Website
                <input
                  type="text"
                  name="website"
                  tabIndex="-1"
                  autoComplete="off"
                  value={form.website}
                  onChange={(event) => updateField('website', event.target.value)}
                />
              </label>
            </div>

            {submitState.status === 'error' && (
              <p className="language-error" role="alert">
                {submitState.httpStatus === 429 ? `Rate limit: ${submitState.error}` : submitState.error}
              </p>
            )}
            <div className="suggestion-form__actions">
              <button className="button button--outline" type="button" onClick={onClose}>Cancel</button>
              <button className="button button--primary" type="submit" disabled={submitState.status === 'loading' || !form.title.trim()}>
                {submitState.status === 'loading' ? 'Sending…' : 'Send suggestion'}
              </button>
            </div>
          </form>
        )}
      </section>
    </div>
  )
}

export default SuggestionModal

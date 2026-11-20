import { useEffect, useState } from 'react'
import { searchLanguages } from '../services/api.js'
import SelectControl from './SelectControl.jsx'

const LANGUAGE_MODES = [
  { value: 'ignore', label: 'Any language' },
  { value: 'balanced', label: 'Slight preference' },
  { value: 'prefer', label: 'Strong preference' },
  { value: 'strict', label: 'Only these languages' },
]

const MOVIE_COUNTS = [
  { value: 5, label: '5 movies' },
  { value: 10, label: '10 movies' },
  { value: 20, label: '20 movies' },
]

const RECOMMENDATION_STYLES = [
  { value: 'balanced', label: 'Balanced' },
  { value: 'genre_first', label: 'Genre first' },
  { value: 'story_first', label: 'Story first' },
  { value: 'cast_crew_first', label: 'Cast & crew first' },
]

function RecommendationControls({ options, onChange, onSubmit, isLoading }) {
  const [languages, setLanguages] = useState([])
  const [languageState, setLanguageState] = useState({ status: 'loading', error: '' })
  const [languageAttempt, setLanguageAttempt] = useState(0)
  const selectedLanguages = Array.isArray(options.languages) ? options.languages : []

  useEffect(() => {
    const controller = new AbortController()
    searchLanguages(controller.signal)
      .then((results) => {
        setLanguages(results)
        setLanguageState({ status: 'success', error: '' })
      })
      .catch((error) => {
        if (error.name !== 'AbortError') {
          setLanguageState({ status: 'error', error: error.message })
        }
      })
    return () => controller.abort()
  }, [languageAttempt])

  function update(key, value) {
    onChange((current) => ({ ...current, [key]: value }))
  }

  function toggleLanguage(language) {
    onChange((current) => {
      const selected = Array.isArray(current.languages) ? current.languages : []
      if (selected.includes(language)) {
        return { ...current, languages: selected.filter((item) => item !== language) }
      }
      if (selected.length >= 5) return current
      return {
        ...current,
        languages: [...selected, language],
        language_mode: selected.length === 0 ? 'prefer' : current.language_mode,
      }
    })
  }

  const selectedRecords = selectedLanguages.map((name) => languages.find((item) => item.name === name))
  const balanceEnabled = Boolean(options.language_balance)
  const requiredPerLanguage = balanceEnabled && selectedLanguages.length > 1
    ? Math.ceil(options.n / selectedLanguages.length)
    : options.n
  const insufficientStrictResults = options.language_mode === 'strict'
    && selectedRecords.some((item) => item && item.recommendable < requiredPerLanguage)
  const cannotSubmit = isLoading || insufficientStrictResults

  return (
    <form className="recommendation-controls" onSubmit={(event) => { event.preventDefault(); onSubmit() }}>
      <div className="control-field">
        <label id="recommendation-count-label" htmlFor="recommendation-count">Number of movies</label>
        <SelectControl
          id="recommendation-count"
          labelId="recommendation-count-label"
          value={options.n}
          options={MOVIE_COUNTS}
          onChange={(value) => update('n', value)}
        />
      </div>
      <div className="control-field">
        <label id="language-mode-label" htmlFor="language-mode">Language mode</label>
        <SelectControl
          id="language-mode"
          labelId="language-mode-label"
          value={options.language_mode}
          options={LANGUAGE_MODES}
          onChange={(value) => update('language_mode', value)}
        />
      </div>
      <div className="control-field">
        <label id="recommendation-style-label" htmlFor="recommendation-style">Recommendation style</label>
        <SelectControl
          id="recommendation-style"
          labelId="recommendation-style-label"
          value={options.preset}
          options={RECOMMENDATION_STYLES}
          onChange={(value) => update('preset', value)}
        />
      </div>

      <fieldset className="language-picker">
        <legend>Languages</legend>
        <p className="control-help">Leave unselected to use the picked movie’s language preference.</p>
        {selectedLanguages.length > 0 && (
          <div className="selected-languages" aria-label="Selected languages">
            {selectedLanguages.map((language) => (
              <button
                className="language-chip language-chip--selected"
                key={language}
                type="button"
                aria-label={`Remove ${language}`}
                onClick={() => toggleLanguage(language)}
              >
                {language} <span aria-hidden="true">×</span>
              </button>
            ))}
            <button className="text-button language-clear" type="button" onClick={() => update('languages', [])}>
              Clear
            </button>
          </div>
        )}
        {languageState.status === 'loading' && <p className="control-help" role="status">Loading catalogue languages…</p>}
        {languageState.status === 'error' && (
          <p className="language-error" role="alert">
            {languageState.error}{' '}
            <button className="text-button" type="button" onClick={() => setLanguageAttempt((attempt) => attempt + 1)}>
              Retry
            </button>
          </p>
        )}
        {languageState.status === 'success' && (
          <div className="language-options" aria-label="Available languages">
            {languages.map((language) => {
              const selected = selectedLanguages.includes(language.name)
              const tooFewMovies = language.recommendable < 50
              const limitReached = !selected && selectedLanguages.length >= 5
              return (
                <button
                  className={`language-chip${selected ? ' language-chip--selected' : ''}`}
                  key={language.id}
                  type="button"
                  aria-pressed={selected}
                  disabled={!selected && (tooFewMovies || limitReached)}
                  title={tooFewMovies ? 'Fewer than 50 recommendable movies in this language.' : undefined}
                  onClick={() => toggleLanguage(language.name)}
                >
                  {language.name} · {language.movies.toLocaleString()}
                </button>
              )
            })}
          </div>
        )}
        {selectedLanguages.length === 5 && <p className="control-help">You can select up to five languages.</p>}
        {insufficientStrictResults && (
          <p className="language-error" role="alert">
            The selected language set cannot supply {options.n} strict recommendations with the current balance setting.
          </p>
        )}
        {selectedLanguages.length > 1 && (
          <label className="language-balance">
            <input
              type="checkbox"
              checked={balanceEnabled}
              onChange={(event) => update('language_balance', event.target.checked)}
            />
            <span>
              <strong>Mix languages evenly</strong>
              <small>Otherwise, larger language catalogues may fill more slots.</small>
            </span>
          </label>
        )}
      </fieldset>

      <div className="control-field control-field--range">
        <label htmlFor="quality-weight">
          Quality influence <strong>{Number(options.quality_weight).toFixed(2)}</strong>
        </label>
        <input
          id="quality-weight"
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={options.quality_weight}
          onChange={(event) => update('quality_weight', Number(event.target.value))}
        />
        <span className="range-labels"><span>Similarity-led</span><span>Quality-led</span></span>
      </div>
      <label className="diversity-toggle">
        <span><strong>More variety</strong><small>Use MMR diversification</small></span>
        <input
          type="checkbox"
          checked={options.diversify}
          onChange={(event) => update('diversify', event.target.checked)}
        />
        <span className="toggle-track" aria-hidden="true" />
      </label>
      <button className="button button--primary recommendation-submit" type="submit" disabled={cannotSubmit}>
        {isLoading ? <><span className="button-loader" /> Finding matches…</> : <>Find Similar Movies <span aria-hidden="true">↗</span></>}
      </button>
    </form>
  )
}

export default RecommendationControls

const API_BASE = '/api'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('Unable to reach the movie service. Check that Flask is running and try again.')
  }

  let payload
  try {
    payload = await response.json()
  } catch (error) {
    if (error.name === 'AbortError') throw error
    throw new Error('The movie service returned an invalid response.')
  }

  if (!response.ok) {
    throw new ApiError(
      typeof payload?.error === 'string' ? payload.error : `The request failed (${response.status}).`,
      response.status,
    )
  }
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
    throw new Error('The movie service returned an invalid response.')
  }
  return payload
}

export async function searchMovies(query, limit = 20, signal) {
  const params = new URLSearchParams({ q: query, limit: String(limit) })
  const payload = await request(`/movies/search?${params}`, { signal })
  if (!Array.isArray(payload.results)) throw new Error('Search results were not in the expected format.')
  return payload.results
}

export async function getMovieDetails(movieId, signal) {
  const payload = await request(`/movie/${encodeURIComponent(movieId)}`, { signal })
  if (typeof payload.movie_id !== 'string' || typeof payload.title !== 'string') {
    throw new Error('Movie details were not in the expected format.')
  }
  return payload
}

export async function getRecommendations(movieId, options) {
  const payload = await request('/recommend', {
    method: 'POST',
    body: JSON.stringify({ movie_id: movieId, ...options }),
  })
  if (!Array.isArray(payload.recommendations)) {
    throw new Error('Recommendations were not in the expected format.')
  }
  return payload.recommendations
}

export async function searchLanguages(signal) {
  const payload = await request('/languages', { signal })
  if (!Array.isArray(payload.languages) || !payload.languages.every((language) => (
    typeof language?.id === 'string'
    && typeof language?.name === 'string'
    && Number.isFinite(language.movies)
    && Number.isFinite(language.recommendable)
  ))) {
    throw new Error('The language list was not in the expected format.')
  }
  return payload.languages
}

export async function tmdbSearch(query, signal) {
  const params = new URLSearchParams({ q: query })
  const payload = await request(`/tmdb/search?${params}`, { signal })
  if (typeof payload.available !== 'boolean' || !Array.isArray(payload.results)) {
    throw new Error('TMDB search results were not in the expected format.')
  }
  return payload
}

export async function tmdbMovie(tmdbId, signal) {
  const id = Number(tmdbId)
  if (!Number.isInteger(id) || id <= 0) {
    throw new Error('A valid TMDB movie ID is required.')
  }
  const payload = await request(`/tmdb/movie/${id}`, { signal })
  if (payload.tmdb_id !== id || typeof payload.title !== 'string') {
    throw new Error('TMDB movie details were not in the expected format.')
  }
  return payload
}

export async function submitSuggestion(suggestion) {
  const payload = await request('/suggestions', {
    method: 'POST',
    body: JSON.stringify(suggestion),
  })
  if (!['received', 'exists', 'duplicate'].includes(payload.status)) {
    throw new Error('The suggestion response was not in the expected format.')
  }
  return payload
}

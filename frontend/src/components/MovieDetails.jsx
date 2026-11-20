import MovieArtwork from './MovieArtwork.jsx'
import { imageUrl } from './movieImages.js'

function hasValue(value) {
  if (Array.isArray(value)) return value.some((item) => hasValue(item))
  if (typeof value === 'number') return Number.isFinite(value)
  return typeof value === 'string' && value.trim() !== '' && value.toLowerCase() !== 'nan'
}

function MovieDetails({ movie }) {
  const backdrop = imageUrl(movie.backdrop_url)
  const meta = [
    hasValue(movie.year) && { label: 'Year', value: movie.year },
    hasValue(movie.release_date) && { label: 'Release date', value: movie.release_date },
    hasValue(movie.runtime) && Number(movie.runtime) > 0 && { label: 'Runtime', value: `${Math.round(Number(movie.runtime))} min` },
    hasValue(movie.rating) && { label: 'Rating', value: `★ ${Number(movie.rating).toFixed(1)}` },
    hasValue(movie.votes) && Number(movie.votes) > 0 && { label: 'Votes', value: Number(movie.votes).toLocaleString() },
    hasValue(movie.primary_language) && { label: 'Primary language', value: movie.primary_language },
    hasValue(movie.director) && { label: 'Director', value: movie.director },
  ].filter(Boolean)

  return (
    <article className="movie-details">
      <div
        className="details-backdrop"
        style={backdrop ? { '--backdrop-image': `url("${backdrop}")` } : undefined}
      />
      <div className="details-content">
        <div className="details-poster">
          <MovieArtwork
            key={`${movie.movie_id}:${movie.poster_url ?? ''}`}
            url={movie.poster_url}
            title={movie.title}
          />
        </div>
        <div className="details-copy">
          <span className="eyebrow">MOVIE PROFILE</span>
          <h2>{movie.title}</h2>
          {hasValue(movie.original_title) && movie.original_title !== movie.title && (
            <p className="details-original">{movie.original_title}</p>
          )}
          {hasValue(movie.tagline) && <p className="details-tagline">&ldquo;{movie.tagline}&rdquo;</p>}
          {hasValue(movie.overview) && <p className="details-overview">{movie.overview}</p>}
          {meta.length > 0 && (
            <dl className="details-meta">
              {meta.map(({ label, value }) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            </dl>
          )}
          {hasValue(movie.genres) && (
            <div className="details-tags" aria-label="Genres">
              {movie.genres.filter(hasValue).map((genre) => <span key={genre}>{genre}</span>)}
            </div>
          )}
          {hasValue(movie.cast) && (
            <div className="details-people">
              <span>CAST</span>
              <p>{movie.cast.filter(hasValue).join(' · ')}</p>
            </div>
          )}
          {hasValue(movie.languages) && (
            <div className="details-people">
              <span>LANGUAGES</span>
              <p>{movie.languages.filter(hasValue).join(' · ')}</p>
            </div>
          )}
          {hasValue(movie.directors) && movie.directors.length > 1 && (
            <div className="details-people">
              <span>DIRECTORS</span>
              <p>{movie.directors.filter(hasValue).join(' · ')}</p>
            </div>
          )}
        </div>
      </div>
    </article>
  )
}

export default MovieDetails

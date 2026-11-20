import MovieArtwork from './MovieArtwork.jsx'

function valueOrNull(value) {
  return value !== null && value !== undefined && String(value).trim() !== '' && String(value).toLowerCase() !== 'nan'
}

function MovieCard({ movie, variant, onSelect }) {
  const isRecommendation = variant === 'recommendation'
  const title = isRecommendation ? movie.Title : movie.title
  const year = isRecommendation ? movie.Year : movie.year
  const genres = isRecommendation ? movie.Genres?.split(',').map((genre) => genre.trim()).filter(Boolean) : movie.genres
  const rating = isRecommendation ? movie.Rating : movie.rating

  return (
    <button className="movie-card" type="button" onClick={onSelect}>
      <MovieArtwork
        key={`${movie.movie_id ?? movie.Movie_ID}:${movie.poster_url ?? ''}`}
        url={movie.poster_url}
        title={title || 'Movie'}
      />
      <span className="movie-card__body">
        <span className="movie-card__topline">
          {valueOrNull(year) && <span>{year}</span>}
          {valueOrNull(rating) && Number.isFinite(Number(rating)) && (
            <span className="movie-rating"><span aria-hidden="true">★</span> {Number(rating).toFixed(1)}</span>
          )}
        </span>
        <strong className="movie-card__title">{title || 'Untitled movie'}</strong>
        {genres?.length > 0 && <span className="movie-card__genres">{genres.slice(0, 3).join(' · ')}</span>}
        {isRecommendation && valueOrNull(movie.Why) && (
          <span className="movie-card__why"><span>WHY THIS MATCH</span>{movie.Why}</span>
        )}
        <span className="movie-card__action">View details <span aria-hidden="true">↗</span></span>
      </span>
    </button>
  )
}

export default MovieCard

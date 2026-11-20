import MovieCard from './MovieCard.jsx'

function MovieGrid({ movies, onSelect, variant = 'search' }) {
  return (
    <div className={`movie-grid ${variant === 'recommendation' ? 'movie-grid--recommendations' : ''}`}>
      {movies.map((movie) => {
        const id = movie.movie_id ?? movie.Movie_ID
        return <MovieCard key={id} movie={movie} variant={variant} onSelect={() => onSelect(id)} />
      })}
    </div>
  )
}

export default MovieGrid

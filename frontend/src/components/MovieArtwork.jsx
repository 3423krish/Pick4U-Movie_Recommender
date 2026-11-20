import { useState } from 'react'
import { imageUrl } from './movieImages.js'

function MovieArtwork({ url, title }) {
  const src = imageUrl(url)
  const [failed, setFailed] = useState(false)

  return (
    <div className="movie-artwork">
      {src && !failed && (
        <img src={src} alt={`${title} poster`} loading="lazy" onError={() => setFailed(true)} />
      )}
      {!src || failed ? (
        <div className="artwork-placeholder" aria-hidden="true">
          <span className="artwork-placeholder__mark">P</span>
        </div>
      ) : null}
      <span className="movie-artwork__shade" />
    </div>
  )
}

export default MovieArtwork

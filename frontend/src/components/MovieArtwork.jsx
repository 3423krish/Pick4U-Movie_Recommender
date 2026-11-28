import { useState } from 'react'
import { imageAssets } from '../config/imageAssets.js'
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
          <img className="artwork-placeholder__mark" src={imageAssets.artworkPlaceholder} alt="" />
        </div>
      ) : null}
      <span className="movie-artwork__shade" />
    </div>
  )
}

export default MovieArtwork

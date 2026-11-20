export function imageUrl(url) {
  if (typeof url !== 'string') return ''
  return /^https:\/\/image\.tmdb\.org\/t\/p\/(?:w342|w500|w780|w1280|original)\/[A-Za-z0-9/_-]+\.(?:jpg|jpeg|png|webp)$/i.test(url)
    ? url
    : ''
}

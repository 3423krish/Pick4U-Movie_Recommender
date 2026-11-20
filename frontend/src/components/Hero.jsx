function Hero({ onExplore }) {
  return (
    <section className="hero-section" aria-labelledby="hero-title">
      <span className="hero-filmstrip" aria-hidden="true" />
      <div className="hero-content">
        <span className="hero-kicker">A MORE THOUGHTFUL MOVIE NIGHT</span>
        <div className="hero-heading-wrap">
          <div className="hero-lights" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          <h1 id="hero-title">
            <span>Find a film</span>
            <em>worth remembering.</em>
          </h1>
        </div>
        <p>
          Explore a real movie catalogue and discover stories connected by
          genres, themes, people, and the languages you enjoy.
        </p>
        <button className="button button--primary" type="button" onClick={onExplore}>
          Explore movies <span aria-hidden="true">↗</span>
        </button>
      </div>
      <span className="hero-note">Picks4U · Thoughtful, content-based recommendations</span>
    </section>
  )
}

export default Hero

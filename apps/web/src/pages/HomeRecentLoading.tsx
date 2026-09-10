export function HomeRecentLoading() {
  return (
    <div className="recent-strip home-recent-loading" role="status" aria-label="Loading recent projects">
      <span className="home-recent-loading__label">Loading recent projects...</span>
      {[0, 1, 2, 3].map((index) => <div key={index} className="recent-card recent-card--skeleton" aria-hidden="true" />)}
    </div>
  );
}

// Full-screen loading state shown while the initial auth check runs, and briefly during
// redirects so a protected page never flashes before the guard resolves.
export function FullScreenLoader() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        background: "#070b09",
        color: "#2bd97c",
      }}
    >
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "1rem" }}>
        <span className="spinner" />
        <span style={{ color: "#8b9a92", fontFamily: "system-ui, sans-serif", fontSize: ".9rem" }}>
          Loading…
        </span>
      </div>
      <style>{`
        .spinner {
          width: 34px; height: 34px; border-radius: 50%;
          border: 3px solid rgba(43,217,124,.2); border-top-color: #2bd97c;
          animation: spin .7s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

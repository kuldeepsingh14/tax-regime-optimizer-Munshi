// Overwritten at build time by scripts/set-env.js when the API_BASE env var is
// set (that is what Vercel does). This committed value is only the fallback
// for a local production build with no API_BASE.
export const environment = {
  production: true,
  apiBase: 'http://localhost:8000',
};

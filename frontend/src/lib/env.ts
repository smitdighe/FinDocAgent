// Typed access to import.meta.env. In dev, VITE_API_BASE_URL is usually empty
// so requests go same-origin and Vite's proxy (vite.config.ts) forwards them to
// the backend. In prod (Vercel) set it to the deployed backend origin.
export const API_BASE_URL: string = (
  import.meta.env.VITE_API_BASE_URL ?? ""
).replace(/\/$/, "");

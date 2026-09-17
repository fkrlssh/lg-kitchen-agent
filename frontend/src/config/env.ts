/**
 * Central environment configuration.
 *
 * All NEXT_PUBLIC_* env vars accessed via this module — avoid scattering
 * `process.env.NEXT_PUBLIC_*` throughout the codebase.
 *
 * For production behind nginx, paths can be relative ('/api', '/ws').
 * For local dev, full URLs (http://localhost:8000).
 */

export const config = {
  // production 빌드 (Docker/EC2) 에선 NEXT_PUBLIC_API_URL="" 로 same-origin 으로 보내고
  // nginx 가 /api → backend:8000 reverse proxy. dev 에선 localhost:8000 fallback.
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  wsUrl: process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws",
  appName: process.env.NEXT_PUBLIC_APP_NAME || "키친솔루션 한계돌파 플랫폼",
} as const;

export default config;

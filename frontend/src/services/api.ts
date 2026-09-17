/**
 * Base API client (axios).
 *
 * Add per-feature service files (e.g. `userService.ts`, `chatService.ts`)
 * that import this `api` instance.
 */
import axios, { AxiosInstance } from "axios";
import { config } from "@/config/env";

export const api: AxiosInstance = axios.create({
  baseURL: config.apiUrl,
  timeout: 10_000,
  headers: { "Content-Type": "application/json" },
});

// Request interceptor — attach JWT if present
api.interceptors.request.use((cfg) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("access_token");
    if (token) cfg.headers.Authorization = `Bearer ${token}`;
  }
  return cfg;
});

// Response interceptor — LG 사내 인증 통합 시 401/refresh 처리 자리 (현재 데모는 인증 없음)
api.interceptors.response.use(
  (res) => res,
  async (error) => Promise.reject(error),
);

export default api;

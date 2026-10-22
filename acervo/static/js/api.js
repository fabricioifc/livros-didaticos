import { elements } from "./dom.js";
import { state } from "./state.js";
import { showAuth } from "./auth.js";

export async function api(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = { ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}), ...options.headers };
  if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = state.csrf;
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/auth/login") showAuth();
    throw new Error(payload.error || "Não foi possível concluir a operação.");
  }
  if (payload.csrf_token) state.csrf = payload.csrf_token;
  return payload;
}

export function notify(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  elements.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 3800);
}

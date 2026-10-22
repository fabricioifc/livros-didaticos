import { $$ } from "./dom.js";

const STORAGE_KEY = "acervo-theme";
const systemDark = window.matchMedia("(prefers-color-scheme: dark)");

function getPreference() {
  try {
    return localStorage.getItem(STORAGE_KEY) || "auto";
  } catch {
    return "auto";
  }
}

function applyTheme(preference = getPreference()) {
  const dark = preference === "dark" || (preference === "auto" && systemDark.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

function setPreference(preference) {
  try {
    if (preference === "auto") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    // Sem armazenamento disponível, o tema vale apenas até recarregar a página.
  }
  applyTheme(preference);
}

export function bindTheme() {
  const preference = getPreference();
  $$('input[name="theme"]').forEach((input) => {
    input.checked = input.value === preference;
    input.addEventListener("change", () => setPreference(input.value));
  });
  systemDark.addEventListener("change", () => {
    if (getPreference() === "auto") applyTheme("auto");
  });
}

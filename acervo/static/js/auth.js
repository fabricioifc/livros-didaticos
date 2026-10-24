import { $, $$, elements } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { setMenuExpanded } from "./navigation.js";
import { refreshStudents } from "./students.js";

export function prepareLogin() {
  elements.authTitle.textContent = "Boas-vindas";
  elements.authIntro.textContent = "Entre com seu e-mail institucional para continuar.";
  elements.authSubmit.innerHTML = "Entrar na plataforma <span aria-hidden=\"true\">→</span>";
  elements.password.autocomplete = "current-password";
  elements.password.required = true;
}

export function showAuth() {
  elements.application.hidden = true;
  elements.authScreen.hidden = false;
  prepareLogin();
}

export function showApplication(email, isAdmin = false) {
  state.email = email;
  state.isAdmin = isAdmin;
  elements.authScreen.hidden = true;
  elements.application.hidden = false;
  setMenuExpanded(!window.matchMedia("(max-width: 760px)").matches);
  $("#users-nav-item").hidden = !isAdmin;
  $("#export-annual-backup-button").hidden = !isAdmin;
  $("#user-email").textContent = email;
  $("#user-role").textContent = isAdmin ? "Administrador" : "Servidor";
  const initials = email.split("@")[0].split(/[._-]/).slice(0, 2).map((part) => part[0]?.toUpperCase() || "").join("");
  $("#user-avatar").textContent = initials;
  const today = new Date();
  $("#today-weekday").textContent = new Intl.DateTimeFormat("pt-BR", { weekday: "long" }).format(today).toUpperCase();
  $("#today-date").textContent = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "long" }).format(today).toUpperCase();
  refreshStudents();
}

export function bindAuth() {
  elements.authForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = $("#email").value.trim();
    const password = elements.password.value;
    elements.authSubmit.disabled = true;
    try {
      const result = await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      showApplication(result.email, result.is_admin);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      elements.authSubmit.disabled = false;
    }
  });

  $("#logout-button").addEventListener("click", async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch (error) {
      notify(error.message, "error");
    }
    showAuth();
  });

  $$("[data-toggle-password]").forEach((button) => {
    button.addEventListener("click", () => {
      const input = $(`#${button.dataset.togglePassword}`);
      const showing = input.type === "password";
      input.type = showing ? "text" : "password";
      button.textContent = showing ? "Ocultar" : "Mostrar";
      button.setAttribute("aria-label", showing ? "Ocultar senha" : "Mostrar senha");
      button.setAttribute("aria-pressed", String(showing));
      input.focus();
    });
  });
}

import { $, $$, elements } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { setMenuExpanded } from "./navigation.js";
import { refreshStudents } from "./students.js";

const GOOGLE_LOGIN_ERRORS = {
  cancelado: "Login com Google cancelado.",
  sessao: "A tentativa de login com Google expirou. Tente novamente.",
  dominio: "Use uma conta Google @ifc.edu.br.",
  conta: "Esta conta Google não tem acesso ao Acervo. Fale com um administrador para cadastrar seu e-mail.",
  google: "Não foi possível concluir o login com Google. Tente novamente.",
};

export function setGoogleLogin(enabled) {
  $("#google-login-button").hidden = !enabled;
  $("#google-login-divider").hidden = !enabled;
}

// O retorno do Google chega como /?login_error=código; mostra o aviso e limpa a URL.
export function showGoogleLoginError() {
  const url = new URL(window.location.href);
  const code = url.searchParams.get("login_error");
  if (!code) return;
  notify(GOOGLE_LOGIN_ERRORS[code] || GOOGLE_LOGIN_ERRORS.google, "error");
  url.searchParams.delete("login_error");
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

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

"use strict";

const $ = (selector, scope = document) => scope.querySelector(selector);
const studentState = { csrf: "", enrollment: "", name: "", countdown: null };
const loginForm = $("#student-login-form");
const passwordForm = $("#student-password-form");
const qrSection = $("#student-qr-section");
const errorBox = $("#student-error");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function notify(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  $("#student-toast-region").append(toast);
  window.setTimeout(() => toast.remove(), 3800);
}

async function api(path, options = {}) {
  const headers = { ...(options.body ? { "Content-Type": "application/json" } : {}) };
  if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = studentState.csrf;
  const response = await fetch(path, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (payload.csrf_token) studentState.csrf = payload.csrf_token;
  if (!response.ok) throw new Error(payload.error || "Não foi possível concluir a operação.");
  return payload;
}

function showPasswordChange(required) {
  loginForm.hidden = true;
  passwordForm.hidden = false;
  $("#student-current-password").required = !required;
  $("#student-current-password").hidden = required;
  $("#student-password-help").textContent = required
    ? "Este é seu primeiro acesso ou sua senha foi redefinida. Crie uma senha pessoal com pelo menos 12 caracteres."
    : "Para alterar sua senha, informe a senha atual e escolha uma nova com pelo menos 12 caracteres.";
  $("#student-title").textContent = "Crie sua senha pessoal";
  $("#student-description").textContent = "A senha temporária não pode ser usada para gerar QR Codes.";
}

function showQrPortal(session) {
  loginForm.hidden = true;
  passwordForm.hidden = true;
  qrSection.hidden = false;
  $("#student-title").textContent = "Seu QR Code";
  $("#student-description").textContent = "Gere um código quando estiver com o servidor para registrar a entrega.";
  $("#student-welcome").textContent = `Olá, ${session.name} · Matrícula ${session.enrollment}`;
}

function displayQr(qr) {
  const target = $("#student-qr-display");
  target.replaceChildren();
  const image = document.createElement("img");
  image.src = qr.qr_data;
  image.alt = "QR Code temporário de validação";
  target.append(image);
  $("#student-qr-token").textContent = qr.token;
  $(".student-token-fallback").open = false;
  let remaining = qr.lifetime_seconds;
  $("#student-qr-countdown").textContent = `Expira em ${remaining} segundos.`;
  window.clearInterval(studentState.countdown);
  studentState.countdown = window.setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      window.clearInterval(studentState.countdown);
      studentState.countdown = null;
      target.replaceChildren(document.createTextNode("Código expirado. Gere um novo quando precisar."));
      $("#student-qr-token").textContent = "";
      $(".student-token-fallback").open = false;
      $("#student-qr-countdown").textContent = "Este código expirou.";
      return;
    }
    $("#student-qr-countdown").textContent = `Expira em ${remaining} segundos.`;
  }, 1000);
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  const form = new FormData(loginForm);
  const button = $('button[type="submit"]', loginForm);
  button.disabled = true;
  try {
    const result = await api("/api/student-auth/login", {
      method: "POST",
      body: JSON.stringify({
        enrollment: form.get("enrollment"),
        password: form.get("password"),
      }),
    });
    studentState.enrollment = result.enrollment;
    studentState.name = result.name;
    if (result.must_change_password) showPasswordChange(true);
    else showQrPortal(result);
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
});

passwordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();
  const currentPassword = $("#student-current-password").value;
  const newPassword = $("#student-new-password").value;
  if (newPassword !== $("#student-confirm-password").value) {
    showError("A confirmação não corresponde à nova senha.");
    return;
  }
  const button = $('button[type="submit"]', passwordForm);
  button.disabled = true;
  try {
    await api("/api/student-auth/password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    });
    showQrPortal({ enrollment: studentState.enrollment, name: studentState.name });
    notify("Senha atualizada com sucesso.");
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
});

$("#generate-student-qr").addEventListener("click", async (event) => {
  clearError();
  window.clearInterval(studentState.countdown);
  studentState.countdown = null;
  $("#student-qr-display").textContent = "Gerando um novo código…";
  $("#student-qr-token").textContent = "";
  $(".student-token-fallback").open = false;
  $("#student-qr-countdown").textContent = "";
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const qr = await api("/api/student-auth/qr", {
      method: "POST",
      body: JSON.stringify({}),
    });
    displayQr(qr);
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
});

$("#copy-student-qr-token").addEventListener("click", async () => {
  const token = $("#student-qr-token").textContent;
  if (!token) return;
  try {
    await navigator.clipboard.writeText(token);
    notify("Token copiado. Cole-o no leitor manual do servidor.");
  } catch (error) {
    showError(`Não foi possível copiar o token. Selecione e copie o texto exibido. ${error.message}`);
  }
});

$("#student-logout").addEventListener("click", async () => {
  try {
    await api("/api/student-auth/logout", {
      method: "POST",
      body: JSON.stringify({}),
    });
    window.clearInterval(studentState.countdown);
    window.location.reload();
  } catch (error) {
    showError(error.message);
  }
});

document.querySelectorAll("[data-toggle-password]").forEach((button) => {
  button.addEventListener("click", () => {
    const input = $(`#${button.dataset.togglePassword}`);
    const showing = input.type === "password";
    input.type = showing ? "text" : "password";
    button.textContent = showing ? "Ocultar" : "Mostrar";
    button.setAttribute("aria-pressed", String(showing));
    button.setAttribute("aria-label", `${showing ? "Ocultar" : "Mostrar"} senha`);
    input.focus();
  });
});

async function initializeStudentPortal() {
  try {
    const session = await api("/api/student-auth/session");
    if (!session.authenticated) {
      studentState.csrf = session.csrf_token;
      return;
    }
    studentState.enrollment = session.enrollment;
    studentState.name = session.name;
    studentState.csrf = session.csrf_token;
    if (session.must_change_password) showPasswordChange(true);
    else showQrPortal(session);
  } catch (error) {
    showError(error.message);
  }
}

initializeStudentPortal();

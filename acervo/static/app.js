'use strict';

const state = {
  csrf: "",
  email: "",
  isAdmin: false,
  users: [],
  students: [],
  view: "dashboard",
  grade: "all",
  currentStudent: null,
  editingStudent: null,
  signatureBook: null,
  signatureAction: "checkout",
  studentQrCode: null,
  historyBook: null,
  schoolYear: null,
  drawing: false,
  hasSignature: false,
};

const $ = (selector, scope = document) => scope.querySelector(selector);
const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
const elements = {
  authScreen: $("#auth-screen"),
  application: $("#application"),
  authForm: $("#auth-form"),
  authTitle: $("#auth-title"),
  authIntro: $("#auth-intro"),
  authSubmit: $("#auth-submit"),
  password: $("#password"),
  studentDialog: $("#student-dialog"),
  studentForm: $("#student-form"),
  detailDialog: $("#student-detail-dialog"),
  signatureDialog: $("#signature-dialog"),
  qrScanDialog: $("#qr-scan-dialog"),
  canvas: $("#signature-canvas"),
  toastRegion: $("#toast-region"),
};

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function formatDate(value, options = { day: "2-digit", month: "2-digit", year: "numeric" }) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", options).format(new Date(value));
}

function bookCounts(student) {
  const books = student.books || [];
  const issued = books.filter((book) => book.checkout_signature).length;
  const returned = books.filter((book) => book.return_signature).length;
  return { total: books.length, issued, returned, awaiting: issued - returned };
}

async function api(path, options = {}) {
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

function notify(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast toast--${type}`;
  toast.textContent = message;
  elements.toastRegion.append(toast);
  window.setTimeout(() => toast.remove(), 3800);
}

function prepareLogin() {
  elements.authTitle.textContent = "Boas-vindas";
  elements.authIntro.textContent = "Entre com seu e-mail institucional para continuar.";
  elements.authSubmit.innerHTML = "Entrar na plataforma <span aria-hidden=\"true\">→</span>";
  elements.password.autocomplete = "current-password";
  elements.password.required = true;
}

function showAuth() {
  elements.application.hidden = true;
  elements.authScreen.hidden = false;
  prepareLogin();
}

function showApplication(email, isAdmin = false) {
  state.email = email;
  state.isAdmin = isAdmin;
  elements.authScreen.hidden = true;
  elements.application.hidden = false;
  $("#users-nav-item").hidden = !isAdmin;
  $("#user-email").textContent = email;
  $("#user-role").textContent = isAdmin ? "Administrador" : "Servidor";
  const initials = email.split("@")[0].split(/[._-]/).slice(0, 2).map((part) => part[0]?.toUpperCase() || "").join("");
  $("#user-avatar").textContent = initials;
  $("#top-avatar").textContent = initials;
  const today = new Date();
  $("#today-weekday").textContent = new Intl.DateTimeFormat("pt-BR", { weekday: "long" }).format(today).toUpperCase();
  $("#today-date").textContent = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "long" }).format(today).toUpperCase();
  refreshStudents();
}

async function refreshStudents() {
  const data = await api("/api/students");
  state.schoolYear = data.school_year;
  $("#school-year-label").textContent = String(data.school_year);
  $$(".school-year-footer").forEach((element) => {
    element.textContent = String(data.school_year);
  });
  const details = await Promise.all(data.students.map(async (student) => {
    const record = await api(`/api/students/${encodeURIComponent(student.enrollment)}`);
    return { ...student, ...record };
  }));
  state.students = details;
  renderStudents();
}

function getProgress(student) {
  const counts = bookCounts(student);
  const checkout = counts.issued === counts.total;
  return {
    label: counts.issued === 0 ? "Não iniciado" : checkout ? "Completa" : `${counts.issued} de ${counts.total}`,
    returnLabel: counts.returned === 0 ? "—" : counts.returned === counts.total ? "Completa" : `${counts.returned} de ${counts.total}`,
    complete: counts.returned === counts.total,
    awaiting: counts.awaiting,
  };
}

function rowMarkup(student) {
  const progress = getProgress(student);
  const initials = student.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
  const checkoutClass = progress.label === "Completa" ? "status-pill status-pill--complete" : progress.label === "Não iniciado" ? "status-pill status-pill--muted" : "status-pill status-pill--progress";
  const returnClass = progress.returnLabel === "Completa" ? "status-pill status-pill--complete" : progress.returnLabel === "—" ? "status-pill status-pill--muted" : "status-pill status-pill--progress";
  return `<tr>
    <td><button class="student-name-button" data-action="detail" data-enrollment="${escapeHtml(student.enrollment)}"><span class="student-avatar">${escapeHtml(initials)}</span><span class="student-name">${escapeHtml(student.name)}</span></button></td>
    <td class="mono-cell">${escapeHtml(student.enrollment)}</td>
    <td><span class="grade-pill">${escapeHtml(student.grade)} ano</span></td>
    <td><span class="${checkoutClass}"><i></i>${escapeHtml(progress.label)}</span></td>
    <td><span class="${returnClass}"><i></i>${escapeHtml(progress.returnLabel)}</span></td>
    <td><button class="row-action" data-action="detail" data-enrollment="${escapeHtml(student.enrollment)}" aria-label="Abrir termo de ${escapeHtml(student.name)}">→</button></td>
  </tr>`;
}

function renderTable(table, empty, count, query = "") {
  const filtered = state.students.filter((student) => {
    const matchesGrade = state.grade === "all" || student.grade === state.grade;
    const text = `${student.name} ${student.enrollment}`.toLowerCase();
    return matchesGrade && text.includes(query.toLowerCase().trim());
  });
  table.innerHTML = filtered.map(rowMarkup).join("");
  empty.hidden = filtered.length > 0;
  table.closest(".table-scroll").hidden = filtered.length === 0;
  count.textContent = `${filtered.length} ${filtered.length === 1 ? "estudante" : "estudantes"}`;
  return filtered;
}

function renderStudents() {
  const dashboard = renderTable($("#dashboard-students"), $("#dashboard-empty"), $("#dashboard-count"), $("#dashboard-search").value);
  const list = renderTable($("#students-table"), $("#students-empty"), $("#students-count"), $("#students-search").value);
  const issued = state.students.reduce((total, student) => total + bookCounts(student).issued, 0);
  const awaiting = state.students.reduce((total, student) => total + bookCounts(student).awaiting, 0);
  const returned = state.students.reduce((total, student) => total + bookCounts(student).returned, 0);
  const total = state.students.reduce((sum, student) => sum + bookCounts(student).total, 0);
  $("#metric-students").textContent = String(state.students.length);
  $("#metric-issued").textContent = String(issued);
  $("#metric-total").textContent = String(total);
  $("#metric-awaiting").textContent = String(awaiting);
  $("#metric-complete").textContent = String(total > 0 && returned === total ? state.students.length : state.students.filter((student) => bookCounts(student).returned === bookCounts(student).total && bookCounts(student).returned > 0).length);
  $("#nav-student-count").textContent = String(state.students.length);
  $("#dashboard-empty").hidden = dashboard.length > 0;
  $("#students-empty").hidden = list.length > 0;
}

function setView(view) {
  if (view === "users" && !state.isAdmin) return;
  state.view = view;
  $("#dashboard-view").hidden = view !== "dashboard";
  $("#students-view").hidden = view !== "students";
  $("#users-view").hidden = view !== "users";
  $("#breadcrumb-current").textContent = {
    dashboard: "Visão geral",
    students: "Estudantes",
    users: "Usuários",
  }[view] || "Visão geral";
  $$(".nav-item").forEach((button) => button.classList.toggle("is-active", button.dataset.view === view));
  $("#sidebar").classList.remove("is-open");
  if (view === "users") loadManagedUsers();
}

function renderManagedUsers() {
  $("#managed-users-table").innerHTML = state.users.map((user) => `
    <tr data-user-id="${user.id}">
      <td class="mono-cell">${escapeHtml(user.email)}</td>
      <td><select class="text-input user-role-select" aria-label="Perfil de ${escapeHtml(user.email)}">
        <option value="false" ${user.is_admin ? "" : "selected"}>Servidor</option>
        <option value="true" ${user.is_admin ? "selected" : ""}>Administrador</option>
      </select></td>
      <td><select class="text-input user-status-select" aria-label="Status de ${escapeHtml(user.email)}">
        <option value="true" ${user.is_active ? "selected" : ""}>Ativo</option>
        <option value="false" ${user.is_active ? "" : "selected"}>Desativado</option>
      </select></td>
      <td><button class="button button--secondary user-save-button" data-action="save-user" type="button">Salvar</button></td>
    </tr>`).join("");
  $("#managed-users-empty").hidden = state.users.length > 0;
  $("#managed-users-table").closest(".table-scroll").hidden = state.users.length === 0;
}

async function loadManagedUsers() {
  try {
    const result = await api("/api/users");
    state.users = result.users;
    renderManagedUsers();
  } catch (error) {
    notify(error.message, "error");
    if (error.message.includes("administradores")) setView("dashboard");
  }
}

async function saveManagedUser(row) {
  const button = $(".user-save-button", row);
  button.disabled = true;
  try {
    await api(`/api/users/${row.dataset.userId}`, {
      method: "PATCH",
      body: JSON.stringify({
        is_admin: $(".user-role-select", row).value === "true",
        is_active: $(".user-status-select", row).value === "true",
      }),
    });
    notify("Permissões do usuário atualizadas.");
    await loadManagedUsers();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function openStudent(enrollment) {
  const student = state.students.find((item) => item.enrollment === enrollment);
  if (!student) return;
  try {
    const record = await api(`/api/students/${encodeURIComponent(enrollment)}`);
    state.currentStudent = { ...student, ...record };
  } catch (error) {
    notify(error.message, "error");
    return;
  }
  renderStudentDetail();
  elements.detailDialog.showModal();
}

async function selectStudentYear(year) {
  if (!state.currentStudent) return;
  const enrollment = state.currentStudent.enrollment;
  try {
    const record = await api(`/api/students/${encodeURIComponent(enrollment)}?year=${year}`);
    state.currentStudent = { ...state.currentStudent, ...record };
    renderStudentDetail();
  } catch (error) {
    notify(error.message, "error");
  }
}

function openNewStudent() {
  state.editingStudent = null;
  elements.studentForm.reset();
  $("#student-enrollment").readOnly = false;
  $("#student-dialog-title").textContent = "Adicionar estudante";
  $("#student-submit").innerHTML = "Salvar estudante <span>→</span>";
  elements.studentDialog.showModal();
}

function editCurrentStudent() {
  const student = state.currentStudent;
  if (!student) return;
  state.editingStudent = student;
  $("#student-name").value = student.name;
  $("#student-enrollment").value = student.enrollment;
  $("#student-enrollment").readOnly = true;
  $("#student-grade").value = student.grade;
  $("#student-dialog-title").textContent = "Editar estudante";
  $("#student-submit").innerHTML = "Salvar alterações <span>→</span>";
  elements.studentDialog.showModal();
}

function renderStudentDetail() {
  const student = state.currentStudent;
  const counts = bookCounts(student);
  $("#detail-school-year").textContent = String(student.school_year);
  const yearSelect = $("#detail-year-select");
  yearSelect.innerHTML = student.years.map((year) =>
    `<option value="${year.school_year}">${year.school_year}${year.status === "completed" ? " · concluído" : ""}</option>`
  ).join("");
  yearSelect.value = String(student.school_year);
  $("#edit-student-button").hidden = student.school_year !== state.schoolYear || student.status !== "active";
  $("#reset-student-access-button").hidden = !state.isAdmin;
  $("#detail-name").textContent = student.name;
  $("#detail-meta").textContent = `Matrícula ${student.enrollment} · ${student.grade} ano`;
  $("#detail-progress-label").textContent = `${counts.issued} de ${counts.total} títulos entregues`;
  $("#detail-progress-bar").style.width = `${counts.total ? Math.round((counts.issued / counts.total) * 100) : 0}%`;
  $("#book-list").innerHTML = student.books.map((book) => {
    const returned = Boolean(book.return_signature);
    const issued = Boolean(book.checkout_signature);
    const carryNotice = book.carried_forward
      ? `<span class="book-status book-status--issued"><i></i>Empréstimo iniciado em ${book.issue_year}</span>`
      : "";
    const status = returned ? `<span class="book-status book-status--returned"><i></i>Devolvido em ${formatDate(book.return_at)}</span>` : issued ? `<span class="book-status book-status--issued"><i></i>Entregue em ${formatDate(book.checkout_at)}</span>` : '<span class="book-status book-status--pending"><i></i>Aguardando assinatura</span>';
    const checkoutSignature = book.checkout_signature ? `<img class="signature-thumb" src="${escapeHtml(book.checkout_signature)}" alt="Assinatura do estudante">` : "";
    const returnSignature = book.return_signature ? `<img class="signature-thumb" src="${escapeHtml(book.return_signature)}" alt="Assinatura do servidor">` : "";
    const button = returned
      ? '<span class="book-done">Concluído <span>✓</span></span>'
      : issued
        ? `<button class="book-action book-action--return" data-action="sign-return" data-book="${escapeHtml(book.id)}"><span class="book-action-icon">↩</span> Registrar devolução</button>`
        : student.school_year === state.schoolYear && student.status === "active"
          ? `<button class="book-action" data-action="sign-checkout" data-book="${escapeHtml(book.id)}"><span class="book-action-icon">✎</span> Assinar entrega</button>`
          : '<span class="book-done">Somente consulta</span>';
    return `<article class="book-row">
      <div class="book-info"><span class="book-index">${String(student.books.indexOf(book) + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(book.title)}</strong>${carryNotice}${status}</div></div>
      <div class="book-signatures">      <span class="signature-cell">${checkoutSignature || '<span class="signature-placeholder-text">—</span>'}<small>Aluno</small></span><span class="signature-cell">${returnSignature || '<span class="signature-placeholder-text">—</span>'}<small>Servidor</small></span></div>
      <div class="book-action-cell">${button}<button class="book-history-link" data-action="book-history" data-book="${escapeHtml(book.id)}" type="button">Histórico</button></div>
    </article>`;
  }).join("");
}

async function openBookHistory(bookId) {
  state.historyBook = state.currentStudent.books.find((book) => book.id === bookId);
  if (!state.historyBook) return;
  $("#book-history-title").textContent = state.historyBook.title;
  $("#book-history-list").innerHTML = '<li class="history-empty">Carregando histórico…</li>';
  $("#history-action-message").textContent = "";
  $("#history-correction-reason").value = "";
  updateHistoryCorrectionActions();
  $("#book-history-dialog").showModal();
  await refreshBookHistory();
}

async function refreshBookHistory() {
  const path = `/api/students/${encodeURIComponent(state.currentStudent.enrollment)}/books/${encodeURIComponent(state.historyBook.id)}/history`;
  try {
    const { history } = await api(path);
    $("#book-history-list").innerHTML = history.length
      ? history.map((entry) => {
        const labels = {
          checkout: "Entrega assinada",
          return: "Devolução assinada",
          cancel_checkout: "Entrega cancelada",
          cancel_return: "Devolução cancelada",
        };
        const signature = entry.signature
          ? `<img class="history-signature" src="${escapeHtml(entry.signature)}" alt="Assinatura registrada">`
          : "";
        const actor = entry.actor_email
          ? escapeHtml(entry.actor_email)
          : "Registro importado do histórico anterior";
        const reason = entry.reason
          ? `<p class="history-reason-text"><strong>Motivo:</strong> ${escapeHtml(entry.reason)}</p>`
          : "";
        const recordedAt = entry.recorded_at && !Number.isNaN(Date.parse(entry.recorded_at))
          ? formatDate(entry.recorded_at, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })
          : "Data não registrada";
        return `<li class="book-history-entry book-history-entry--${escapeHtml(entry.action)}">
          <div class="history-entry-heading"><strong>${labels[entry.action] || "Evento"}</strong><span>Ano letivo ${entry.school_year}</span></div>
          <p>${recordedAt}</p>
          <p>Registrado por: ${actor}</p>${reason}${signature}
        </li>`;
      }).join("")
      : '<li class="history-empty">Nenhum registro de assinatura para este livro.</li>';
    updateHistoryCorrectionActions();
  } catch (error) {
    $("#book-history-list").innerHTML = `<li class="history-empty history-error">${escapeHtml(error.message)}</li>`;
  }
}

function updateHistoryCorrectionActions() {
  const book = state.historyBook;
  if (!book) return;
  $("#cancel-checkout-button").hidden = !book.checkout_signature || Boolean(book.return_signature);
  $("#cancel-return-button").hidden = !book.return_signature;
  const canCancel = !$("#cancel-checkout-button").hidden || !$("#cancel-return-button").hidden;
  $("#history-correction").hidden = !canCancel;
  const notice = book.checkout_signature && book.return_signature
    ? "Cancele a devolução antes de cancelar a entrega."
    : "";
  $("#history-action-message").textContent = notice;
}

async function cancelBookRecord(action) {
  if (!state.historyBook) return;
  const reasonField = $("#history-correction-reason");
  const reason = reasonField.value.trim();
  if (reason.length < 5) {
    $("#history-action-message").textContent = "Informe o motivo da correção (mínimo de 5 caracteres).";
    reasonField.focus();
    return;
  }
  const button = $(`#cancel-${action}-button`);
  button.disabled = true;
  $("#history-action-message").textContent = "";
  try {
    await api(
      `/api/students/${encodeURIComponent(state.currentStudent.enrollment)}/books/${encodeURIComponent(state.historyBook.id)}/${action}/cancel`,
      { method: "POST", body: JSON.stringify({ reason }) },
    );
    await refreshCurrentStudent();
    $("#history-correction-reason").value = "";
    await refreshBookHistory();
    notify(action === "checkout" ? "Entrega cancelada e registrada no histórico." : "Devolução cancelada e registrada no histórico.");
  } catch (error) {
    $("#history-action-message").textContent = error.message;
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function openSignature(bookId, action, verifiedQrCode = null) {
  if (action === "checkout" && !verifiedQrCode) {
    openQrScanner(bookId);
    return;
  }
  const book = state.currentStudent.books.find((item) => item.id === bookId);
  state.signatureBook = book;
  state.signatureAction = action;
  state.studentQrCode = verifiedQrCode;
  state.hasSignature = false;
  $("#signature-eyebrow").textContent = action === "checkout" ? "ASSINATURA DO ESTUDANTE" : "ASSINATURA DO SERVIDOR";
  $("#signature-title").textContent = action === "checkout" ? "Assine para confirmar" : "Assine a devolução";
  $("#signature-book").textContent = book.title;
  $("#signature-consent").textContent = action === "checkout"
    ? "Ao assinar, o estudante confirma o recebimento deste título e se compromete com as regras de utilização do termo."
    : `Ao assinar, você confirma a devolução deste título por ${state.currentStudent.name}.`;
  $("#signature-placeholder").textContent = action === "checkout" ? "Assine aqui com o dedo ou a caneta" : "Assinatura do servidor";
  elements.signatureDialog.showModal();
  window.requestAnimationFrame(resizeCanvas);
}

let qrScanner = null;

function stopQrCamera() {
  if (qrScanner) {
    qrScanner.destroy();
    qrScanner = null;
  }
  const video = $("#qr-camera");
  video.srcObject = null;
  video.hidden = true;
}

async function openQrScanner(bookId) {
  stopQrCamera();
  state.signatureBook = state.currentStudent.books.find((item) => item.id === bookId);
  state.studentQrCode = null;
  $("#qr-scan-status").textContent =
    `Escaneie o QR Code temporário de ${state.currentStudent.name}.`;
  $("#qr-manual-code").value = "";
  $("#qr-scan-status").classList.remove("qr-scan-status--error");
  $("#qr-camera").hidden = true;
  elements.qrScanDialog.showModal();
  if (typeof QrScanner === "undefined") {
    $("#qr-scan-status").textContent =
      "Não foi possível carregar o leitor de QR Code. Digite o código de 6 dígitos abaixo.";
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    $("#qr-scan-status").textContent =
      "A câmera não está disponível neste navegador ou endereço. Verifique se está usando HTTPS ou digite o código abaixo.";
    return;
  }

  const video = $("#qr-camera");
  video.hidden = false;
  const scanner = new QrScanner(
    video,
    (result) => {
      if (qrScanner !== scanner || !elements.qrScanDialog.open) return;
      const code = result.data;
      stopQrCamera();
      $("#qr-camera").hidden = true;
      validateStudentQr(code);
    },
    {
      preferredCamera: "environment",
      returnDetailedScanResult: true,
      onDecodeError: () => {},
    },
  );
  qrScanner = scanner;
  try {
    await scanner.start();
    if (qrScanner !== scanner || !elements.qrScanDialog.open) stopQrCamera();
  } catch (error) {
    if (qrScanner === scanner) {
      stopQrCamera();
      $("#qr-scan-status").textContent =
        "Não foi possível iniciar a câmera. Verifique a permissão ou digite o código de 6 dígitos abaixo.";
      notify(error.message, "error");
    }
  }
}

async function validateStudentQr(code) {
  try {
    const result = await api("/api/student-qr/verify", {
      method: "POST",
      body: JSON.stringify({
        code: code.trim(),
        enrollment: state.currentStudent.enrollment,
      }),
    });
    state.studentQrCode = code.trim();
    stopQrCamera();
    $("#qr-camera").hidden = true;
    elements.qrScanDialog.close();
    notify(`Estudante validado: ${result.name}.`);
    openSignature(state.signatureBook.id, "checkout", state.studentQrCode);
  } catch (error) {
    $("#qr-scan-status").textContent = error.message;
    $("#qr-scan-status").classList.add("qr-scan-status--error");
    stopQrCamera();
    $("#qr-camera").hidden = true;
    const manualCode = $("#qr-manual-code");
    manualCode.value = /^\d{6}$/.test(code.trim()) ? code.trim() : "";
    manualCode.focus();
  }
}

function resizeCanvas() {
  const canvas = elements.canvas;
  const box = canvas.getBoundingClientRect();
  if (!box.width || !box.height) return;
  const ratio = window.devicePixelRatio || 1;
  const image = state.hasSignature ? canvas.toDataURL() : "";
  canvas.width = Math.round(box.width * ratio);
  canvas.height = Math.round(box.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.lineWidth = 2.5;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = "#234b3a";
  if (image) {
    const saved = new Image();
    saved.onload = () => context.drawImage(saved, 0, 0, box.width, box.height);
    saved.src = image;
  }
}

function canvasPoint(event) {
  const bounds = elements.canvas.getBoundingClientRect();
  return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
}

function startDrawing(event) {
  event.preventDefault();
  elements.canvas.setPointerCapture(event.pointerId);
  const point = canvasPoint(event);
  const context = elements.canvas.getContext("2d");
  context.beginPath();
  context.moveTo(point.x, point.y);
  context.lineTo(point.x + 0.1, point.y + 0.1);
  context.stroke();
  state.drawing = true;
  state.hasSignature = true;
  $("#signature-placeholder").hidden = true;
}

function draw(event) {
  if (!state.drawing) return;
  event.preventDefault();
  const point = canvasPoint(event);
  const context = elements.canvas.getContext("2d");
  context.lineTo(point.x, point.y);
  context.stroke();
}

function stopDrawing() {
  state.drawing = false;
}

function clearCanvas() {
  const canvas = elements.canvas;
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  state.hasSignature = false;
  $("#signature-placeholder").hidden = false;
}

function buildPrintTermMarkup(student, date) {
  const rules = [
    "Em caso de desistência do curso ou transferência para outra instituição, os livros deverão ser devolvidos para a liberação da transferência e/ou formalização da desistência.",
    "Em caso de perda, roubo ou dano aos livros didáticos, não haverá reposição destes itens ao(à) estudante.",
  ];
  const rows = student.books.map((book) => `<tr>
    <td>${escapeHtml(book.title)}</td>
    <td>${book.checkout_signature ? `<img src="${escapeHtml(book.checkout_signature)}" alt="Assinatura do estudante"><small>${formatDate(book.checkout_at)}</small>` : '<span class="print-blank">Pendente</span>'}</td>
    <td>${book.return_signature ? `<img src="${escapeHtml(book.return_signature)}" alt="Assinatura do servidor"><small>${formatDate(book.return_at)}</small>` : '<span class="print-blank">Pendente</span>'}</td>
  </tr>`).join("");
  return `<article class="print-term">
    <header class="print-header"><div><strong>INSTITUTO FEDERAL CATARINENSE</strong><span>Campus Fraiburgo</span></div><span>TERMO DE COMPROMISSO · ${student.school_year}</span></header>
    <h1>Termo de compromisso com os livros didáticos</h1>
    <p>Eu, <strong>${escapeHtml(student.name)}</strong>, matrícula <strong>${escapeHtml(student.enrollment)}</strong>, estudante do <strong>${escapeHtml(student.grade)} ano</strong> do curso Técnico em Informática Integrado ao Ensino Médio, declaro que recebi os livros relacionados neste termo ao longo do curso e assumo a responsabilidade de devolvê-los em perfeito estado de conservação ao final do Ensino Médio, em caso de transferência para outra instituição ou de desistência do curso.</p>
    <h2>Regras de utilização dos livros didáticos (PNLD)</h2><ol>${rules.map((rule) => `<li>${escapeHtml(rule)}</li>`).join("")}</ol>
    <table class="print-table"><thead><tr><th>Título do volume</th><th>Assinatura do estudante<br>no empréstimo</th><th>Assinatura do servidor<br>na devolução</th></tr></thead><tbody>${rows}</tbody></table>
    <footer class="print-footer"><span>Fraiburgo, ${date}</span><span>Rua Cruz e Souza, nº 100 · Centro · Fraiburgo/SC · (49) 3202-8800</span></footer>
  </article>`;
}

function printTerms(students, documentTitle) {
  const date = formatDate(new Date().toISOString());
  $("#print-container").innerHTML = students
    .map((student) => buildPrintTermMarkup(student, date))
    .join("");
  const previousTitle = document.title;
  document.title = documentTitle;
  window.addEventListener("afterprint", () => {
    document.title = previousTitle;
    $("#print-container").replaceChildren();
  }, { once: true });
  window.setTimeout(() => window.print(), 100);
}

function buildPrintTerm(student) {
  printTerms([student], `termo-livros-${student.school_year}-${student.enrollment}`);
}

async function exportAnnualBackup() {
  const button = $("#export-annual-backup-button");
  button.disabled = true;
  try {
    await refreshStudents();
    const currentTerms = state.students.filter((student) => student.school_year === state.schoolYear);
    if (!currentTerms.length) {
      notify(`Não há termos registrados para ${state.schoolYear}.`, "error");
      return;
    }
    printTerms(currentTerms, `backup-termos-${state.schoolYear}`);
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function refreshCurrentStudent() {
  await refreshStudents();
  const enrollment = state.currentStudent.enrollment;
  const year = state.currentStudent.school_year;
  const record = await api(`/api/students/${encodeURIComponent(enrollment)}?year=${year}`);
  state.currentStudent = { ...state.students.find((student) => student.enrollment === enrollment), ...record };
  if (state.historyBook) {
    state.historyBook = state.currentStudent.books.find((book) => book.id === state.historyBook.id);
  }
  renderStudentDetail();
}

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

$("#add-student-button").addEventListener("click", openNewStudent);
$("#add-student-button-list").addEventListener("click", openNewStudent);
$("#import-students-button").addEventListener("click", () => $("#students-csv-input").click());
$("#students-csv-input").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const button = $("#import-students-button");
  button.disabled = true;
  try {
    const form = new FormData();
    form.append("file", file);
    const result = await api("/api/students/import", { method: "POST", body: form });
    if (result.imported > 0) await refreshStudents();
    const details = result.errors.slice(0, 3).map((item) => `linha ${item.line}: ${item.reason}`).join("; ");
    const summary = `Importados: ${result.imported}. Ignorados (matrícula já cadastrada): ${result.ignored}. Linhas inválidas: ${result.invalid}.${details ? ` ${details}` : ""}`;
    notify(summary, result.invalid > 0 ? "error" : "success");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
    event.target.value = "";
  }
});
elements.studentForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#student-submit");
  button.disabled = true;
  try {
    const form = new FormData(elements.studentForm);
    const editing = state.editingStudent;
    const enrollment = String(form.get("enrollment"));
    await api(editing ? `/api/students/${encodeURIComponent(enrollment)}` : "/api/students", {
      method: editing ? "PUT" : "POST",
      body: JSON.stringify({ name: form.get("name"), enrollment: form.get("enrollment"), grade: form.get("grade") }),
    });
    elements.studentDialog.close();
    elements.studentForm.reset();
    state.editingStudent = null;
    await refreshStudents();
    if (editing) {
      state.currentStudent = state.students.find((student) => student.enrollment === enrollment);
      renderStudentDetail();
    }
    notify(editing ? "Cadastro atualizado com sucesso." : "Estudante cadastrado com sucesso.");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

elements.studentDialog.addEventListener("close", () => {
  state.editingStudent = null;
  $("#student-enrollment").readOnly = false;
});

$("#edit-student-button").addEventListener("click", editCurrentStudent);
$("#logout-button").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch (error) {
    notify(error.message, "error");
  }
  showAuth();
});

$$(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
$$("[data-go]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.go)));
$("#menu-button").addEventListener("click", () => $("#sidebar").classList.toggle("is-open"));
$("#dashboard-search").addEventListener("input", renderStudents);
$("#students-search").addEventListener("input", renderStudents);
$$(".grade-filter").forEach((filter) => filter.addEventListener("click", (event) => {
  const button = event.target.closest("[data-grade]");
  if (!button) return;
  state.grade = button.dataset.grade;
  $$(".grade-filter").forEach((group) => $$(".filter-chip", group).forEach((chip) => chip.classList.toggle("is-selected", chip.dataset.grade === state.grade)));
  renderStudents();
}));

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  if (target.dataset.action === "detail") openStudent(target.dataset.enrollment);
  if (target.dataset.action === "add-student") openNewStudent();
  if (target.dataset.action === "sign-checkout") openSignature(target.dataset.book, "checkout");
  if (target.dataset.action === "sign-return") openSignature(target.dataset.book, "return");
  if (target.dataset.action === "book-history") openBookHistory(target.dataset.book);
  if (target.dataset.action === "save-user") saveManagedUser(target.closest("tr"));
});

elements.qrScanDialog.addEventListener("close", stopQrCamera);
$("#qr-manual-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await validateStudentQr($("#qr-manual-code").value);
});
elements.signatureDialog.addEventListener("close", () => {
  state.studentQrCode = null;
});

$$("[data-close]").forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.close}`).close()));
$("#export-term-button").addEventListener("click", () => buildPrintTerm(state.currentStudent));
$("#export-annual-backup-button").addEventListener("click", exportAnnualBackup);
$("#detail-year-select").addEventListener("change", (event) => selectStudentYear(Number(event.target.value)));
$("#signature-history-button").addEventListener("click", () => {
  if (state.signatureBook) openBookHistory(state.signatureBook.id);
});
$("#cancel-checkout-button").addEventListener("click", () => cancelBookRecord("checkout"));
$("#cancel-return-button").addEventListener("click", () => cancelBookRecord("return"));
$("#reset-student-access-button").addEventListener("click", async () => {
  if (!state.currentStudent) return;
  const button = $("#reset-student-access-button");
  button.disabled = true;
  try {
    const result = await api(
      `/api/students/${encodeURIComponent(state.currentStudent.enrollment)}/student-access`,
      { method: "POST", body: JSON.stringify({}) },
    );
    $("#student-temp-password").textContent = result.temporary_password;
    $("#student-portal-qr").src = result.portal_qr_data;
    $("#student-portal-url").href = result.portal_url;
    $("#student-portal-url").textContent = result.portal_url;
    $("#student-access-dialog").showModal();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
});
$("#managed-user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const userForm = event.currentTarget;
  const button = $("#managed-user-submit");
  button.disabled = true;
  try {
    const form = new FormData(userForm);
    await api("/api/users", {
      method: "POST",
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password"),
        is_admin: form.get("is_admin") === "on",
      }),
    });
    userForm.reset();
    notify("Usuário criado com sucesso.");
    await loadManagedUsers();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
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
$("#clear-signature").addEventListener("click", clearCanvas);
elements.canvas.addEventListener("pointerdown", startDrawing);
elements.canvas.addEventListener("pointermove", draw);
elements.canvas.addEventListener("pointerup", stopDrawing);
elements.canvas.addEventListener("pointercancel", stopDrawing);
window.addEventListener("resize", () => {
  if (elements.signatureDialog.open) resizeCanvas();
});

$("#signature-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.hasSignature) {
    notify("Faça a assinatura no campo antes de confirmar.", "error");
    return;
  }
  const button = $('button[type="submit"]', $("#signature-form"));
  button.disabled = true;
  try {
    await api(`/api/students/${encodeURIComponent(state.currentStudent.enrollment)}/books/${encodeURIComponent(state.signatureBook.id)}/${state.signatureAction}`, {
      method: "PUT",
      body: JSON.stringify({
        signature: elements.canvas.toDataURL("image/png"),
        student_qr_code: state.studentQrCode,
      }),
    });
    elements.signatureDialog.close();
    await refreshCurrentStudent();
    notify(state.signatureAction === "checkout" ? "Assinatura de entrega registrada." : "Devolução registrada com sucesso.");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
});

async function initialize() {
  prepareLogin();
  try {
    const session = await api("/api/auth/session");
    if (session.authenticated) showApplication(session.email, session.is_admin);
  } catch (error) {
    notify(error.message, "error");
  }
}

initialize();

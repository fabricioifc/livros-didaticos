import { $, elements } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { bookCounts, escapeHtml, formatDate } from "./utils.js";
import { renderStudentCourseOptions } from "./courses.js";
import { refreshStudents } from "./students.js";
import { openSignature } from "./signature.js";

export async function openStudent(enrollment, mode = "records") {
  const student = state.students.find((item) => item.enrollment === enrollment);
  if (!student) return;
  state.detailMode = mode;
  try {
    const record = await api(`/api/students/${encodeURIComponent(enrollment)}`);
    state.currentStudent = { ...student, ...record };
    state.selectedCheckoutBooks.clear();
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
    state.selectedCheckoutBooks.clear();
    renderStudentDetail();
  } catch (error) {
    notify(error.message, "error");
  }
}

function editCurrentStudent() {
  const student = state.currentStudent;
  if (!student) return;
  state.editingStudent = student;
  $("#student-name").value = student.name;
  $("#student-enrollment").value = student.enrollment;
  $("#student-grade").value = student.grade;
  renderStudentCourseOptions(student.course_id);
  $("#student-dialog-title").textContent = "Editar estudante";
  $("#student-submit").innerHTML = "Salvar alterações <span>→</span>";
  elements.studentDialog.showModal();
}

function canCheckoutCurrentCycle(student) {
  return !student.is_archived && student.school_year === state.schoolYear && student.status === "active";
}

// Livros que ainda podem ser entregues no ciclo atual: não entregues, não
// devolvidos e emitidos neste ciclo (empréstimos de ciclos anteriores ficam de fora).
function eligibleCheckoutBooks(student) {
  if (!canCheckoutCurrentCycle(student)) return [];
  return student.books.filter((book) =>
    !book.checkout_signature && !book.return_signature && book.issue_year === student.school_year
  );
}

function renderSelectAll(eligible) {
  const selectAll = $("#checkout-select-all");
  const selected = eligible.filter((book) => state.selectedCheckoutBooks.has(book.id)).length;
  selectAll.disabled = eligible.length === 0;
  selectAll.checked = eligible.length > 0 && selected === eligible.length;
  selectAll.indeterminate = selected > 0 && selected < eligible.length;
  $("#checkout-select-all-label").textContent = eligible.length
    ? `Selecionar todos (${eligible.length})`
    : "Nenhum livro disponível para entrega";
}

export function renderStudentDetail() {
  const student = state.currentStudent;
  const counts = bookCounts(student);
  const loanMode = state.detailMode === "loans";
  $("#detail-mode-label").textContent = loanMode ? "ENTREGA E DEVOLUÇÃO" : "CADASTRO";
  elements.detailDialog.classList.toggle("dialog--loan-mode", loanMode);
  $("#open-loans-button").hidden = loanMode;
  $("#detail-school-year").textContent = String(student.school_year);
  const yearSelect = $("#detail-year-select");
  yearSelect.innerHTML = student.years.map((year) =>
    `<option value="${year.school_year}">${year.school_year}${year.status === "completed" ? " · concluído" : ""}</option>`
  ).join("");
  yearSelect.value = String(student.school_year);
  $("#edit-student-button").hidden = loanMode || student.is_archived || student.school_year !== state.schoolYear || student.status !== "active";
  $("#archive-student-button").hidden = loanMode || student.is_archived;
  $("#reactivate-student-button").hidden = loanMode || !student.is_archived;
  $("#delete-student-button").hidden = loanMode || !state.isAdmin;
  $("#delete-student-button").disabled = student.has_loan_history;
  $("#delete-student-button").title = student.has_loan_history
    ? "Não é possível excluir um cadastro com empréstimos, devoluções ou histórico."
    : "Excluir definitivamente um cadastro sem movimentações";
  const archiveInfo = $("#detail-archive-info");
  archiveInfo.hidden = !student.is_archived;
  archiveInfo.textContent = student.is_archived
    ? `Desvinculado em ${formatDate(student.archived_at)} por ${student.archived_by}. Motivo: ${student.archive_reason}`
    : "";
  $("#export-student-terms-button").hidden = student.years.length < 2;
  $("#detail-name").textContent = student.name;
  $("#detail-meta").textContent = student.status === "completed"
    ? `Matrícula ${student.enrollment} · ${student.course_name} · Arquivado`
    : `Matrícula ${student.enrollment} · ${student.course_name} · ${student.grade} ano`;
  $("#detail-progress-label").textContent = `${counts.issued} de ${counts.total} títulos entregues`;
  $("#detail-progress-bar").style.width = `${counts.total ? Math.round((counts.issued / counts.total) * 100) : 0}%`;
  const canCheckout = loanMode && canCheckoutCurrentCycle(student);
  const eligible = loanMode ? eligibleCheckoutBooks(student) : [];
  const eligibleIds = new Set(eligible.map((book) => book.id));
  state.selectedCheckoutBooks.forEach((bookId) => {
    if (!eligibleIds.has(bookId)) state.selectedCheckoutBooks.delete(bookId);
  });
  $("#checkout-selection-bar").hidden = !canCheckout;
  renderSelectAll(eligible);
  $("#checkout-selection-count").textContent = `${state.selectedCheckoutBooks.size} selecionado${state.selectedCheckoutBooks.size === 1 ? "" : "s"}`;
  $("#checkout-selected-button").disabled = state.selectedCheckoutBooks.size === 0;
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
      : !loanMode
        ? ""
      : issued
        ? `<button class="book-action book-action--return" data-action="sign-return" data-book="${escapeHtml(book.id)}"><span class="book-action-icon">↩</span> Registrar devolução</button>`
        : eligibleIds.has(book.id)
          ? `<label class="book-select"><input type="checkbox" data-action="select-checkout-book" data-book="${escapeHtml(book.id)}" ${state.selectedCheckoutBooks.has(book.id) ? "checked" : ""}><span>Selecionar para entrega</span></label>`
          : '<span class="book-done">Somente consulta</span>';
    return `<article class="book-row">
      <div class="book-info"><span class="book-index">${String(student.books.indexOf(book) + 1).padStart(2, "0")}</span><div><strong>${escapeHtml(book.title)}</strong>${carryNotice}${status}</div></div>
      <div class="book-signatures">      <span class="signature-cell">${checkoutSignature || '<span class="signature-placeholder-text">—</span>'}<small>Aluno</small></span><span class="signature-cell">${returnSignature || '<span class="signature-placeholder-text">—</span>'}<small>Servidor</small></span></div>
      <div class="book-action-cell">${button}<button class="book-history-link" data-action="book-history" data-book="${escapeHtml(book.id)}" type="button">Histórico</button></div>
    </article>`;
  }).join("");
}

export async function refreshCurrentStudent() {
  await refreshStudents();
  const enrollment = state.currentStudent.enrollment;
  const year = state.currentStudent.school_year;
  const record = await api(`/api/students/${encodeURIComponent(enrollment)}?year=${year}`);
  state.currentStudent = { ...state.students.find((student) => student.enrollment === enrollment), ...record };
  state.selectedCheckoutBooks.clear();
  if (state.historyBook) {
    state.historyBook = state.currentStudent.books.find((book) => book.id === state.historyBook.id);
  }
  renderStudentDetail();
}

function openCheckoutSignature() {
  const bookIds = eligibleCheckoutBooks(state.currentStudent)
    .filter((book) => state.selectedCheckoutBooks.has(book.id))
    .map((book) => book.id);
  if (!bookIds.length) return;
  openSignature(null, "checkout", bookIds);
}

export function bindStudentDetail() {
  $("#edit-student-button").addEventListener("click", editCurrentStudent);
  $("#detail-year-select").addEventListener("change", (event) => selectStudentYear(Number(event.target.value)));
  $("#archive-student-button").addEventListener("click", () => {
    $("#student-archive-reason").value = "";
    $("#student-archive-dialog").showModal();
    $("#student-archive-reason").focus();
  });
  $("#student-archive-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const enrollment = state.currentStudent.enrollment;
    const button = $("#student-archive-submit");
    button.disabled = true;
    try {
      await api(`/api/students/${encodeURIComponent(enrollment)}/archive`, {
        method: "POST",
        body: JSON.stringify({ reason: $("#student-archive-reason").value }),
      });
      $("#student-archive-dialog").close();
      elements.detailDialog.close();
      await refreshStudents();
      await openStudent(enrollment);
      notify("Vínculo arquivado. O histórico do estudante foi preservado.");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  $("#reactivate-student-button").addEventListener("click", async () => {
    const enrollment = state.currentStudent.enrollment;
    const button = $("#reactivate-student-button");
    button.disabled = true;
    try {
      await api(`/api/students/${encodeURIComponent(enrollment)}/reactivate`, { method: "POST" });
      await refreshStudents();
      const record = await api(`/api/students/${encodeURIComponent(enrollment)}`);
      state.currentStudent = { ...state.students.find((student) => student.enrollment === enrollment), ...record };
      state.selectedCheckoutBooks.clear();
      renderStudentDetail();
      notify("Vínculo reativado. Confira a turma atual no cadastro.");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  $("#delete-student-button").addEventListener("click", async () => {
    const student = state.currentStudent;
    if (student.has_loan_history) return;
    const confirmed = window.confirm(
      `Excluir permanentemente o cadastro de ${student.name} (${student.enrollment})? Esta ação não pode ser desfeita.`
    );
    if (!confirmed) return;
    const button = $("#delete-student-button");
    button.disabled = true;
    try {
      await api(`/api/students/${encodeURIComponent(student.enrollment)}`, { method: "DELETE" });
      elements.detailDialog.close();
      await refreshStudents();
      notify("Cadastro excluído.");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("#book-list").addEventListener("change", (event) => {
    const checkbox = event.target.closest('[data-action="select-checkout-book"]');
    if (!checkbox) return;
    if (checkbox.checked) state.selectedCheckoutBooks.add(checkbox.dataset.book);
    else state.selectedCheckoutBooks.delete(checkbox.dataset.book);
    renderStudentDetail();
  });
  $("#open-loans-button").addEventListener("click", () => {
    state.detailMode = "loans";
    state.selectedCheckoutBooks.clear();
    renderStudentDetail();
  });
  $("#checkout-select-all").addEventListener("change", (event) => {
    const eligible = eligibleCheckoutBooks(state.currentStudent);
    if (event.target.checked) eligible.forEach((book) => state.selectedCheckoutBooks.add(book.id));
    else state.selectedCheckoutBooks.clear();
    renderStudentDetail();
  });
  $("#checkout-selected-button").addEventListener("click", openCheckoutSignature);
  $("#checkout-clear-selection").addEventListener("click", () => {
    state.selectedCheckoutBooks.clear();
    renderStudentDetail();
  });
}

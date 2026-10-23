import { $, elements } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { bookCounts, escapeHtml, formatDate } from "./utils.js";
import { renderStudentCourseOptions } from "./courses.js";
import { refreshStudents } from "./students.js";
import { openSignature } from "./signature.js";

export async function openStudent(enrollment) {
  const student = state.students.find((item) => item.enrollment === enrollment);
  if (!student) return;
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
  $("#student-enrollment").readOnly = true;
  $("#student-grade").value = student.grade;
  renderStudentCourseOptions(student.course_id);
  $("#student-dialog-title").textContent = "Editar estudante";
  $("#student-submit").innerHTML = "Salvar alterações <span>→</span>";
  elements.studentDialog.showModal();
}

export function renderStudentDetail() {
  const student = state.currentStudent;
  const counts = bookCounts(student);
  $("#detail-school-year").textContent = String(student.school_year);
  const yearSelect = $("#detail-year-select");
  yearSelect.innerHTML = student.years.map((year) =>
    `<option value="${year.school_year}">${year.school_year}${year.status === "completed" ? " · concluído" : ""}</option>`
  ).join("");
  yearSelect.value = String(student.school_year);
  $("#edit-student-button").hidden = student.is_archived || student.school_year !== state.schoolYear || student.status !== "active";
  $("#archive-student-button").hidden = student.is_archived;
  $("#reactivate-student-button").hidden = !student.is_archived;
  $("#delete-student-button").hidden = !state.isAdmin;
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
  const canCheckout = !student.is_archived && student.school_year === state.schoolYear && student.status === "active";
  $("#checkout-selection-bar").hidden = !canCheckout;
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
      : issued
        ? `<button class="book-action book-action--return" data-action="sign-return" data-book="${escapeHtml(book.id)}"><span class="book-action-icon">↩</span> Registrar devolução</button>`
        : canCheckout && book.issue_year === student.school_year
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

function openCheckoutConfirmation() {
  const books = state.currentStudent.books.filter((book) =>
    state.selectedCheckoutBooks.has(book.id)
  );
  if (!books.length) return;
  state.signatureBooks = books;
  $("#checkout-student-name").textContent = state.currentStudent.name;
  $("#checkout-student-enrollment").textContent = state.currentStudent.enrollment;
  $("#checkout-selected-books").innerHTML = books
    .map((book) => `<li>${escapeHtml(book.title)}</li>`)
    .join("");
  $("#enrollment-confirmation-input").value = "";
  elements.enrollmentDialog.showModal();
  $("#enrollment-confirmation-input").focus();
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

  $("#enrollment-confirmation-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const enrollment = $("#enrollment-confirmation-input").value.trim();
    if (enrollment !== state.currentStudent.enrollment) {
      notify("A matrícula informada não corresponde ao estudante selecionado.", "error");
      $("#enrollment-confirmation-input").focus();
      return;
    }
    elements.enrollmentDialog.close();
    openSignature(null, "checkout", enrollment, state.signatureBooks.map((book) => book.id));
  });
  $("#book-list").addEventListener("change", (event) => {
    const checkbox = event.target.closest('[data-action="select-checkout-book"]');
    if (!checkbox) return;
    if (checkbox.checked) state.selectedCheckoutBooks.add(checkbox.dataset.book);
    else state.selectedCheckoutBooks.delete(checkbox.dataset.book);
    renderStudentDetail();
  });
  $("#checkout-selected-button").addEventListener("click", openCheckoutConfirmation);
  $("#checkout-clear-selection").addEventListener("click", () => {
    state.selectedCheckoutBooks.clear();
    renderStudentDetail();
  });
}

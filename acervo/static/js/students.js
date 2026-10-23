import { $, $$, elements } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { bookCounts, escapeHtml } from "./utils.js";
import { courseColorClass, renderCourseFilters, renderStudentCourseOptions } from "./courses.js";
import { renderStudentDetail } from "./student-detail.js";
import { renderDashboard } from "./dashboard.js";

export async function refreshStudents() {
  const courseData = await api("/api/courses");
  state.courses = courseData.courses;
  renderStudentCourseOptions();
  renderCourseFilters();
  const data = await api("/api/students");
  state.schoolYear = data.school_year;
  $("#school-year-label").textContent = String(data.school_year);
  $("#admin-school-year-current").textContent = String(data.school_year);
  $("#school-year-input").value = String(data.school_year);
  $("#school-year-input").min = String(data.school_year);
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
  const courseColor = courseColorClass(student.course_id);
  return `<tr>
    <td><button class="student-name-button" data-action="detail" data-enrollment="${escapeHtml(student.enrollment)}"><span class="student-avatar">${escapeHtml(initials)}</span><span class="student-name">${escapeHtml(student.name)}</span></button></td>
    <td class="mono-cell">${escapeHtml(student.enrollment)}</td>
    <td><span class="course-pill ${courseColor}" title="${escapeHtml(student.course_name)}">${escapeHtml(student.course_abbreviation)}</span></td>
    <td>${student.is_archived
    ? '<span class="archived-pill">Desvinculado</span>'
    : student.status === "completed"
      ? '<span class="archived-pill">Ciclo concluído</span>'
    : `<span class="grade-pill">${escapeHtml(student.grade)} ano</span>`}</td>
    <td><span class="${checkoutClass}"><i></i>${escapeHtml(progress.label)}</span></td>
    <td><span class="${returnClass}"><i></i>${escapeHtml(progress.returnLabel)}</span></td>
    <td><button class="row-action" data-action="detail" data-enrollment="${escapeHtml(student.enrollment)}" aria-label="Abrir termo de ${escapeHtml(student.name)}">→</button></td>
  </tr>`;
}

function renderTable(table, empty, count, query = "", status = "active") {
  const filtered = state.students.filter((student) => {
    const matchesStatus = status === "archived"
      ? student.is_archived
      : !student.is_archived && student.status === status;
    const matchesGrade = status !== "active" || state.grade === "all" || student.grade === state.grade;
    const matchesCourse = state.course === "all" || String(student.course_id) === state.course;
    const text = `${student.name} ${student.enrollment} ${student.course_name}`.toLowerCase();
    return matchesStatus && matchesGrade && matchesCourse && text.includes(query.toLowerCase().trim());
  });
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  state.studentsPage = Math.min(state.studentsPage, pageCount);
  const firstItem = (state.studentsPage - 1) * pageSize;
  table.innerHTML = filtered.slice(firstItem, firstItem + pageSize).map(rowMarkup).join("");
  empty.hidden = filtered.length > 0;
  table.closest(".table-scroll").hidden = filtered.length === 0;
  count.textContent = filtered.length === 0
    ? "0 estudantes"
    : `Mostrando ${firstItem + 1}–${Math.min(firstItem + pageSize, filtered.length)} de ${filtered.length} estudantes`;
  $("#students-page-label").textContent = `Página ${state.studentsPage} de ${pageCount}`;
  $("#students-previous").disabled = state.studentsPage === 1;
  $("#students-next").disabled = state.studentsPage === pageCount;
  $("#students-pagination").hidden = filtered.length === 0;
  return filtered;
}

export function renderStudents() {
  const activeStudents = state.students.filter((student) => student.status === "active" && !student.is_archived);
  const list = renderTable($("#students-table"), $("#students-empty"), $("#students-count"), $("#students-search").value, state.studentStatus);
  const issued = activeStudents.reduce((total, student) => total + bookCounts(student).issued, 0);
  const awaiting = activeStudents.reduce((total, student) => total + bookCounts(student).awaiting, 0);
  const returned = activeStudents.reduce((total, student) => total + bookCounts(student).returned, 0);
  const total = activeStudents.reduce((sum, student) => sum + bookCounts(student).total, 0);
  $("#metric-students").textContent = String(activeStudents.length);
  $("#metric-issued").textContent = String(issued);
  $("#metric-total").textContent = String(total);
  $("#metric-awaiting").textContent = String(awaiting);
  $("#metric-complete").textContent = String(activeStudents.filter((student) => bookCounts(student).returned === bookCounts(student).total && bookCounts(student).returned > 0).length);
  $("#nav-student-count").textContent = String(activeStudents.length);
  $("#students-empty").hidden = list.length > 0;
  renderDashboard();
}

export function openNewStudent() {
  state.editingStudent = null;
  elements.studentForm.reset();
  $("#student-enrollment").readOnly = false;
  renderStudentCourseOptions();
  $("#student-dialog-title").textContent = "Adicionar estudante";
  $("#student-submit").innerHTML = "Salvar estudante <span>→</span>";
  elements.studentDialog.showModal();
}

export function bindStudents() {
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
        body: JSON.stringify({
          name: form.get("name"),
          enrollment: form.get("enrollment"),
          grade: form.get("grade"),
          course_id: Number(form.get("course_id")),
        }),
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

  $("#students-search").addEventListener("input", () => {
    state.studentsPage = 1;
    renderStudents();
  });
  $("#students-previous").addEventListener("click", () => {
    if (state.studentsPage > 1) {
      state.studentsPage -= 1;
      renderStudents();
    }
  });
  $("#students-next").addEventListener("click", () => {
    state.studentsPage += 1;
    renderStudents();
  });
  $$(".grade-filter[data-grade-filter]").forEach((filter) => filter.addEventListener("click", (event) => {
    const button = event.target.closest("[data-grade]");
    if (!button) return;
    state.grade = button.dataset.grade;
    state.studentsPage = 1;
    $$(".grade-filter[data-grade-filter]").forEach((group) => $$(".filter-chip", group).forEach((chip) => chip.classList.toggle("is-selected", chip.dataset.grade === state.grade)));
    renderStudents();
  }));
  $$(".course-filter").forEach((filter) => filter.addEventListener("click", (event) => {
    const button = event.target.closest("[data-course]");
    if (!button) return;
    state.course = button.dataset.course;
    state.studentsPage = 1;
    renderCourseFilters();
    renderStudents();
  }));
  $("#student-status-filter").addEventListener("click", (event) => {
    const button = event.target.closest("[data-student-status]");
    if (!button) return;
    state.studentStatus = button.dataset.studentStatus;
    state.studentsPage = 1;
    if (state.studentStatus !== "active") state.grade = "all";
    $$("#student-status-filter [data-student-status]").forEach((chip) =>
      chip.classList.toggle("is-selected", chip.dataset.studentStatus === state.studentStatus)
    );
    renderStudents();
  });
}

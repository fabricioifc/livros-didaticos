import { $, elements } from "./dom.js";
import { state } from "./state.js";
import { bookCounts, escapeHtml } from "./utils.js";
import { courseColorClass } from "./courses.js";
import { openStudent } from "./student-detail.js";

const MAX_RESULTS = 10;

function normalize(value) {
  return String(value).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

// Estudantes concluídos ou desvinculados continuam na busca para registrar devoluções.
function searchStudents(query) {
  const term = normalize(query.trim());
  if (term.length < 2) return [];
  const digits = /^\d+$/.test(term);
  return state.students
    .filter((student) => (digits
      ? student.enrollment.includes(term)
      : normalize(student.name).includes(term)))
    .sort((a, b) => {
      const rank = (student) => (student.enrollment === term ? 0 : 1)
        + (!student.is_archived && student.status === "active" ? 0 : 2);
      return rank(a) - rank(b) || a.name.localeCompare(b.name, "pt-BR");
    });
}

function studentSituation(student) {
  if (student.is_archived) return '<span class="archived-pill">Desvinculado</span>';
  if (student.status === "completed") return '<span class="archived-pill">Ciclo concluído</span>';
  return `<span class="grade-pill">${escapeHtml(student.grade)} ano</span>`;
}

function resultMarkup(student) {
  const counts = bookCounts(student);
  const awaitingReturn = counts.issued - counts.returned;
  const initials = student.name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("");
  return `<li><button class="loan-result" data-action="loan" data-enrollment="${escapeHtml(student.enrollment)}" type="button">
    <span class="student-avatar">${escapeHtml(initials)}</span>
    <span class="loan-result__identity"><strong>${escapeHtml(student.name)}</strong><span class="mono-cell">${escapeHtml(student.enrollment)}</span></span>
    <span class="loan-result__tags"><span class="course-pill ${courseColorClass(student.course_id)}" title="${escapeHtml(student.course_name)}">${escapeHtml(student.course_abbreviation)}</span>${studentSituation(student)}</span>
    <span class="loan-result__progress">${counts.issued} de ${counts.total} entregues${awaitingReturn ? ` · ${awaitingReturn} aguardando devolução` : ""}</span>
    <span class="loan-result__open" aria-hidden="true">→</span>
  </button></li>`;
}

export function renderLoanResults() {
  const query = $("#loans-search").value;
  const matches = searchStudents(query);
  const hint = $("#loans-hint");
  $("#loans-results").innerHTML = matches.slice(0, MAX_RESULTS).map(resultMarkup).join("");
  if (query.trim().length < 2) {
    hint.textContent = "Digite ao menos 2 letras do nome ou números da matrícula.";
  } else if (!matches.length) {
    hint.textContent = "Nenhum estudante encontrado. Confira a matrícula ou o nome.";
  } else if (matches.length > MAX_RESULTS) {
    hint.textContent = `Mostrando ${MAX_RESULTS} de ${matches.length} estudantes. Refine a busca.`;
  } else {
    hint.textContent = `${matches.length} ${matches.length === 1 ? "estudante encontrado" : "estudantes encontrados"}. Pressione Enter para abrir o primeiro.`;
  }
}

export function focusLoanSearch() {
  renderLoanResults();
  $("#loans-search").focus();
}

export function bindLoans() {
  $("#loans-search").addEventListener("input", renderLoanResults);
  $("#loans-search").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    const [first] = searchStudents(event.currentTarget.value);
    if (first) openStudent(first.enrollment, "loans");
  });
  elements.detailDialog.addEventListener("close", () => {
    if (state.view !== "loans") return;
    renderLoanResults();
    $("#loans-search").select();
  });
}

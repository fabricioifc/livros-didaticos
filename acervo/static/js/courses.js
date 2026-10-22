import { $, $$ } from "./dom.js";
import { state } from "./state.js";
import { escapeHtml } from "./utils.js";

export function courseColorClass(courseId) {
  const colorIndex = Math.abs(Number(courseId) - 1) % 6;
  return `course-color-${colorIndex}`;
}

export function renderStudentCourseOptions(selectedId = "") {
  const select = $("#student-course");
  const selected = String(selectedId || "");
  select.innerHTML = '<option value="" disabled>Selecione o curso</option>' + state.courses
    .map((course) => `<option value="${course.id}" ${!course.is_active && String(course.id) !== selected ? "disabled" : ""}>${escapeHtml(course.abbreviation)} — ${escapeHtml(course.name)}${course.is_active ? "" : " (inativo)"}</option>`)
    .join("");
  select.value = selected;
}

export function renderCourseFilters() {
  const buttons = [
    '<button class="filter-chip is-selected" data-course="all" type="button">Todos os cursos</button>',
    ...state.courses.map((course) =>
      `<button class="filter-chip ${courseColorClass(course.id)} ${String(course.id) === state.course ? "is-selected" : ""}" data-course="${course.id}" type="button" title="${escapeHtml(course.name)}" aria-label="${escapeHtml(course.name)}">${escapeHtml(course.abbreviation)}</button>`
    ),
  ].join("");
  $$(".course-filter").forEach((filter) => {
    filter.innerHTML = buttons;
    $$("[data-course]", filter).forEach((button) => {
      button.classList.toggle("is-selected", button.dataset.course === state.course);
    });
  });
}

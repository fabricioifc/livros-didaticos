import { $ } from "./dom.js";
import { state } from "./state.js";
import { escapeHtml } from "./utils.js";

const grades = ["1º", "2º", "3º"];
const gradeClasses = ["grade-1", "grade-2", "grade-3"];

function chartBar(value, max, className) {
  const width = max ? (value / max) * 100 : 0;
  return `<span class="chart-bar ${className}" style="width:${width}%" aria-hidden="true"></span>`;
}

function renderCourseChart(students) {
  const courses = new Map();
  students.forEach((student) => {
    if (!courses.has(student.course_id)) {
      courses.set(student.course_id, {
        name: student.course_name,
        counts: Object.fromEntries(grades.map((grade) => [grade, 0])),
      });
    }
    const course = courses.get(student.course_id);
    course.counts[student.grade] = (course.counts[student.grade] || 0) + 1;
  });

  const rows = [...courses.values()].sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
  const max = Math.max(1, ...rows.map((course) => Object.values(course.counts).reduce((sum, count) => sum + count, 0)));
  $("#dashboard-course-chart").innerHTML = rows.length
    ? rows.map((course) => {
      const total = Object.values(course.counts).reduce((sum, count) => sum + count, 0);
      const bars = grades.map((grade, index) => chartBar(course.counts[grade] || 0, max, gradeClasses[index])).join("");
      return `<div class="chart-row"><span class="chart-label" title="${escapeHtml(course.name)}">${escapeHtml(course.name)}</span><span class="chart-track" role="img" aria-label="${escapeHtml(course.name)}: ${grades.map((grade) => `${grade} ano ${course.counts[grade] || 0}`).join(", ")}">${bars}</span><strong class="chart-total">${total}</strong></div>`;
    }).join("")
    : '<div class="chart-empty">Nenhum estudante cadastrado neste ciclo.</div>';
}

function renderBookChart(students) {
  const books = new Map();
  students.forEach((student) => {
    student.books.forEach((book) => {
      if (!books.has(book.id)) {
        books.set(book.id, { title: book.title, delivery: 0, awaitingReturn: 0, returned: 0 });
      }
      const counts = books.get(book.id);
      if (book.checkout_signature && book.return_signature) {
        counts.returned += 1;
      } else if (book.checkout_signature) {
        counts.awaitingReturn += 1;
      } else if (book.issue_year === student.school_year) {
        counts.delivery += 1;
      }
    });
  });

  const rows = [...books.values()].sort((a, b) => a.title.localeCompare(b.title, "pt-BR"));
  const max = Math.max(1, ...rows.map((book) => book.delivery + book.awaitingReturn + book.returned));
  $("#dashboard-book-chart").innerHTML = rows.length
    ? rows.map((book) => {
      const total = book.delivery + book.awaitingReturn + book.returned;
      const bars = [
        chartBar(book.delivery, max, "book-delivery"),
        chartBar(book.awaitingReturn, max, "book-awaiting-return"),
        chartBar(book.returned, max, "book-returned"),
      ].join("");
      const label = `${book.title}: ${book.delivery} aguardando entrega, ${book.awaitingReturn} aguardando devolução, ${book.returned} devolvidos`;
      return `<div class="chart-row chart-row--book"><span class="chart-label" title="${escapeHtml(book.title)}">${escapeHtml(book.title)}</span><span class="chart-track" role="img" aria-label="${escapeHtml(label)}">${bars}</span><strong class="chart-total">${total}</strong></div>`;
    }).join("")
    : '<div class="chart-empty">Nenhum livro registrado neste ciclo.</div>';
}

export function renderDashboard() {
  const students = state.students.filter((student) => student.status === "active" && !student.is_archived);
  const groups = new Map();
  let deliveryBooks = 0;
  let returnBooks = 0;
  const deliveryStudents = new Set();
  const returnStudents = new Set();

  state.students.filter((student) => !student.is_archived && student.status === "active" || student.is_archived)
    .forEach((student) => {
    const key = `${student.course_id}:${student.grade}:${student.is_archived}`;
    if (!groups.has(key)) {
      groups.set(key, {
        courseName: student.course_name,
        grade: student.grade,
        isArchived: student.is_archived,
        students: 0,
        delivery: 0,
        awaitingReturn: 0,
      });
    }
    const group = groups.get(key);
    group.students += 1;
    student.books.forEach((book) => {
      if (book.checkout_signature && !book.return_signature) {
        group.awaitingReturn += 1;
        returnBooks += 1;
        returnStudents.add(student.enrollment);
      } else if (!student.is_archived && !book.checkout_signature && book.issue_year === student.school_year) {
        group.delivery += 1;
        deliveryBooks += 1;
        deliveryStudents.add(student.enrollment);
      }
    });
  });

  $("#report-delivery-books").textContent = String(deliveryBooks);
  $("#report-delivery-students").textContent = String(deliveryStudents.size);
  $("#report-return-books").textContent = String(returnBooks);
  $("#report-return-students").textContent = String(returnStudents.size);
  const pendingRows = [...groups.values()]
    .sort((a, b) => Number(a.isArchived) - Number(b.isArchived) || a.courseName.localeCompare(b.courseName, "pt-BR") || a.grade.localeCompare(b.grade, "pt-BR"))
    .map((group) => `<tr><td>${group.isArchived ? "Desvinculado" : "Ativo"}</td><td>${escapeHtml(group.courseName)}</td><td>${escapeHtml(group.grade)} ano</td><td>${group.students}</td><td>${group.delivery}</td><td>${group.awaitingReturn}</td></tr>`);
  $("#dashboard-pending-table").innerHTML = pendingRows.join("");
  $("#dashboard-pending-empty").hidden = pendingRows.length > 0;
  $("#dashboard-pending-table").closest(".table-scroll").hidden = pendingRows.length === 0;

  renderCourseChart(students);
  renderBookChart(students);
}

import { $ } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { escapeHtml, formatDate } from "./utils.js";

function buildPrintTermMarkup(student, date) {
  const rules = [
    "Em caso de desistência do curso ou transferência para outra instituição, os livros deverão ser devolvidos para a liberação da transferência e/ou formalização da desistência.",
    "Em caso de perda, roubo ou dano aos livros didáticos, não haverá reposição destes itens ao(à) estudante.",
  ];
  const rows = [...student.books]
    .sort((first, second) => first.title.localeCompare(second.title, "pt-BR", { sensitivity: "base" }))
    .map((book) => `<tr>
    <td>${escapeHtml(book.title)}</td>
    <td>${book.checkout_signature ? `<img src="${escapeHtml(book.checkout_signature)}" alt="Assinatura do estudante"><small>${formatDate(book.checkout_at)}</small>` : '<span class="print-blank">Pendente</span>'}</td>
    <td>${book.return_signature ? `<img src="${escapeHtml(book.return_signature)}" alt="Assinatura do servidor"><small>${formatDate(book.return_at)}</small>` : '<span class="print-blank">Pendente</span>'}</td>
  </tr>`).join("");
  return `<article class="print-term">
    <header class="print-header"><div><strong>INSTITUTO FEDERAL CATARINENSE</strong><span>Campus Fraiburgo</span></div><span>TERMO DE COMPROMISSO · ${student.school_year}</span></header>
    <h1>Termo de compromisso com os livros didáticos</h1>
    <p>Eu, <strong>${escapeHtml(student.name)}</strong>, matrícula <strong>${escapeHtml(student.enrollment)}</strong>, estudante da turma do <strong>${escapeHtml(student.grade)} ano</strong> do curso <strong>${escapeHtml(student.course_name)} (${escapeHtml(student.course_abbreviation)})</strong>, declaro que recebi os livros relacionados neste termo ao longo do curso e assumo a responsabilidade de devolvê-los em perfeito estado de conservação ao final do Ensino Médio, em caso de transferência para outra instituição ou de desistência do curso.</p>
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
  try {
    const { school_years: years } = await api("/api/school-years");
    $("#backup-school-year").innerHTML = years
      .map((year) => `<option value="${year}" ${year === state.schoolYear ? "selected" : ""}>${year}</option>`)
      .join("");
    $("#annual-backup-dialog").showModal();
  } catch (error) {
    notify(error.message, "error");
  }
}

async function printAnnualBackup(year) {
  const button = $("#annual-backup-submit");
  button.disabled = true;
  try {
    const { students } = await api(`/api/students?year=${encodeURIComponent(year)}`);
    if (!students.length) {
      notify(`Não há termos registrados para ${year}.`, "error");
      return;
    }
    const terms = await Promise.all(students.map((student) =>
      api(`/api/students/${encodeURIComponent(student.enrollment)}?year=${encodeURIComponent(year)}`)
    ));
    printTerms(terms, `backup-termos-${year}`);
    $("#annual-backup-dialog").close();
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function exportStudentTerms() {
  if (!state.currentStudent) return;
  const button = $("#export-student-terms-button");
  button.disabled = true;
  try {
    const terms = await Promise.all(state.currentStudent.years.map((year) =>
      api(`/api/students/${encodeURIComponent(state.currentStudent.enrollment)}?year=${encodeURIComponent(year.school_year)}`)
    ));
    printTerms(terms, `termos-${state.currentStudent.enrollment}`);
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

export function bindPrint() {
  $("#export-term-button").addEventListener("click", () => buildPrintTerm(state.currentStudent));
  $("#export-annual-backup-button").addEventListener("click", exportAnnualBackup);
  $("#annual-backup-form").addEventListener("submit", (event) => {
    event.preventDefault();
    printAnnualBackup(Number($("#backup-school-year").value));
  });
  $("#export-student-terms-button").addEventListener("click", exportStudentTerms);
}

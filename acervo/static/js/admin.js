import { $ } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { escapeHtml, formatDate } from "./utils.js";
import { showAuth } from "./auth.js";
import { courseColorClass, renderCourseFilters, renderStudentCourseOptions } from "./courses.js";
import { setView } from "./navigation.js";
import { refreshStudents } from "./students.js";
import { renderStudentDetail } from "./student-detail.js";

function renderManagedCourses() {
  $("#courses-table").innerHTML = state.courses.map((course) => `
    <tr data-course-id="${course.id}">
      <td><span class="course-pill ${courseColorClass(course.id)}">${escapeHtml(course.abbreviation)}</span></td>
      <td>${escapeHtml(course.name)}</td>
      <td>${course.student_count}</td>
      <td>${course.is_active ? "Ativo" : "Inativo"}</td>
      <td><button class="button button--secondary course-toggle-button" data-action="toggle-course" type="button">${course.is_active ? "Desativar" : "Reativar"}</button></td>
    </tr>`).join("");
  $("#courses-empty").hidden = state.courses.length > 0;
  $("#courses-table").closest(".table-scroll").hidden = state.courses.length === 0;
}

export async function loadManagedCourses() {
  try {
    const result = await api("/api/courses");
    state.courses = result.courses;
    renderCourseFilters();
    renderManagedCourses();
    renderStudentCourseOptions($("#student-course").value);
  } catch (error) {
    notify(error.message, "error");
  }
}

export async function toggleCourse(row) {
  const course = state.courses.find((item) => item.id === Number(row.dataset.courseId));
  const button = $(".course-toggle-button", row);
  if (!course) return;
  button.disabled = true;
  try {
    await api(`/api/courses/${course.id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: !course.is_active }),
    });
    await loadManagedCourses();
    renderStudentCourseOptions($("#student-course").value);
    notify(course.is_active ? "Curso desativado." : "Curso reativado.");
  } catch (error) {
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

const BOOK_APPLICATIONS = { "1º": "Somente 1º ano", "2º": "Somente 2º ano", "3º": "Somente 3º ano" };

const BOOKS_PAGE_SIZE = 10;

function bookApplication(book) {
  return BOOK_APPLICATIONS[book.grade] || "Volume único";
}

function bookApplicationClass(book) {
  return book.grade ? `book-app-${book.grade[0]}` : "book-app-single";
}

function filteredBooks() {
  const query = state.booksQuery.trim().toLocaleLowerCase("pt-BR");
  return state.books.filter((book) =>
    (!query || book.title.toLocaleLowerCase("pt-BR").includes(query))
    && (state.booksApplication === "all" || (book.grade || "single") === state.booksApplication)
    && (state.booksStatus === "all" || book.is_active === (state.booksStatus === "active"))
  );
}

function renderManagedBooks() {
  const books = filteredBooks();
  const pageCount = Math.max(1, Math.ceil(books.length / BOOKS_PAGE_SIZE));
  state.booksPage = Math.min(state.booksPage, pageCount);
  const firstItem = (state.booksPage - 1) * BOOKS_PAGE_SIZE;
  $("#books-table").innerHTML = books.slice(firstItem, firstItem + BOOKS_PAGE_SIZE).map((book) => `
    <tr data-book-id="${book.id}" class="${book.is_active ? "" : "is-inactive"}">
      <td>${escapeHtml(book.title)}</td>
      <td><span class="course-pill ${bookApplicationClass(book)}">${bookApplication(book)}</span></td>
      <td><span class="status-pill ${book.is_active ? "status-pill--complete" : "status-pill--inactive"}"><i></i>${book.is_active ? "Ativo" : "Inativo"}</span></td>
      <td><div class="book-row-actions">
        <button class="button button--secondary" data-book-action="edit" type="button">Editar</button>
        <button class="button button--secondary" data-book-action="toggle" type="button">${book.is_active ? "Desativar" : "Reativar"}</button>
        <button class="button button--danger-quiet" data-book-action="delete" type="button" ${book.is_used ? 'disabled title="Livro com entregas registradas: desative-o em vez de excluir."' : ""}>Excluir</button>
      </div></td>
    </tr>`).join("");
  $("#books-empty").hidden = books.length > 0;
  $("#books-empty-title").textContent = state.books.length ? "Nenhum livro encontrado com esses filtros" : "Nenhum livro cadastrado";
  $("#books-table").closest(".table-scroll").hidden = books.length === 0;
  const total = state.books.length;
  $("#books-count").textContent = books.length
    ? `Mostrando ${firstItem + 1}–${Math.min(firstItem + BOOKS_PAGE_SIZE, books.length)} de ${books.length} ${books.length === 1 ? "livro" : "livros"}${books.length < total ? ` (${total} no catálogo)` : ""}`
    : `0 de ${total} livros`;
  $("#books-page-label").textContent = `Página ${state.booksPage} de ${pageCount}`;
  $("#books-previous").disabled = state.booksPage === 1;
  $("#books-next").disabled = state.booksPage === pageCount;
}

function selectBookFilter(container, button, key, value) {
  container.querySelectorAll(".filter-chip").forEach((chip) => chip.classList.toggle("is-selected", chip === button));
  state[key] = value;
  state.booksPage = 1;
  renderManagedBooks();
}

export async function loadManagedBooks() {
  try {
    const result = await api("/api/books");
    state.books = result.books;
    renderManagedBooks();
  } catch (error) {
    notify(error.message, "error");
  }
}

function resetBookForm() {
  state.editingBook = null;
  $("#book-form").reset();
  $("#book-grade").disabled = false;
  $("#book-grade").title = "";
  $("#book-form-title").textContent = "Cadastrar livro";
  $("#book-submit").textContent = "Cadastrar livro";
  $("#book-cancel-edit").hidden = true;
}

function editBook(book) {
  state.editingBook = book;
  $("#book-title").value = book.title;
  $("#book-grade").value = book.grade || "";
  // A aplicação define o identificador de cada entrega; só muda antes da primeira.
  $("#book-grade").disabled = book.is_used;
  $("#book-grade").title = book.is_used ? "Livro já entregue: a aplicação não pode ser alterada." : "";
  $("#book-form-title").textContent = "Editar livro";
  $("#book-submit").textContent = "Salvar alterações";
  $("#book-cancel-edit").hidden = false;
  $("#book-title").focus();
}

async function saveBook(book, changes, message) {
  await api(`/api/books/${book.id}`, {
    method: "PUT",
    body: JSON.stringify({ title: book.title, grade: book.grade, is_active: book.is_active, ...changes }),
  });
  await loadManagedBooks();
  notify(message);
}

async function handleBookAction(button) {
  const book = state.books.find((item) => item.id === Number(button.closest("tr").dataset.bookId));
  if (!book) return;
  const action = button.dataset.bookAction;
  if (action === "edit") {
    editBook(book);
    return;
  }
  if (action === "delete" && !window.confirm(`Excluir o livro "${book.title}" do catálogo?`)) return;
  button.disabled = true;
  try {
    if (action === "toggle") {
      await saveBook(book, { is_active: !book.is_active }, book.is_active
        ? "Livro desativado. Ele deixa de aparecer nos termos em que ainda não foi entregue."
        : "Livro reativado e incluído nos termos do ano letivo atual.");
    } else if (action === "delete") {
      await api(`/api/books/${book.id}`, { method: "DELETE" });
      if (state.editingBook?.id === book.id) resetBookForm();
      await loadManagedBooks();
      notify("Livro excluído do catálogo.");
    }
  } catch (error) {
    notify(error.message, "error");
    button.disabled = false;
  }
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

export async function loadManagedUsers() {
  try {
    const result = await api("/api/users");
    state.users = result.users;
    renderManagedUsers();
  } catch (error) {
    notify(error.message, "error");
    if (error.message.includes("administradores")) setView("dashboard");
  }
}

export async function saveManagedUser(row) {
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

function backupUrl(filename) {
  return `/api/backups/${encodeURIComponent(filename)}`;
}

function downloadBackup(filename) {
  const link = document.createElement("a");
  link.href = backupUrl(filename);
  link.download = filename;
  link.click();
}

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1).replace(".", ",")} MB`;
}

function renderBackups(backups) {
  $("#backups-table").innerHTML = backups.map((backup) => `
    <tr>
      <td class="mono-cell">${escapeHtml(backup.filename)}</td>
      <td>${formatDate(backup.created_at, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
      <td>${formatSize(backup.size)}</td>
      <td><a class="button button--secondary" href="${backupUrl(backup.filename)}" download="${escapeHtml(backup.filename)}">Baixar</a></td>
    </tr>`).join("");
  $("#backups-empty").hidden = backups.length > 0;
  $("#backups-table").closest(".table-scroll").hidden = backups.length === 0;
}

export async function loadBackups() {
  try {
    const result = await api("/api/backups");
    renderBackups(result.backups);
  } catch (error) {
    notify(error.message, "error");
  }
}

export function bindAdmin() {
  $("#book-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("#book-submit");
    const editing = state.editingBook;
    const title = $("#book-title").value;
    const grade = $("#book-grade").value || null;
    button.disabled = true;
    try {
      if (editing) {
        await saveBook(editing, { title, grade }, "Livro atualizado.");
      } else {
        await api("/api/books", { method: "POST", body: JSON.stringify({ title, grade }) });
        await loadManagedBooks();
        notify("Livro cadastrado e incluído nos termos do ano letivo atual.");
      }
      resetBookForm();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
  $("#book-cancel-edit").addEventListener("click", resetBookForm);
  $("#books-search").addEventListener("input", (event) => {
    state.booksQuery = event.target.value;
    state.booksPage = 1;
    renderManagedBooks();
  });
  $("#books-application-filter").addEventListener("click", (event) => {
    const button = event.target.closest("[data-book-application]");
    if (button) selectBookFilter(event.currentTarget, button, "booksApplication", button.dataset.bookApplication);
  });
  $("#books-status-filter").addEventListener("click", (event) => {
    const button = event.target.closest("[data-book-status]");
    if (button) selectBookFilter(event.currentTarget, button, "booksStatus", button.dataset.bookStatus);
  });
  $("#books-previous").addEventListener("click", () => {
    state.booksPage = Math.max(1, state.booksPage - 1);
    renderManagedBooks();
  });
  $("#books-next").addEventListener("click", () => {
    state.booksPage += 1;
    renderManagedBooks();
  });
  $("#books-table").addEventListener("click", (event) => {
    const button = event.target.closest("[data-book-action]");
    if (button) handleBookAction(button);
  });

  $("#backup-create-button").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await api("/api/backups", { method: "POST" });
      downloadBackup(result.backup.filename);
      notify("Backup criado e validado.");
      await loadBackups();
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("#backup-restore-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const file = $("#backup-restore-file").files[0];
    if (!window.confirm(`Substituir todos os dados atuais pelo backup "${file.name}"?`)) return;
    const button = $("#backup-restore-submit");
    button.disabled = true;
    try {
      const body = new FormData();
      body.append("backup", file);
      const result = await api("/api/backups/restore", { method: "POST", body });
      form.reset();
      showAuth();
      notify(`Backup restaurado. Entre novamente. Cópia de segurança: ${result.safety_backup.filename}.`);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("#course-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $("#course-submit");
    button.disabled = true;
    try {
      await api("/api/courses", {
        method: "POST",
        body: JSON.stringify({
          name: $("#course-name").value,
          abbreviation: $("#course-abbreviation").value,
        }),
      });
      form.reset();
      await loadManagedCourses();
      notify("Curso cadastrado com sucesso.");
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

  $("#school-year-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const button = $("#school-year-submit");
    button.disabled = true;
    try {
      const result = await api("/api/settings/school-year", {
        method: "POST",
        body: JSON.stringify({ school_year: Number($("#school-year-input").value) }),
      });
      if (result.backup) {
        const backupLink = $("#school-year-backup-link");
        backupLink.href = `/api/backups/${encodeURIComponent(result.backup.filename)}`;
        backupLink.download = result.backup.filename;
        $("#school-year-backup-status").hidden = false;
        backupLink.click();
      }
      loadBackups();
      const enrollment = state.currentStudent?.enrollment;
      await refreshStudents();
      if (enrollment) {
        const record = await api(`/api/students/${encodeURIComponent(enrollment)}`);
        state.currentStudent = {
          ...state.students.find((student) => student.enrollment === enrollment),
          ...record,
        };
        state.selectedCheckoutBooks.clear();
        renderStudentDetail();
      }
      $("#school-year-confirm").checked = false;
      notify(`Ano letivo atualizado para ${result.school_year}. Ciclos e turmas foram atualizados.`);
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
}

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

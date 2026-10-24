import { $, $$ } from "./dom.js";
import { api, notify } from "./api.js";
import { bindAuth, prepareLogin, showApplication } from "./auth.js";
import { bindNavigation } from "./navigation.js";
import { bindStudents, openNewStudent } from "./students.js";
import { bindStudentDetail, openStudent } from "./student-detail.js";
import { bindLoans } from "./loans.js";
import { bindHistory, openBookHistory } from "./history.js";
import { bindSignature, openSignature } from "./signature.js";
import { bindPrint } from "./print.js";
import { bindAdmin, saveManagedUser, toggleCourse } from "./admin.js";
import { bindTheme } from "./theme.js";
import { bindPwa } from "./pwa.js";

function bindGlobalActions() {
  document.addEventListener("click", (event) => {
    const target = event.target.closest("[data-action]");
    if (!target) return;
    if (target.dataset.action === "detail") openStudent(target.dataset.enrollment);
    if (target.dataset.action === "loan") openStudent(target.dataset.enrollment, "loans");
    if (target.dataset.action === "add-student") openNewStudent();
    if (target.dataset.action === "sign-return") openSignature(target.dataset.book, "return");
    if (target.dataset.action === "book-history") openBookHistory(target.dataset.book);
    if (target.dataset.action === "save-user") saveManagedUser(target.closest("tr"));
    if (target.dataset.action === "toggle-course") toggleCourse(target.closest("tr"));
  });
  $$("[data-close]").forEach((button) => button.addEventListener("click", () => $(`#${button.dataset.close}`).close()));
}

async function initialize() {
  bindAuth();
  bindNavigation();
  bindStudents();
  bindStudentDetail();
  bindLoans();
  bindHistory();
  bindSignature();
  bindPrint();
  bindAdmin();
  bindTheme();
  bindPwa();
  bindGlobalActions();
  prepareLogin();
  try {
    const session = await api("/api/auth/session");
    if (session.authenticated) showApplication(session.email, session.is_admin);
  } catch (error) {
    notify(error.message, "error");
  }
}

initialize();

import { $, $$, elements } from "./dom.js";
import { state } from "./state.js";
import { loadManagedCourses, loadManagedUsers } from "./admin.js";

export function setMenuExpanded(expanded) {
  const isMobile = window.matchMedia("(max-width: 760px)").matches;
  if (isMobile) {
    $("#sidebar").classList.toggle("is-open", expanded);
  } else {
    elements.application.classList.toggle("sidebar-collapsed", !expanded);
  }
  const label = expanded ? "Ocultar menu lateral" : "Mostrar menu lateral";
  $("#menu-button").setAttribute("aria-expanded", String(expanded));
  $("#menu-button").setAttribute("aria-label", label);
  $("#menu-button").title = label;
}

export function setAdminTab(tabName) {
  $$("[data-admin-tab]").forEach((button) => {
    const selected = button.dataset.adminTab === tabName;
    button.classList.toggle("is-active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  $$(".admin-panel").forEach((panel) => {
    panel.hidden = panel.id !== `admin-panel-${tabName}`;
  });
}

export function setView(view) {
  if (view === "users" && !state.isAdmin) return;
  state.view = view;
  $("#dashboard-view").hidden = view !== "dashboard";
  $("#students-view").hidden = view !== "students";
  $("#users-view").hidden = view !== "users";
  $("#breadcrumb-current").textContent = {
    dashboard: "Visão geral",
    students: "Estudantes",
    users: "Administração",
  }[view] || "Visão geral";
  $$(".nav-item").forEach((button) => button.classList.toggle("is-active", button.dataset.view === view));
  if (window.matchMedia("(max-width: 760px)").matches) setMenuExpanded(false);
  if (view === "users") {
    setAdminTab("courses");
    loadManagedUsers();
    loadManagedCourses();
  }
}

export function bindNavigation() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $$("[data-go]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.go)));
  $("#menu-button").addEventListener("click", () => {
    setMenuExpanded($("#menu-button").getAttribute("aria-expanded") !== "true");
  });
  $$("[data-admin-tab]").forEach((button) => {
    button.addEventListener("click", () => setAdminTab(button.dataset.adminTab));
    button.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const tabs = $$("[data-admin-tab]");
      const currentIndex = tabs.indexOf(button);
      const step = event.key === "ArrowRight" ? 1 : -1;
      const next = tabs[(currentIndex + step + tabs.length) % tabs.length];
      next.focus();
      setAdminTab(next.dataset.adminTab);
    });
  });
}

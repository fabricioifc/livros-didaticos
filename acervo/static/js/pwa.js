import { $ } from "./dom.js";
import { notify } from "./api.js";

function isInstalled() {
  return window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone === true;
}

export function bindPwa() {
  const button = $("#install-app-button");
  if (isInstalled()) button.hidden = true;

  let installPrompt = null;
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    button.hidden = false;
  });

  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    button.hidden = true;
  });

  button.addEventListener("click", async () => {
    if (!installPrompt) {
      notify("Use o menu do navegador e escolha “Instalar aplicativo” ou “Adicionar à tela inicial”.", "info");
      return;
    }
    const prompt = installPrompt;
    installPrompt = null;
    try {
      await prompt.prompt();
      await prompt.userChoice;
    } catch (error) {
      console.error("Não foi possível abrir o diálogo de instalação do Acervo IFC.", error);
      notify("Não foi possível iniciar a instalação. Tente pelo menu do navegador.", "error");
    }
  });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js")
      .catch((error) => {
        console.error("Não foi possível registrar o service worker do Acervo IFC.", error);
      });
  }
}

// Carregado antes do CSS para aplicar o tema sem piscar a tela.
// A preferência é gerenciada por js/theme.js.
(function () {
  var preference = "auto";
  try {
    preference = localStorage.getItem("acervo-theme") || "auto";
  } catch (error) {}
  var dark = preference === "dark"
    || (preference !== "light" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
})();

import { $, elements } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { escapeHtml } from "./utils.js";
import { refreshCurrentStudent } from "./student-detail.js";
import { openBookHistory } from "./history.js";

export function openSignature(bookId, action, bookIds = []) {
  const book = state.currentStudent.books.find((item) => item.id === bookId);
  state.signatureBook = book || null;
  state.signatureBooks = bookIds.length
    ? state.currentStudent.books.filter((item) => bookIds.includes(item.id))
    : book ? [book] : [];
  state.signatureBook = state.signatureBooks.length === 1 ? state.signatureBooks[0] : null;
  state.signatureAction = action;
  state.hasSignature = false;
  $("#signature-eyebrow").textContent = action === "checkout" ? "ASSINATURA DO ESTUDANTE" : "ASSINATURA DO SERVIDOR";
  $("#signature-title").textContent = action === "checkout"
    ? `Assine para retirar ${state.signatureBooks.length} ${state.signatureBooks.length === 1 ? "livro" : "livros"}`
    : "Assine a devolução";
  $("#signature-book").innerHTML = state.signatureBooks
    .map((item) => `<li>${escapeHtml(item.title)}</li>`)
    .join("");
  $("#signature-consent").textContent = action === "checkout"
    ? `Ao assinar, o estudante confirma o recebimento dos ${state.signatureBooks.length === 1 ? "livro listado" : "livros listados"} acima e se compromete com as regras de utilização do termo.`
    : `Ao assinar, você confirma a devolução deste título por ${state.currentStudent.name}.`;
  $("#signature-placeholder").textContent = action === "checkout" ? "Assine aqui com o dedo ou a caneta" : "Assinatura do servidor";
  $("#signature-history-button").hidden = state.signatureBooks.length !== 1;
  elements.signatureDialog.showModal();
  window.requestAnimationFrame(resizeCanvas);
}

function resizeCanvas() {
  const canvas = elements.canvas;
  const box = canvas.getBoundingClientRect();
  if (!box.width || !box.height) return;
  const ratio = window.devicePixelRatio || 1;
  const image = state.hasSignature ? canvas.toDataURL() : "";
  canvas.width = Math.round(box.width * ratio);
  canvas.height = Math.round(box.height * ratio);
  const context = canvas.getContext("2d");
  context.scale(ratio, ratio);
  context.lineWidth = 2.5;
  context.lineCap = "round";
  context.lineJoin = "round";
  context.strokeStyle = "#234b3a";
  if (image) {
    const saved = new Image();
    saved.onload = () => context.drawImage(saved, 0, 0, box.width, box.height);
    saved.src = image;
  }
}

function canvasPoint(event) {
  const bounds = elements.canvas.getBoundingClientRect();
  return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
}

function startDrawing(event) {
  event.preventDefault();
  elements.canvas.setPointerCapture(event.pointerId);
  const point = canvasPoint(event);
  const context = elements.canvas.getContext("2d");
  context.beginPath();
  context.moveTo(point.x, point.y);
  context.lineTo(point.x + 0.1, point.y + 0.1);
  context.stroke();
  state.drawing = true;
  state.hasSignature = true;
  $("#signature-placeholder").hidden = true;
}

function draw(event) {
  if (!state.drawing) return;
  event.preventDefault();
  const point = canvasPoint(event);
  const context = elements.canvas.getContext("2d");
  context.lineTo(point.x, point.y);
  context.stroke();
}

function stopDrawing() {
  state.drawing = false;
}

function clearCanvas() {
  const canvas = elements.canvas;
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  state.hasSignature = false;
  $("#signature-placeholder").hidden = false;
}

export function bindSignature() {
  $("#signature-history-button").addEventListener("click", () => {
    if (state.signatureBook) openBookHistory(state.signatureBook.id);
  });
  $("#clear-signature").addEventListener("click", clearCanvas);
  elements.canvas.addEventListener("pointerdown", startDrawing);
  elements.canvas.addEventListener("pointermove", draw);
  elements.canvas.addEventListener("pointerup", stopDrawing);
  elements.canvas.addEventListener("pointercancel", stopDrawing);
  window.addEventListener("resize", () => {
    if (elements.signatureDialog.open) resizeCanvas();
  });

  $("#signature-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.hasSignature) {
      notify("Faça a assinatura no campo antes de confirmar.", "error");
      return;
    }
    const button = $('button[type="submit"]', $("#signature-form"));
    button.disabled = true;
    try {
      const signature = elements.canvas.toDataURL("image/png");
      if (state.signatureAction === "checkout") {
        await api(
          `/api/students/${encodeURIComponent(state.currentStudent.enrollment)}/books/checkout`,
          {
            method: "POST",
            body: JSON.stringify({
              book_ids: state.signatureBooks.map((book) => book.id),
              signature,
            }),
          },
        );
      } else {
        await api(`/api/students/${encodeURIComponent(state.currentStudent.enrollment)}/books/${encodeURIComponent(state.signatureBook.id)}/${state.signatureAction}`, {
          method: "PUT",
          body: JSON.stringify({ signature }),
        });
      }
      elements.signatureDialog.close();
      await refreshCurrentStudent();
      notify(state.signatureAction === "checkout"
        ? `Entrega de ${state.signatureBooks.length} ${state.signatureBooks.length === 1 ? "livro registrada" : "livros registrada"} com uma assinatura.`
        : "Devolução registrada com sucesso.");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      button.disabled = false;
    }
  });
}

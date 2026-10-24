import { $ } from "./dom.js";
import { state } from "./state.js";
import { api, notify } from "./api.js";
import { escapeHtml, formatDate } from "./utils.js";
import { refreshCurrentStudent } from "./student-detail.js";

export async function openBookHistory(bookId) {
  state.historyBook = state.currentStudent.books.find((book) => book.id === bookId);
  if (!state.historyBook) return;
  $("#book-history-title").textContent = state.historyBook.title;
  $("#book-history-list").innerHTML = '<li class="history-empty">Carregando histórico…</li>';
  $("#history-action-message").textContent = "";
  $("#history-correction-reason").value = "";
  updateHistoryCorrectionActions();
  $("#book-history-dialog").showModal();
  await refreshBookHistory();
}

async function refreshBookHistory() {
  const path = `/api/students/${encodeURIComponent(state.currentStudent.enrollment)}/books/${encodeURIComponent(state.historyBook.id)}/history`;
  try {
    const { history } = await api(path);
    $("#book-history-list").innerHTML = history.length
      ? history.map((entry) => {
        const labels = {
          checkout: "Entrega assinada",
          return: "Devolução assinada",
          cancel_checkout: "Entrega cancelada",
          cancel_return: "Devolução cancelada",
        };
        const signature = entry.signature
          ? `<img class="history-signature" src="${escapeHtml(entry.signature)}" alt="Assinatura registrada">`
          : "";
        const actor = entry.actor_email
          ? escapeHtml(entry.actor_email)
          : "Registro importado do histórico anterior";
        const reason = entry.reason
          ? `<p class="history-reason-text"><strong>Motivo:</strong> ${escapeHtml(entry.reason)}</p>`
          : "";
        const recordedAt = entry.recorded_at && !Number.isNaN(Date.parse(entry.recorded_at))
          ? formatDate(entry.recorded_at, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })
          : "Data não registrada";
        return `<li class="book-history-entry book-history-entry--${escapeHtml(entry.action)}">
          <div class="history-entry-heading"><strong>${labels[entry.action] || "Evento"}</strong><span>Ano letivo ${entry.school_year}</span></div>
          <p>${recordedAt}</p>
          <p>Registrado por: ${actor}</p>${reason}${signature}
        </li>`;
      }).join("")
      : '<li class="history-empty">Nenhum registro de assinatura para este livro.</li>';
    updateHistoryCorrectionActions();
  } catch (error) {
    $("#book-history-list").innerHTML = `<li class="history-empty history-error">${escapeHtml(error.message)}</li>`;
  }
}

function updateHistoryCorrectionActions() {
  const book = state.historyBook;
  if (!book) return;
  // Correções fazem parte do fluxo de entrega; no cadastro o histórico é só consulta.
  const loanMode = state.detailMode === "loans";
  $("#cancel-checkout-button").hidden = !loanMode || !book.checkout_signature || Boolean(book.return_signature);
  $("#cancel-return-button").hidden = !loanMode || !book.return_signature;
  const canCancel = !$("#cancel-checkout-button").hidden || !$("#cancel-return-button").hidden;
  $("#history-correction").hidden = !canCancel;
  const notice = book.checkout_signature && book.return_signature
    ? "Cancele a devolução antes de cancelar a entrega."
    : "";
  $("#history-action-message").textContent = notice;
}

async function cancelBookRecord(action) {
  if (!state.historyBook) return;
  const reasonField = $("#history-correction-reason");
  const reason = reasonField.value.trim();
  if (reason.length < 5) {
    $("#history-action-message").textContent = "Informe o motivo da correção (mínimo de 5 caracteres).";
    reasonField.focus();
    return;
  }
  const button = $(`#cancel-${action}-button`);
  button.disabled = true;
  $("#history-action-message").textContent = "";
  try {
    await api(
      `/api/students/${encodeURIComponent(state.currentStudent.enrollment)}/books/${encodeURIComponent(state.historyBook.id)}/${action}/cancel`,
      { method: "POST", body: JSON.stringify({ reason }) },
    );
    await refreshCurrentStudent();
    $("#history-correction-reason").value = "";
    await refreshBookHistory();
    notify(action === "checkout" ? "Entrega cancelada e registrada no histórico." : "Devolução cancelada e registrada no histórico.");
  } catch (error) {
    $("#history-action-message").textContent = error.message;
    notify(error.message, "error");
  } finally {
    button.disabled = false;
  }
}

export function bindHistory() {
  $("#cancel-checkout-button").addEventListener("click", () => cancelBookRecord("checkout"));
  $("#cancel-return-button").addEventListener("click", () => cancelBookRecord("return"));
}

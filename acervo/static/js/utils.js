export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

export function formatDate(value, options = { day: "2-digit", month: "2-digit", year: "numeric" }) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pt-BR", options).format(new Date(value));
}

export function bookCounts(student) {
  const books = student.books || [];
  const issued = books.filter((book) => book.checkout_signature).length;
  const returned = books.filter((book) => book.return_signature).length;
  return { total: books.length, issued, returned, awaiting: issued - returned };
}

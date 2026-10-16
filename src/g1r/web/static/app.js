// Open the modal whenever htmx loads content into it; close buttons carry data-close.
document.addEventListener("htmx:afterSwap", (event) => {
  const modal = document.getElementById("modal");
  if (event.detail.target.id === "modal-body" && !modal.open) modal.showModal();
});
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-close]")) document.getElementById("modal").close();
});

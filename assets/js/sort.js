(() => {
  const grid = document.getElementById("carsGrid");
  const btnPrice = document.getElementById("sortPrice");
  const btnYear = document.getElementById("sortYear");

  if (!grid || !btnPrice || !btnYear) return;

  const arrowPrice = btnPrice.querySelector(".btn-arrow");
  const arrowYear = btnYear.querySelector(".btn-arrow");

  // State
  let activeField = null; // "price" | "year" | null
  let direction = null;   // "asc" | "desc" | null

  function toNumberOrNull(value) {
    if (value === undefined || value === null) return null;
    const s = String(value).trim();
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  }

  // Missing values always at the bottom (for both asc/desc)
  function compareNullableNumbers(a, b, dir) {
    const aMissing = (a === null);
    const bMissing = (b === null);

    if (aMissing && bMissing) return 0;
    if (aMissing) return 1;
    if (bMissing) return -1;

    if (a === b) return 0;

    // Normal numeric compare
    return dir === "asc" ? (a - b) : (b - a);
  }

  function setActiveButton(field, dir) {
    // Reset all
    btnPrice.classList.remove("is-active");
    btnYear.classList.remove("is-active");
    if (arrowPrice) arrowPrice.textContent = "";
    if (arrowYear) arrowYear.textContent = "";

    const arrow = dir === "asc" ? "↑" : "↓";

    if (field === "price") {
      btnPrice.classList.add("is-active");
      if (arrowPrice) arrowPrice.textContent = arrow;
    } else if (field === "year") {
      btnYear.classList.add("is-active");
      if (arrowYear) arrowYear.textContent = arrow;
    }
  }

  function sortTiles(field, dir) {
    // Only sort existing tiles
    const tiles = Array.from(grid.querySelectorAll(".car-card"));

    tiles.sort((elA, elB) => {
      const a = toNumberOrNull(elA.dataset[field]);
      const b = toNumberOrNull(elB.dataset[field]);
      return compareNullableNumbers(a, b, dir);
    });

    // Re-append in new order (moves nodes, doesn’t recreate)
    for (const tile of tiles) grid.appendChild(tile);
  }

  function onSortClick(field) {
    // If same button clicked again -> toggle direction
    if (activeField === field) {
      direction = (direction === "asc") ? "desc" : "asc";
    } else {
      activeField = field;

      // Default directions:
      // price: low->high, year: new->old
      direction = (field === "price") ? "asc" : "desc";
    }

    setActiveButton(activeField, direction);
    sortTiles(activeField, direction);
  }

  btnPrice.addEventListener("click", () => onSortClick("price"));
  btnYear.addEventListener("click", () => onSortClick("year"));
})();
  
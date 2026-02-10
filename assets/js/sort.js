(() => {
  const grid = document.getElementById("carsGrid");
  const btnPrice = document.getElementById("sortPrice");
  const btnYear = document.getElementById("sortYear");

  if (!grid || !btnPrice || !btnYear) return;

  const arrowPrice = btnPrice.querySelector(".btn-arrow");
  const arrowYear = btnYear.querySelector(".btn-arrow");

  // Capture initial (default) order once
  const originalTiles = Array.from(grid.querySelectorAll(".car-card"));

  // State
  let activeField = null; // "price" | "releaseyear" | null
  let direction = null;   // "asc" | "desc" | null
  let clickNo = 0;

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

  function clearActiveButton() {
    // Reset all
    btnPrice.classList.remove("is-active");
    btnYear.classList.remove("is-active");
    if (arrowPrice) arrowPrice.textContent = "";
    if (arrowYear) arrowYear.textContent = "";
  }

  function setActiveButton(field, dir) {
    clearActiveButton();
    const arrow = dir === "asc" ? "↑" : "↓";

    if (field === "price") {
      btnPrice.classList.add("is-active");
      if (arrowPrice) arrowPrice.textContent = arrow;
    } else if (field === "releaseyear") {
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

  // Reset to Jekyll’s default order
  function resetTiles() {
    for (const tile of originalTiles) grid.appendChild(tile);
  }

  function onSortClick(field) {
    clickNo = clickNo + 1
    // Same button clicked
    if (activeField === field) {
      direction = (direction === "asc") ? "desc" : "asc";
      if (clickNo == 3) {
        // 3rd click => reset to default
        clickNo = 0;
        activeField = null;
        direction = null;
        clearActiveButton();
        resetTiles();
        btnPrice.blur();
        btnYear.blur();
        return;
      }
    } else {
      activeField = field;
      direction = (field === "price") ? "asc" : "desc";
      clickNo = 1;
    }

    setActiveButton(activeField, direction);
    sortTiles(activeField, direction);
  }

  btnPrice.addEventListener("click", () => onSortClick("price"));
  btnYear.addEventListener("click", () => onSortClick("releaseyear"));
})();

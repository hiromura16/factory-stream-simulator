const filter = document.querySelector("#help-filter");
if (filter) {
  const tables = Array.from(document.querySelectorAll(".help-content article table"));
  const rows = tables.flatMap((table) => Array.from(table.querySelectorAll("tbody tr")));
  const labels = rows.map((row) => row.textContent.normalize("NFKC").toLocaleLowerCase("ja"));
  const result = document.querySelector("#help-results");
  const update = () => {
    const terms = filter.value.normalize("NFKC").toLocaleLowerCase("ja").trim().split(/\s+/).filter(Boolean);
    let count = 0;
    for (const [i, row] of rows.entries()) {
      row.hidden = !terms.every((term) => labels[i].includes(term));
      if (!row.hidden) count += 1;
    }
    for (const table of tables) {
      const empty = !table.querySelector("tbody tr:not([hidden])");
      table.hidden = empty;
      const heading = table.previousElementSibling;
      if (heading?.matches("h2, h3")) heading.hidden = empty;
    }
    result.textContent = count ? `${count}件` : "該当する項目がありません";
  };
  filter.closest(".help-search").hidden = false;
  filter.addEventListener("input", update);
  update();
}

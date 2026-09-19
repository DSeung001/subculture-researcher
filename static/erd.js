// Highlight the relations of the hovered/focused table in the ERD.
const erd = document.getElementById("erd");
if (erd) {
  const relations = [...erd.querySelectorAll(".erd-rel")];
  const focus = (name) => {
    erd.classList.toggle("has-focus", Boolean(name));
    relations.forEach((rel) => rel.classList.toggle("on", Boolean(name) && rel.dataset.tables.split(" ").includes(name)));
    erd.querySelectorAll(".erd-table").forEach((table) => {
      const related = Boolean(name) && relations.some((rel) => {
        const tables = rel.dataset.tables.split(" ");
        return tables.includes(name) && tables.includes(table.dataset.table);
      });
      table.classList.toggle("on", Boolean(name) && (table.dataset.table === name || related));
    });
  };
  erd.querySelectorAll(".erd-table").forEach((table) => {
    table.addEventListener("mouseenter", () => focus(table.dataset.table));
    table.addEventListener("focus", () => focus(table.dataset.table));
    table.addEventListener("mouseleave", () => focus(null));
    table.addEventListener("blur", () => focus(null));
  });
}

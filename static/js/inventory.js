const inventoryEditor = document.querySelector("[data-inventory-editor]");

if (inventoryEditor) {
  const lines = inventoryEditor.querySelector("[data-lines]");
  const emptyLine = inventoryEditor.querySelector("[data-empty-line]");
  const addLine = inventoryEditor.querySelector("[data-add-line]");
  const totalForms = inventoryEditor.querySelector("[name$='-TOTAL_FORMS']");
  const maxForms = inventoryEditor.querySelector("[name$='-MAX_NUM_FORMS']");

  function scaled(input, places) {
    const match = /^(\d*)(?:\.(\d*))?$/.exec(input);
    if (!match || !(match[1] || match[2]) || (match[2] || "").length > places) return null;
    return BigInt((match[1] || "0") + (match[2] || "").padEnd(places, "0"));
  }

  function money(amount) {
    return `${(amount / 10000n).toLocaleString("en-IN")}.${String(amount % 10000n).padStart(4, "0")}`;
  }

  function updateTotals() {
    let total = 0n;
    let hasValue = false;
    for (const line of lines.querySelectorAll("[data-line]")) {
      const quantity = scaled(line.querySelector("[name$='-quantity']").value, 3);
      const cost = scaled(line.querySelector("[name$='-unit_cost']").value, 4);
      const item = line.querySelector("select");
      const removed = line.querySelector("[name$='-DELETE']")?.checked;
      const output = line.querySelector("[data-line-value]");
      output.textContent = "—";
      if (removed || !item.value || !quantity || cost === null) continue;
      const product = quantity * cost;
      const remainder = product % 1000n;
      let value = product / 1000n;
      if (remainder > 500n || (remainder === 500n && value % 2n)) value += 1n;
      output.textContent = money(value);
      total += value;
      hasValue = true;
    }
    inventoryEditor.querySelector("[data-document-total]").textContent = hasValue ? money(total) : "—";
  }

  addLine.hidden = false;
  addLine.disabled = Number(totalForms.value) >= Number(maxForms.value);
  addLine.addEventListener("click", () => {
    const index = Number(totalForms.value);
    if (index >= Number(maxForms.value)) return;
    const row = emptyLine.content.cloneNode(true);
    for (const element of row.querySelectorAll("[name], [id], [for], [aria-describedby]")) {
      for (const attribute of ["name", "id", "for", "aria-describedby"]) {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, element.getAttribute(attribute).replaceAll("__prefix__", index));
        }
      }
    }
    row.querySelector("[data-line-number]").textContent = index + 1;
    const item = row.querySelector("select");
    lines.append(row);
    totalForms.value = index + 1;
    addLine.disabled = index + 1 >= Number(maxForms.value);
    item.focus();
  });
  inventoryEditor.addEventListener("input", updateTotals);
  inventoryEditor.addEventListener("change", updateTotals);
  updateTotals();
}

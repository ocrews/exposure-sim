// Map tracing: hover, focus, or tap a node to highlight every line touching it.
document.querySelectorAll(".map").forEach((map) => {
  const nodes = map.querySelectorAll(".node");
  const edges = map.querySelectorAll(".edge");
  let pinned = null;

  function trace(id) {
    map.classList.toggle("tracing", !!id);
    nodes.forEach((n) => n.classList.remove("hot"));
    edges.forEach((e) => e.classList.remove("hot"));
    if (!id) return;
    edges.forEach((e) => {
      if (e.dataset.src === id || e.dataset.dst === id) {
        e.classList.add("hot");
        map.querySelectorAll(`.node[data-id="${e.dataset.src}"], .node[data-id="${e.dataset.dst}"]`)
          .forEach((n) => n.classList.add("hot"));
      }
    });
  }

  nodes.forEach((n) => {
    const id = n.dataset.id;
    n.addEventListener("mouseenter", () => { if (!pinned) trace(id); });
    n.addEventListener("mouseleave", () => { if (!pinned) trace(null); });
    n.addEventListener("focus", () => trace(id));
    n.addEventListener("blur", () => { if (!pinned) trace(null); });
    n.addEventListener("click", () => { pinned = pinned === id ? null : id; trace(pinned); });
  });
});

// OOP stage: PaginatedApiParser is only a valid parent once the player creates that class.
const midToggle = document.querySelector('[data-toggles="paginated"]');
if (midToggle) {
  const sync = () => {
    document.querySelectorAll('option[data-needs="paginated"]').forEach((opt) => {
      opt.disabled = !midToggle.checked;
      if (!midToggle.checked && opt.selected) opt.parentElement.value = "base";
    });
  };
  midToggle.addEventListener("change", sync);
  sync();
}

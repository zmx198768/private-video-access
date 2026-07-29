document.addEventListener("DOMContentLoaded", () => {
  const navigation = document.querySelector(".system-nav");
  if (!navigation) return;

  const groups = Array.from(navigation.querySelectorAll(".system-nav-group"));
  const closeGroups = (except = null) => {
    groups.forEach((group) => {
      if (group !== except) group.removeAttribute("open");
    });
  };

  groups.forEach((group) => {
    group.addEventListener("toggle", () => {
      if (group.open) closeGroups(group);
    });
  });

  document.addEventListener("click", (event) => {
    if (!navigation.contains(event.target)) closeGroups();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeGroups();
      navigation.querySelector(".system-nav-group summary:focus")?.blur();
    }
  });
});

/* Tiny dark-mode toggle (no framework).
 * Sets `class="dark"` on <html>; persists to localStorage; respects system.
 */
(function () {
  const KEY = "rwai-theme";
  function apply(theme) {
    const dark =
      theme === "dark" ||
      (theme === "system" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
    document.documentElement.dataset.theme = theme;
  }
  function read() {
    return localStorage.getItem(KEY) || "system";
  }
  function set(theme) {
    localStorage.setItem(KEY, theme);
    apply(theme);
  }
  // initial paint — run before DOMContentLoaded to avoid FOUC
  apply(read());
  // expose
  window.rwaiTheme = {
    get: read,
    set,
    toggle() {
      const cur = read();
      const next =
        cur === "dark" ? "light" : cur === "light" ? "system" : "dark";
      set(next);
    },
  };
  // react to OS changes when on "system"
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (read() === "system") apply("system");
    });
})();

import { defineStore } from "pinia";

// Which look the UI wears:
//   "ultimit" -- glass-black Altimit-style skin, following the desktop skin
//   "neko"    -- the original pink neko theme (still in tokens.css)
// Under Ultimit (backend says so: XDG_CURRENT_DESKTOP=Ultimit or
// ~/.config/ultimit/shell.json exists) the default is "ultimit" and the skin
// (mine/amber/silver/verdant) is polled from the backend every few seconds,
// so changing it in Ultimit's Settings re-skins NekoMail live. There's no
// switcher; ?theme=neko / ?theme=ultimit (remembered) is a developer override.
const CACHE_KEY = "nekomail.skin";
const OVERRIDE_KEY = "nekomail.theme";
const POLL_MS = 3000;
export const SKINS = ["mine", "amber", "silver", "verdant"];

function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function safeSet(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // storage unavailable: skin just isn't cached between launches
  }
}

function readOverride() {
  const q = new URLSearchParams(window.location.search).get("theme");
  if (q === "neko" || q === "ultimit") safeSet(OVERRIDE_KEY, q);
  else if (q === "auto") safeSet(OVERRIDE_KEY, null);
  const v = safeGet(OVERRIDE_KEY);
  return v === "neko" || v === "ultimit" ? v : null;
}

export const useThemeStore = defineStore("theme", {
  state: () => {
    const cached = safeGet(CACHE_KEY);
    const override = readOverride();
    return {
      override,
      // Optimistic first paint from the last known skin; corrected by the first poll.
      name: override || (cached ? "ultimit" : "neko"),
      skin: SKINS.includes(cached) ? cached : "mine",
      timer: null,
    };
  },
  getters: {
    isUltimit: (s) => s.name === "ultimit",
  },
  actions: {
    apply() {
      const root = document.documentElement;
      root.dataset.theme = this.name;
      root.dataset.skin = this.skin;
    },
    async refresh() {
      try {
        const res = await fetch("/api/ultimit/skin", { cache: "no-store" });
        if (!res.ok) return;
        const data = await res.json();
        const skin = SKINS.includes(data.skin) ? data.skin : "mine";
        const name = this.override || (data.ultimit ? "ultimit" : "neko");
        if (name !== this.name || skin !== this.skin) {
          this.name = name;
          this.skin = skin;
          this.apply();
        }
        safeSet(CACHE_KEY, data.ultimit ? skin : null);
      } catch {
        // server briefly unreachable: keep the current skin
      }
    },
    start() {
      this.apply();
      this.refresh();
      if (!this.timer) this.timer = setInterval(() => this.refresh(), POLL_MS);
    },
  },
});

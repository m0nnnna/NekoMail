import { defineStore } from "pinia";

const STORAGE_KEY = "nekomail.dark";

export const useUiStore = defineStore("ui", {
  state: () => ({
    dark: localStorage.getItem(STORAGE_KEY)
      ? localStorage.getItem(STORAGE_KEY) === "1"
      : window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false,
  }),
  actions: {
    applyTheme() {
      document.documentElement.classList.toggle("dark-mode", this.dark);
    },
    toggleDark() {
      this.dark = !this.dark;
      localStorage.setItem(STORAGE_KEY, this.dark ? "1" : "0");
      this.applyTheme();
    },
  },
});

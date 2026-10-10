import { defineStore } from "pinia";
import { api, ApiError } from "@/api/client";

// Native Ultimit window only: the pywebview host can trade the server's local
// token for a fresh session (expired cookie, server restarted...), so the user
// never meets the login page on their own desktop. Tried at most once per
// page load; plain browsers / LAN clients simply get the normal login.
let triedLocalLogin = false;
async function tryLocalLogin() {
  const api = window.pywebview?.api;
  if (triedLocalLogin || !api?.local_login_url) return false;
  triedLocalLogin = true;
  try {
    const url = await api.local_login_url();
    if (url) {
      window.location.href = url;
      return true;
    }
  } catch {
    // fall through to the normal login page
  }
  return false;
}

export const useAuthStore = defineStore("auth", {
  state: () => ({
    user: null,
    status: "unknown", // "unknown" | "authenticated" | "anonymous"
  }),
  actions: {
    async fetchMe() {
      try {
        this.user = await api.get("/auth/me");
        this.status = "authenticated";
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          if (await tryLocalLogin()) return false; // navigating to the local session URL
          this.user = null;
          this.status = "anonymous";
        } else {
          throw err;
        }
      }
      return this.status === "authenticated";
    },
    async login(username, password) {
      this.user = await api.post("/auth/login", { username, password });
      this.status = "authenticated";
    },
    async logout() {
      await api.post("/auth/logout");
      this.user = null;
      this.status = "anonymous";
    },
  },
});

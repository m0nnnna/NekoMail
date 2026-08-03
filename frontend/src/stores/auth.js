import { defineStore } from "pinia";
import { api, ApiError } from "@/api/client";

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

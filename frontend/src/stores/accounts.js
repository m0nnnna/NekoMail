import { defineStore } from "pinia";
import { api } from "@/api/client";

export const useAccountsStore = defineStore("accounts", {
  state: () => ({
    items: [],
    loaded: false,
    loading: false,
  }),
  actions: {
    async fetchAll() {
      this.loading = true;
      try {
        this.items = await api.get("/accounts");
        this.loaded = true;
      } finally {
        this.loading = false;
      }
    },
    async create(data) {
      const account = await api.post("/accounts", data);
      this.items.push(account);
      return account;
    },
    async update(id, data) {
      const account = await api.patch(`/accounts/${id}`, data);
      const idx = this.items.findIndex((a) => a.id === id);
      if (idx !== -1) this.items[idx] = account;
      return account;
    },
    async remove(id) {
      await api.delete(`/accounts/${id}`);
      this.items = this.items.filter((a) => a.id !== id);
    },
    testConnect(id) {
      return api.post(`/accounts/${id}/test-connect`);
    },
    refreshFolders(id) {
      return api.post(`/accounts/${id}/folders/refresh`);
    },
  },
});

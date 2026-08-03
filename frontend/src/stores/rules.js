import { defineStore } from "pinia";
import { api } from "@/api/client";

export const useRulesStore = defineStore("rules", {
  state: () => ({
    items: [],
    loaded: false,
    loading: false,
  }),
  actions: {
    async fetchAll() {
      this.loading = true;
      try {
        this.items = await api.get("/rules");
        this.loaded = true;
      } finally {
        this.loading = false;
      }
    },
    async create(data) {
      const rule = await api.post("/rules", data);
      this.items.push(rule);
      return rule;
    },
    async update(id, data) {
      const rule = await api.patch(`/rules/${id}`, data);
      const idx = this.items.findIndex((r) => r.id === id);
      if (idx !== -1) this.items[idx] = rule;
      return rule;
    },
    async remove(id) {
      await api.delete(`/rules/${id}`);
      this.items = this.items.filter((r) => r.id !== id);
    },
  },
});

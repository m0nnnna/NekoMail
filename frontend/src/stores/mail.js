import { defineStore } from "pinia";
import { api } from "@/api/client";

const PAGE_SIZE = 50;

export const useMailStore = defineStore("mail", {
  state: () => ({
    foldersByAccount: {}, // accountId -> Folder[]
    unreadCounts: {}, // folderId -> count

    view: { specialUse: "inbox" }, // { specialUse } | { accountId, folderId }

    messages: [],
    offset: 0,
    hasMore: true,
    loadingMessages: false,

    selectedIds: new Set(),

    openMessageId: null,
    openMessage: null,
    openMessageHtml: null,
    loadingOpenMessage: false,
  }),

  getters: {
    isSingleFolderView: (state) => !state.view.specialUse,
    selectedCount: (state) => state.selectedIds.size,
  },

  actions: {
    // --- Sidebar: folders + unread counts ---
    async loadSidebarFor(accountId) {
      const folders = await api.get(`/accounts/${accountId}/folders`);
      this.foldersByAccount = { ...this.foldersByAccount, [accountId]: folders };
      await this.refreshUnreadCounts(accountId);
    },
    async loadAllSidebars(accountIds) {
      await Promise.all(accountIds.map((id) => this.loadSidebarFor(id)));
    },
    async refreshUnreadCounts(accountId) {
      const counts = await api.get(`/accounts/${accountId}/unread-counts`);
      const folders = this.foldersByAccount[accountId] || [];
      const next = { ...this.unreadCounts };
      // The endpoint only returns folders with >0 unread -- zero out the
      // rest for this account first so a folder that just got read to zero
      // doesn't keep showing a stale badge.
      folders.forEach((f) => { next[f.id] = 0; });
      Object.assign(next, counts);
      this.unreadCounts = next;
    },

    // --- Message list (paged) ---
    setView(view) {
      this.view = view;
      this.messages = [];
      this.offset = 0;
      this.hasMore = true;
      this.selectedIds = new Set();
      this.closeMessage();
      this.loadMoreMessages();
    },
    async loadMoreMessages() {
      if (this.loadingMessages || !this.hasMore) return;
      this.loadingMessages = true;
      try {
        const params = new URLSearchParams();
        if (this.view.specialUse) params.set("special_use", this.view.specialUse);
        if (this.view.accountId) params.set("account_id", this.view.accountId);
        if (this.view.folderId) params.set("folder_id", this.view.folderId);
        params.set("limit", String(PAGE_SIZE));
        params.set("offset", String(this.offset));

        const page = await api.get(`/messages?${params.toString()}`);
        this.messages = this.offset === 0 ? page : [...this.messages, ...page];
        this.offset += page.length;
        this.hasMore = page.length === PAGE_SIZE;
      } finally {
        this.loadingMessages = false;
      }
    },

    // --- Selection ---
    toggleSelect(id) {
      if (this.selectedIds.has(id)) this.selectedIds.delete(id);
      else this.selectedIds.add(id);
    },
    selectAllLoaded() {
      this.messages.forEach((m) => this.selectedIds.add(m.id));
    },
    clearSelection() {
      this.selectedIds.clear();
    },

    // --- Reading pane ---
    async openMessageById(id) {
      this.openMessageId = id;
      this.openMessage = null;
      this.openMessageHtml = null;
      this.loadingOpenMessage = true;
      try {
        const [detail, htmlResp] = await Promise.all([
          api.get(`/messages/${id}`),
          api.get(`/messages/${id}/html`),
        ]);
        this.openMessage = detail;
        this.openMessageHtml = htmlResp.html;
        if (!detail.flags.includes("\\Seen")) {
          await this.markRead([id]);
        }
      } finally {
        this.loadingOpenMessage = false;
      }
    },
    closeMessage() {
      this.openMessageId = null;
      this.openMessage = null;
      this.openMessageHtml = null;
    },

    // --- Mutations ---
    _accountsOf(ids) {
      const idSet = new Set(ids);
      const accounts = new Set(this.messages.filter((m) => idSet.has(m.id)).map((m) => m.account_id));
      if (this.openMessage && idSet.has(this.openMessage.id)) accounts.add(this.openMessage.account_id);
      return [...accounts];
    },
    _applyFlagChange(ids, add, remove) {
      const idSet = new Set(ids);
      const apply = (flags) => {
        const current = new Set(flags);
        add.forEach((f) => current.add(f));
        remove.forEach((f) => current.delete(f));
        return [...current];
      };
      this.messages = this.messages.map((m) => (idSet.has(m.id) ? { ...m, flags: apply(m.flags) } : m));
      if (this.openMessage && idSet.has(this.openMessage.id)) {
        this.openMessage = { ...this.openMessage, flags: apply(this.openMessage.flags) };
      }
    },
    _removeFromList(ids) {
      const idSet = new Set(ids);
      this.messages = this.messages.filter((m) => !idSet.has(m.id));
      ids.forEach((id) => this.selectedIds.delete(id));
      if (this.openMessageId && idSet.has(this.openMessageId)) this.closeMessage();
    },

    async setFlags(ids, add = [], remove = []) {
      const accounts = this._accountsOf(ids);
      const result = await api.patch("/messages/flags", { message_ids: ids, add, remove });
      this._applyFlagChange(result.succeeded_ids, add, remove);
      if (add.includes("\\Seen") || remove.includes("\\Seen")) {
        await Promise.all(accounts.map((id) => this.refreshUnreadCounts(id)));
      }
      return result;
    },
    markRead(ids) { return this.setFlags(ids, ["\\Seen"], []); },
    markUnread(ids) { return this.setFlags(ids, [], ["\\Seen"]); },
    star(ids) { return this.setFlags(ids, ["\\Flagged"], []); },
    unstar(ids) { return this.setFlags(ids, [], ["\\Flagged"]); },

    async _moveAway(ids, apiCall) {
      const accounts = this._accountsOf(ids);
      const result = await apiCall();
      this._removeFromList(result.succeeded_ids);
      await Promise.all(accounts.map((id) => this.refreshUnreadCounts(id)));
      return result;
    },
    archive(ids) {
      return this._moveAway(ids, () => api.post("/messages/archive", { message_ids: ids }));
    },
    trash(ids) {
      return this._moveAway(ids, () => api.post("/messages/trash", { message_ids: ids }));
    },
    moveTo(ids, targetFolderId) {
      return this._moveAway(ids, () => api.post("/messages/move", { message_ids: ids, target_folder_id: targetFolderId }));
    },

    // --- Compose (send/draft-save land in Sent/Drafts via IMAP APPEND, not
    // through the poll/IDLE broadcast path -- refresh locally if we're
    // already looking at the folder they landed in). ---
    refreshIfViewing(accountId, folderId) {
      if (this.view.accountId !== accountId || this.view.folderId !== folderId) return;
      this.offset = 0;
      this.hasMore = true;
      this.messages = [];
      this.loadMoreMessages();
    },

    // --- WebSocket push ---
    handleWsEvent(event) {
      switch (event.type) {
        case "new_mail":
          this._handleNewMail(event);
          break;
        case "flags_changed":
          this._applyFlagChange(event.message_ids, event.add || [], event.remove || []);
          break;
        case "messages_moved":
          this._removeFromList(event.message_ids);
          break;
      }
    },
    _handleNewMail(event) {
      this.refreshUnreadCounts(event.account_id);

      const folders = this.foldersByAccount[event.account_id] || [];
      const folder = folders.find((f) => f.name === event.folder_name);
      let matches = false;
      if (this.view.specialUse) {
        matches = !!folder && folder.special_use === this.view.specialUse;
      } else if (this.view.accountId === event.account_id) {
        matches = !!folder && folder.id === this.view.folderId;
      }

      if (matches) {
        this.offset = 0;
        this.hasMore = true;
        this.messages = [];
        this.loadMoreMessages();
      }
    },
  },
});

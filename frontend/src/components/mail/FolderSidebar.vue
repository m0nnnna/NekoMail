<script setup>
import { computed, onMounted, reactive, watch } from "vue";
import { useRoute } from "vue-router";
import { useAccountsStore } from "@/stores/accounts";
import { useMailStore } from "@/stores/mail";
import { useComposeStore } from "@/stores/compose";

const emit = defineEmits(["navigate"]);

const accounts = useAccountsStore();
const mail = useMailStore();
const compose = useComposeStore();
const route = useRoute();

function startCompose() {
  const accountId = mail.view.accountId || accounts.items[0]?.id;
  if (accountId) compose.openNew(accountId);
}

const expanded = reactive({});

const SPECIAL_ORDER = ["inbox", "flagged", "sent", "drafts", "archive", "all", "junk", "trash"];
const ICONS = {
  inbox: "📥", sent: "📤", drafts: "📝", trash: "🗑️", junk: "🚫",
  archive: "🗄️", flagged: "⭐", important: "❗", all: "📚",
};

async function loadAll() {
  if (!accounts.loaded) await accounts.fetchAll();
  await mail.loadAllSidebars(accounts.items.map((a) => a.id));
  accounts.items.forEach((a) => {
    if (!(a.id in expanded)) expanded[a.id] = true;
  });
}

onMounted(loadAll);
watch(() => accounts.items.length, loadAll);

function sortedFolders(accountId) {
  const folders = mail.foldersByAccount[accountId] || [];
  return [...folders]
    .filter((f) => f.is_selectable)
    .sort((a, b) => {
      const rank = (f) => {
        const i = f.special_use ? SPECIAL_ORDER.indexOf(f.special_use) : -1;
        return i === -1 ? 999 : i;
      };
      const diff = rank(a) - rank(b);
      return diff !== 0 ? diff : a.name.localeCompare(b.name);
    });
}

function depthOf(folder) {
  if (!folder.delimiter) return 0;
  return Math.max(0, folder.name.split(folder.delimiter).length - 1);
}
function displayName(folder) {
  if (!folder.delimiter) return folder.name;
  const parts = folder.name.split(folder.delimiter);
  return parts[parts.length - 1];
}

const unifiedUnread = computed(() => {
  let total = 0;
  for (const accountId of Object.keys(mail.foldersByAccount)) {
    const inbox = mail.foldersByAccount[accountId].find((f) => f.special_use === "inbox");
    if (inbox) total += mail.unreadCounts[inbox.id] || 0;
  }
  return total;
});

const isUnifiedActive = computed(() => !route.params.accountId);
function isFolderActive(accountId, folderId) {
  return route.params.accountId === accountId && route.params.folderId === folderId;
}
</script>

<template>
  <nav class="sidebar" @click="emit('navigate')">
    <button type="button" class="compose-btn" :disabled="!accounts.items.length" @click.stop="startCompose">✏️ Compose</button>

    <RouterLink to="/mail" class="sidebar-item unified" :class="{ active: isUnifiedActive }">
      <span class="icon">📬</span>
      <span class="label">Unified Inbox</span>
      <span v-if="unifiedUnread" class="paw-badge">{{ unifiedUnread }}</span>
    </RouterLink>

    <div v-for="account in accounts.items" :key="account.id" class="account-group">
      <button type="button" class="account-header" @click.stop="expanded[account.id] = !expanded[account.id]">
        <span class="chevron" :class="{ open: expanded[account.id] }">▸</span>
        <span class="account-label">{{ account.label }}</span>
      </button>
      <ul v-show="expanded[account.id]" class="folder-list">
        <li v-for="folder in sortedFolders(account.id)" :key="folder.id">
          <RouterLink
            :to="`/mail/${account.id}/${folder.id}`"
            class="sidebar-item"
            :class="{ active: isFolderActive(account.id, folder.id) }"
            :style="{ paddingLeft: `${1 + depthOf(folder) * 0.9}rem` }"
          >
            <span class="icon">{{ ICONS[folder.special_use] || "📁" }}</span>
            <span class="label">{{ displayName(folder) }}</span>
            <span v-if="mail.unreadCounts[folder.id]" class="paw-badge">{{ mail.unreadCounts[folder.id] }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>
  </nav>
</template>

<style scoped>
.sidebar {
  height: 100%;
  overflow-y: auto;
  background: var(--bg-primary);
  border-right: 1px solid var(--border);
  padding: 0.75rem 0.5rem;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: var(--radius-sm);
  text-decoration: none;
  color: var(--text-primary);
  font-size: 0.9rem;
  white-space: nowrap;
  overflow: hidden;
}

.sidebar-item:hover {
  background: var(--bg-hover);
}

.sidebar-item.active {
  background: var(--accent);
  color: var(--accent-contrast);
}

.sidebar-item .label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
}

.compose-btn {
  width: 100%;
  margin-bottom: 0.75rem;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent-strong);
  color: var(--accent-contrast);
  padding: 0.55rem 0.75rem;
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  font-family: inherit;
}

.compose-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.unified {
  margin-bottom: 0.75rem;
  font-weight: 600;
}

.account-group {
  margin-bottom: 0.5rem;
}

.account-header {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0.4rem 0.5rem;
  cursor: pointer;
  font-family: inherit;
}

.chevron {
  transition: transform 0.15s;
  display: inline-block;
}

.chevron.open {
  transform: rotate(90deg);
}

.folder-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
</style>

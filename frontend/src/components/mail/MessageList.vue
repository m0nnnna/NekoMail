<script setup>
import { ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useMailStore } from "@/stores/mail";
import NIcon from "@/components/icons/NIcon.vue";
import VirtualList from "./VirtualList.vue";
import MessageRow from "./MessageRow.vue";
import MoveFolderPicker from "./MoveFolderPicker.vue";

const ROW_HEIGHT = 60;

const mail = useMailStore();
const router = useRouter();
const listRef = ref(null);
const movePickerOpen = ref(false);

watch(
  () => mail.view,
  () => listRef.value?.scrollToTop(),
);

function openMessage(message) {
  router.push(`/mail/${message.account_id}/${message.folder_id}/${message.id}`);
}
function toggleSelect(id) {
  mail.toggleSelect(id);
}
async function toggleStar(id) {
  const msg = mail.messages.find((m) => m.id === id);
  if (!msg) return;
  if (msg.flags.includes("\\Flagged")) await mail.unstar([id]);
  else await mail.star([id]);
}

function selectedIds() {
  return [...mail.selectedIds];
}

async function bulkMarkRead() { await mail.markRead(selectedIds()); }
async function bulkMarkUnread() { await mail.markUnread(selectedIds()); }
async function bulkStar() { await mail.star(selectedIds()); }
async function bulkUnstar() { await mail.unstar(selectedIds()); }
async function bulkArchive() { await mail.archive(selectedIds()); }
async function bulkTrash() { await mail.trash(selectedIds()); }
async function bulkMove(targetFolderId) {
  await mail.moveTo(selectedIds(), targetFolderId);
  movePickerOpen.value = false;
}
</script>

<template>
  <div class="message-list">
    <div v-if="mail.selectedCount > 0" class="bulk-toolbar">
      <span class="count">{{ mail.selectedCount }} selected</span>
      <button type="button" @click="mail.clearSelection()">Clear</button>
      <button type="button" @click="bulkMarkRead">Mark read</button>
      <button type="button" @click="bulkMarkUnread">Mark unread</button>
      <button type="button" @click="bulkStar">Star</button>
      <button type="button" @click="bulkUnstar">Unstar</button>
      <button type="button" @click="bulkArchive">Archive</button>
      <button type="button" class="danger" @click="bulkTrash">Delete</button>
      <button v-if="mail.isSingleFolderView" type="button" @click="movePickerOpen = true">Move to…</button>
    </div>
    <div v-else class="list-toolbar">
      <button type="button" @click="mail.selectAllLoaded()">Select all loaded</button>
    </div>

    <div v-if="movePickerOpen" class="popover-overlay" @click="movePickerOpen = false">
      <MoveFolderPicker :account-id="mail.view.accountId" :folder-id="mail.view.folderId" @select="bulkMove" @close="movePickerOpen = false" />
    </div>

    <div class="list-body">
      <VirtualList
        v-if="mail.messages.length"
        ref="listRef"
        :items="mail.messages"
        :item-height="ROW_HEIGHT"
        @scroll-end="mail.loadMoreMessages()"
      >
        <template #default="{ item }">
          <MessageRow
            :message="item"
            :selected="mail.selectedIds.has(item.id)"
            @open="openMessage"
            @toggle-select="toggleSelect"
            @toggle-star="toggleStar"
          />
        </template>
      </VirtualList>
      <div v-else-if="!mail.loadingMessages" class="empty-state">
        <p class="mascot"><NIcon name="cat" :size="40" /></p>
        <p>No mail here, nya~</p>
      </div>
      <div v-if="mail.loadingMessages" class="loading">Loading…</div>
    </div>
  </div>
</template>

<style scoped>
.message-list {
  height: 100%;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  min-width: 0;
}

.bulk-toolbar,
.list-toolbar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  background: var(--bg-elevated);
  flex-wrap: wrap;
}

.bulk-toolbar button,
.list-toolbar button {
  border: 1px solid var(--border);
  background: var(--bg-primary);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
  padding: 0.3rem 0.6rem;
  cursor: pointer;
  font-size: 0.8rem;
  font-family: inherit;
}

.bulk-toolbar .danger {
  color: var(--danger);
  border-color: var(--danger);
}

.bulk-toolbar .count {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-right: 0.25rem;
}

.list-body {
  flex: 1;
  min-height: 0;
  position: relative;
}

.empty-state,
.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
  gap: 0.25rem;
  text-align: center;
}

.mascot {
  font-size: 2rem;
  margin: 0;
}

.popover-overlay {
  position: fixed;
  inset: 0;
  z-index: 30;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 4rem;
  background: rgba(0, 0, 0, 0.15);
}
</style>

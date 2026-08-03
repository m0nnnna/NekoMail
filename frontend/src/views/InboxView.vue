<script setup>
import { ref, watch } from "vue";
import { useRoute } from "vue-router";
import { useMailStore } from "@/stores/mail";
import FolderSidebar from "@/components/mail/FolderSidebar.vue";
import MessageList from "@/components/mail/MessageList.vue";
import ReadingPane from "@/components/mail/ReadingPane.vue";

const route = useRoute();
const mail = useMailStore();
const sidebarOpen = ref(false);

function syncViewFromRoute() {
  const { accountId, folderId, messageId } = route.params;
  const desired = accountId && folderId ? { accountId, folderId } : { specialUse: "inbox" };
  const sameView =
    desired.specialUse === mail.view.specialUse &&
    desired.accountId === mail.view.accountId &&
    desired.folderId === mail.view.folderId;
  if (!sameView) {
    mail.setView(desired);
  }

  if (messageId) {
    if (String(mail.openMessageId) !== String(messageId)) {
      mail.openMessageById(Number(messageId));
    }
  } else if (mail.openMessageId) {
    mail.closeMessage();
  }
}

watch(
  () => [route.params.accountId, route.params.folderId, route.params.messageId],
  syncViewFromRoute,
  { immediate: true },
);
</script>

<template>
  <div class="mail-shell" :class="{ 'has-open-message': !!mail.openMessageId }">
    <button type="button" class="hamburger" @click="sidebarOpen = !sidebarOpen">☰</button>
    <FolderSidebar class="pane-sidebar" :class="{ open: sidebarOpen }" @navigate="sidebarOpen = false" />
    <MessageList class="pane-list" />
    <ReadingPane class="pane-reading" />
  </div>
</template>

<style scoped>
.mail-shell {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 240px 380px 1fr;
  position: relative;
}

.hamburger {
  display: none;
  position: absolute;
  top: 0.5rem;
  left: 0.5rem;
  z-index: 25;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  border-radius: var(--radius-sm);
  padding: 0.35rem 0.6rem;
  cursor: pointer;
}

@media (max-width: 900px) {
  .mail-shell {
    grid-template-columns: 1fr;
  }

  .hamburger {
    display: block;
  }

  .pane-sidebar {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    width: 78%;
    max-width: 300px;
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    z-index: 20;
    box-shadow: var(--shadow-soft);
  }

  .pane-sidebar.open {
    transform: translateX(0);
  }

  .pane-list,
  .pane-reading {
    grid-column: 1;
    grid-row: 1;
  }

  .has-open-message .pane-list {
    display: none;
  }

  .mail-shell:not(.has-open-message) .pane-reading {
    display: none;
  }
}
</style>

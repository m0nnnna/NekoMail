<script setup>
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { useMailStore } from "@/stores/mail";
import { useComposeStore } from "@/stores/compose";
import { usePgpStore } from "@/stores/pgp";
import { rewriteCidLinks, sanitizeEmailHtml } from "@/utils/sanitizeHtml";
import { decryptPgpMessage } from "@/utils/pgpMime";
import { api } from "@/api/client";
import NIcon from "@/components/icons/NIcon.vue";
import MoveFolderPicker from "./MoveFolderPicker.vue";

const mail = useMailStore();
const compose = useComposeStore();
const pgp = usePgpStore();
const router = useRouter();
const movePickerOpen = ref(false);

const message = computed(() => mail.openMessage);
const isDraftFolder = computed(() => {
  if (!message.value) return false;
  const folders = mail.foldersByAccount[message.value.account_id] || [];
  const folder = folders.find((f) => f.id === message.value.folder_id);
  return folder?.special_use === "drafts";
});
const srcdoc = computed(() => {
  if (!message.value || !mail.openMessageHtml) return null;
  const rewritten = rewriteCidLinks(mail.openMessageHtml, message.value.id, message.value.attachments);
  return sanitizeEmailHtml(rewritten);
});

// --- PGP decrypt ---
const decrypted = ref(null); // { bodyText, attachments, verified }
const decryptError = ref("");
const decryptPassphrase = ref("");
const decrypting = ref(false);

watch(message, () => {
  decrypted.value = null;
  decryptError.value = "";
  if (message.value?.is_encrypted) pgp.init();
});

async function doDecrypt() {
  if (!message.value) return;
  decryptError.value = "";
  if (!pgp.isUnlocked) {
    if (!decryptPassphrase.value) {
      decryptError.value = "Enter your PGP passphrase.";
      return;
    }
    try {
      await pgp.unlock(decryptPassphrase.value);
      decryptPassphrase.value = "";
    } catch {
      decryptError.value = "Wrong passphrase.";
      return;
    }
  }

  decrypting.value = true;
  try {
    const { ciphertext } = await api.get(`/messages/${message.value.id}/pgp`);
    if (!ciphertext) {
      decryptError.value = "No PGP content found in this message.";
      return;
    }
    let senderPublicKeyArmored = null;
    const senderEmail = message.value.from_addrs?.[0]?.email;
    if (senderEmail) {
      try {
        const contact = await api.get(`/contacts/lookup?email=${encodeURIComponent(senderEmail)}`);
        senderPublicKeyArmored = contact.pgp_public_key || null;
      } catch {
        // unknown sender -- decrypt still proceeds, just without signature verification
      }
    }
    decrypted.value = await decryptPgpMessage({ armoredCiphertext: ciphertext, privateKey: pgp.unlockedPrivateKey, senderPublicKeyArmored });
  } catch (e) {
    decryptError.value = e.message || "Decryption failed.";
  } finally {
    decrypting.value = false;
  }
}

function downloadDecryptedAttachment(att) {
  const url = URL.createObjectURL(att.blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = att.filename;
  a.click();
  URL.revokeObjectURL(url);
}

function fmtAddr(a) {
  if (!a) return "";
  return a.name ? `${a.name} <${a.email}>` : a.email;
}
function fmtDate(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString();
}
function attachmentUrl(att) {
  return `/api/messages/${message.value.id}/attachments/${att.id}`;
}

function goBack() {
  router.back();
}
async function toggleRead() {
  if (message.value.flags.includes("\\Seen")) await mail.markUnread([message.value.id]);
  else await mail.markRead([message.value.id]);
}
async function toggleStar() {
  if (message.value.flags.includes("\\Flagged")) await mail.unstar([message.value.id]);
  else await mail.star([message.value.id]);
}
async function doArchive() {
  await mail.archive([message.value.id]);
}
async function doTrash() {
  await mail.trash([message.value.id]);
}
async function doMove(folderId) {
  await mail.moveTo([message.value.id], folderId);
  movePickerOpen.value = false;
}
</script>

<template>
  <div v-if="mail.openMessageId" class="reading-pane">
    <div v-if="mail.loadingOpenMessage" class="empty-state">Loading…</div>
    <template v-else-if="message">
      <div class="pane-toolbar">
        <button type="button" class="icon-btn" @click="goBack"><NIcon name="back" :size="14" only /> Back</button>
        <template v-if="isDraftFolder">
          <button type="button" class="icon-btn" @click="compose.openDraft(message)">Continue editing</button>
        </template>
        <template v-else>
          <button type="button" class="icon-btn" @click="compose.openReply(message, 'reply')"><NIcon name="reply" :size="14" only /> Reply</button>
          <button type="button" class="icon-btn" @click="compose.openReply(message, 'reply_all')"><NIcon name="replyall" :size="14" only /> Reply All</button>
          <button type="button" class="icon-btn" @click="compose.openForward(message)"><NIcon name="forward" :size="14" only /> Forward</button>
        </template>
        <div class="spacer" />
        <button type="button" class="icon-btn" @click="toggleRead">
          <NIcon :name="message.flags.includes('\\Seen') ? 'mailbox' : 'mailopen'" :size="14" only />
          {{ message.flags.includes('\\Seen') ? "Mark unread" : "Mark read" }}
        </button>
        <button type="button" class="icon-btn" @click="toggleStar">
          <NIcon name="star" :size="14" only :filled="message.flags.includes('\\Flagged')" />
          {{ message.flags.includes('\\Flagged') ? "Unstar" : "Star" }}
        </button>
        <button type="button" class="icon-btn" @click="doArchive"><NIcon name="archive" :size="14" only /> Archive</button>
        <button type="button" class="icon-btn danger" @click="doTrash"><NIcon name="trash" :size="14" only /> Delete</button>
        <button v-if="mail.isSingleFolderView" type="button" class="icon-btn" @click="movePickerOpen = true"><NIcon name="move" :size="14" only /> Move to…</button>
      </div>

      <div v-if="movePickerOpen" class="popover-overlay" @click="movePickerOpen = false">
        <MoveFolderPicker :account-id="mail.view.accountId" :folder-id="mail.view.folderId" @select="doMove" @close="movePickerOpen = false" />
      </div>

      <header class="msg-header">
        <h2>{{ message.subject || "(no subject)" }}</h2>
        <p class="from">{{ fmtAddr(message.from_addrs[0]) }}</p>
        <p class="to">To: {{ message.to_addrs.map(fmtAddr).join(", ") }}</p>
        <p v-if="message.cc_addrs?.length" class="cc">Cc: {{ message.cc_addrs.map(fmtAddr).join(", ") }}</p>
        <p class="date">{{ fmtDate(message.date) }}</p>
      </header>

      <div v-if="!message.is_encrypted && message.attachments.length" class="attachments">
        <a v-for="att in message.attachments" :key="att.id" :href="attachmentUrl(att)" target="_blank" class="attachment-chip">
          <NIcon name="attach" :size="14" /> {{ att.filename || "attachment" }}
        </a>
      </div>

      <template v-if="message.is_encrypted">
        <!-- message.attachments here would just be PGP/MIME's own structural
             parts (the version-marker + ciphertext blob) -- meaningless to
             show; the real attachments only exist post-decryption below. -->

        <div v-if="!decrypted" class="pgp-panel">
          <p class="pgp-locked"><NIcon name="lock" :size="15" /> This message is PGP-encrypted.</p>
          <div v-if="!pgp.isUnlocked" class="unlock-row">
            <input v-model="decryptPassphrase" type="password" placeholder="Your PGP passphrase" @keyup.enter="doDecrypt" />
          </div>
          <button type="button" class="icon-btn" :disabled="decrypting" @click="doDecrypt">{{ decrypting ? "Decrypting…" : "Decrypt" }}</button>
          <p v-if="decryptError" class="pgp-error">{{ decryptError }}</p>
        </div>
        <template v-else>
          <p class="pgp-status" :class="{ verified: decrypted.verified === true, unverified: decrypted.verified === false }">
            <template v-if="decrypted.verified === true"><NIcon name="check" :size="14" /> Signature verified</template>
            <template v-else-if="decrypted.verified === false"><NIcon name="warn" :size="14" /> Signature verification failed</template>
            <template v-else><NIcon name="unlock" :size="14" /> Decrypted (sender's key unknown — signature not checked)</template>
          </p>
          <div v-if="decrypted.attachments.length" class="attachments">
            <button v-for="(att, i) in decrypted.attachments" :key="i" type="button" class="attachment-chip" @click="downloadDecryptedAttachment(att)">
              <NIcon name="attach" :size="14" /> {{ att.filename }}
            </button>
          </div>
          <pre class="body-text">{{ decrypted.bodyText || "(no content)" }}</pre>
        </template>
      </template>
      <template v-else>
        <iframe v-if="srcdoc" class="body-frame" sandbox="allow-same-origin allow-popups" :srcdoc="srcdoc" />
        <pre v-else class="body-text">{{ message.body_text || "(no content)" }}</pre>
      </template>
    </template>
  </div>
  <div v-else class="reading-pane empty-state">
    <p class="mascot"><NIcon name="cat" :size="40" /></p>
    <p>Select a message to read it, nya~</p>
  </div>
</template>

<style scoped>
.reading-pane {
  height: 100%;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-primary);
}

.pane-toolbar {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 0.75rem;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}

.icon-btn {
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
  padding: 0.35rem 0.65rem;
  cursor: pointer;
  font-size: 0.8rem;
  font-family: inherit;
}

.icon-btn.danger {
  color: var(--danger);
  border-color: var(--danger);
}

.spacer {
  flex: 1;
}

.msg-header {
  padding: 0.75rem 1rem 0.5rem;
  border-bottom: 1px solid var(--border);
}

.msg-header h2 {
  margin: 0 0 0.35rem;
  font-size: 1.1rem;
}

.msg-header p {
  margin: 0.1rem 0;
  font-size: 0.82rem;
  color: var(--text-secondary);
}

.attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--border);
}

.attachment-chip {
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  border-radius: var(--radius-sm);
  padding: 0.3rem 0.6rem;
  font-size: 0.8rem;
  color: var(--text-primary);
  text-decoration: none;
}

.body-frame {
  flex: 1;
  min-height: 0;
  margin: 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: #fff;
  box-shadow: var(--shadow-soft);
}

.body-text {
  flex: 1;
  margin: 0;
  padding: 1rem;
  white-space: pre-wrap;
  overflow-y: auto;
  font-family: inherit;
  font-size: 0.9rem;
}

.pgp-panel {
  margin: 0.75rem 1rem;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  align-items: flex-start;
}

.pgp-locked {
  margin: 0;
  font-size: 0.9rem;
}

.unlock-row {
  width: 100%;
}

.unlock-row input {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.5rem;
  font-family: inherit;
  font-size: 0.85rem;
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.pgp-error {
  margin: 0;
  font-size: 0.8rem;
  color: var(--danger);
}

.pgp-status {
  margin: 0.6rem 1rem 0;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.pgp-status.verified {
  color: var(--success);
}

.pgp-status.unverified {
  color: var(--danger);
}

.empty-state {
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

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import * as openpgp from "openpgp";
import { useComposeStore } from "@/stores/compose";
import { useAccountsStore } from "@/stores/accounts";
import { useMailStore } from "@/stores/mail";
import { usePgpStore } from "@/stores/pgp";
import { api } from "@/api/client";
import NIcon from "@/components/icons/NIcon.vue";
import { buildEncryptedMime } from "@/utils/pgpMime";

const AUTOSAVE_INTERVAL_MS = 20000;

const compose = useComposeStore();
const accounts = useAccountsStore();
const mail = useMailStore();
const pgp = usePgpStore();

const form = reactive({ ...compose.draft });
const draftId = ref(form.draftId);
const showCcBcc = ref(!!(form.cc || form.bcc));
const sending = ref(false);
const savingDraft = ref(false);
const error = ref("");
let dirty = false;

// --- PGP encrypt toggle ---
const encrypt = ref(false);
const encryptPassphrase = ref("");
const recipientKeys = reactive({}); // email -> armored public key, or null once confirmed missing
const checkingKeys = ref(false);

function parseEmails(raw) {
  if (!raw) return [];
  return raw
    .split(",")
    .map((s) => {
      const m = s.trim().match(/<([^>]+)>/);
      return (m ? m[1] : s.trim()).toLowerCase();
    })
    .filter(Boolean);
}

const recipientEmails = computed(() => [...new Set([...parseEmails(form.to), ...parseEmails(form.cc)])]);
const missingKeyRecipients = computed(() => recipientEmails.value.filter((e) => !recipientKeys[e]));

async function checkRecipientKeys() {
  checkingKeys.value = true;
  try {
    await Promise.all(
      recipientEmails.value.map(async (email) => {
        if (email in recipientKeys) return;
        try {
          const contact = await api.get(`/contacts/lookup?email=${encodeURIComponent(email)}`);
          recipientKeys[email] = contact.pgp_public_key || null;
        } catch {
          recipientKeys[email] = null;
        }
      }),
    );
  } finally {
    checkingKeys.value = false;
  }
}

watch(encrypt, (on) => {
  if (on) checkRecipientKeys();
});
watch([() => form.to, () => form.cc], () => {
  if (encrypt.value) checkRecipientKeys();
});

watch(
  () => compose.draft,
  (d) => {
    if (!d) return;
    Object.assign(form, d);
    draftId.value = d.draftId;
    showCcBcc.value = !!(d.cc || d.bcc);
    dirty = false;
    error.value = "";
  },
);

function markDirty() {
  dirty = true;
}

function hasContent() {
  return !!(form.to.trim() || form.subject.trim() || form.bodyText.trim() || form.attachments.length);
}

async function buildEncryptedMessage() {
  if (!pgp.isUnlocked) throw new Error("Unlock your PGP key first.");
  await checkRecipientKeys();
  if (missingKeyRecipients.value.length) {
    throw new Error(`Missing public key for: ${missingKeyRecipients.value.join(", ")}`);
  }
  const account = accounts.items.find((a) => a.id === form.accountId);
  const recipientPublicKeys = await Promise.all(
    recipientEmails.value.map((e) => openpgp.readKey({ armoredKey: recipientKeys[e] })),
  );
  return buildEncryptedMime({
    fromEmail: account.email_address, fromName: account.label,
    to: form.to, cc: form.cc, subject: form.subject, messageId: `<${crypto.randomUUID()}@nekomail>`,
    inReplyTo: null, references: null,
    bodyText: form.bodyText, attachments: form.attachments,
    recipientPublicKeys, ownPublicKeyArmored: pgp.publicKeyArmored, signingPrivateKey: pgp.unlockedPrivateKey,
  });
}

async function toFormData() {
  const fd = new FormData();
  fd.set("account_id", form.accountId);
  fd.set("to", form.to);
  fd.set("cc", form.cc);
  if (form.inReplyToMessageId) fd.set("in_reply_to_message_id", form.inReplyToMessageId);
  if (draftId.value) fd.set("draft_id", draftId.value);

  if (encrypt.value) {
    // Built entirely in the browser -- the backend only ever sees these
    // already-encrypted bytes, never the plaintext (see
    // services/mail/compose.py's raw_mime path). Bcc is unsupported here:
    // a blind recipient would need their own separately-encrypted copy,
    // which this version doesn't build (see utils/pgpMime.js).
    fd.set("raw_mime", await buildEncryptedMessage());
  } else {
    fd.set("bcc", form.bcc);
    fd.set("subject", form.subject);
    fd.set("body_text", form.bodyText);
    form.attachments.forEach((f) => fd.append("attachments", f));
  }
  return fd;
}

async function ensureUnlockedForEncrypt() {
  if (!encrypt.value || pgp.isUnlocked) return true;
  if (!encryptPassphrase.value) {
    error.value = "Enter your PGP passphrase to encrypt.";
    return false;
  }
  try {
    await pgp.unlock(encryptPassphrase.value);
    encryptPassphrase.value = "";
    return true;
  } catch {
    error.value = "Wrong passphrase.";
    return false;
  }
}

async function doSaveDraft({ silent = false } = {}) {
  if (!form.accountId || !hasContent()) return;
  if (encrypt.value && !pgp.isUnlocked) {
    if (silent) return; // never interrupt a background autosave tick for a passphrase
    if (!(await ensureUnlockedForEncrypt())) return;
  }
  if (!silent) savingDraft.value = true;
  try {
    const saved = await api.postForm("/messages/draft", await toFormData());
    draftId.value = saved.id;
    dirty = false;
    mail.refreshIfViewing(saved.account_id, saved.folder_id);
  } catch (e) {
    if (!silent) error.value = e.message;
  } finally {
    if (!silent) savingDraft.value = false;
  }
}

async function doSend() {
  if (!form.to.trim()) {
    error.value = "Add at least one recipient.";
    return;
  }
  error.value = "";
  if (!(await ensureUnlockedForEncrypt())) return;
  sending.value = true;
  try {
    await api.postForm("/messages/send", await toFormData());
    dirty = false;
    // A send can change the current view's contents two ways: the sent copy
    // lands in Sent, and (if this was replying from/editing a draft) the
    // draft it replaced disappears from Drafts -- just reload whatever
    // folder is currently open rather than tracking both cases separately.
    mail.refreshIfViewing(mail.view.accountId, mail.view.folderId);
    compose.close();
  } catch (e) {
    error.value = e.message;
  } finally {
    sending.value = false;
  }
}

async function discard() {
  dirty = false;
  const idToTrash = draftId.value;
  compose.close();
  if (idToTrash) {
    try {
      await mail.trash([idToTrash]);
    } catch {
      // best-effort -- the draft just stays in Drafts if this fails
    }
  }
}

async function close() {
  if (dirty && hasContent()) {
    await doSaveDraft({ silent: true });
    mail.refreshIfViewing(mail.view.accountId, mail.view.folderId);
  }
  compose.close();
}

function addFiles(e) {
  const files = Array.from(e.target.files || []);
  form.attachments = [...form.attachments, ...files];
  e.target.value = "";
  markDirty();
}
function removeFile(idx) {
  form.attachments.splice(idx, 1);
  markDirty();
}

onMounted(() => pgp.init());

const autosaveTimer = setInterval(() => {
  if (dirty && hasContent()) doSaveDraft({ silent: true });
}, AUTOSAVE_INTERVAL_MS);
onBeforeUnmount(() => clearInterval(autosaveTimer));
</script>

<template>
  <div class="compose-backdrop" @click.self="close">
    <div class="compose-panel">
      <div class="compose-header">
        <span>{{ form.inReplyToMessageId ? "Reply" : draftId ? "Edit draft" : "New message" }}</span>
        <div class="spacer" />
        <button type="button" class="icon-btn" @click="close"><NIcon name="close" :size="14" /></button>
      </div>

      <div class="compose-body">
        <div class="field">
          <label>From</label>
          <select v-model="form.accountId" @change="markDirty">
            <option v-for="a in accounts.items" :key="a.id" :value="a.id">{{ a.label }} &lt;{{ a.email_address }}&gt;</option>
          </select>
        </div>
        <div class="field">
          <label>To</label>
          <input v-model="form.to" type="text" placeholder="name@example.com, ..." @input="markDirty" />
        </div>
        <button type="button" class="cc-toggle" @click="showCcBcc = !showCcBcc">{{ showCcBcc ? "Hide" : "Add" }} Cc/Bcc</button>
        <template v-if="showCcBcc">
          <div class="field"><label>Cc</label><input v-model="form.cc" type="text" @input="markDirty" /></div>
          <div v-if="!encrypt" class="field"><label>Bcc</label><input v-model="form.bcc" type="text" @input="markDirty" /></div>
        </template>
        <div class="field">
          <label>Subject</label>
          <input v-model="form.subject" type="text" @input="markDirty" />
        </div>
        <textarea v-model="form.bodyText" class="body-input" @input="markDirty" />

        <p v-if="form.hadServerAttachments && !form.attachments.length" class="hint">
          This draft's original attachments weren't reloaded — re-attach them below if you still need them.
        </p>

        <div class="attachments">
          <span v-for="(f, i) in form.attachments" :key="i" class="attachment-chip">
            <NIcon name="attach" :size="14" /> {{ f.name }}
            <button type="button" @click="removeFile(i)"><NIcon name="close" :size="11" /></button>
          </span>
          <label class="attach-btn">
            + Attach
            <input type="file" multiple hidden @change="addFiles" />
          </label>
        </div>

        <div v-if="pgp.hasKeypair" class="pgp-row">
          <label class="encrypt-toggle">
            <input v-model="encrypt" type="checkbox" @change="markDirty" />
            <NIcon name="lock" :size="14" /> Encrypt with PGP (Bcc disabled while on)
          </label>
          <p v-if="encrypt && checkingKeys" class="hint">Checking recipient keys…</p>
          <p v-else-if="encrypt && missingKeyRecipients.length" class="warning">
            No public key on file for: {{ missingKeyRecipients.join(", ") }} — add it under PGP first.
          </p>
          <p v-else-if="encrypt && recipientEmails.length" class="hint ok"><NIcon name="lock" :size="13" /> All recipients have a key. Also encrypted to yourself, so your Sent copy stays readable.</p>
          <div v-if="encrypt && !pgp.isUnlocked" class="unlock-row">
            <input v-model="encryptPassphrase" type="password" placeholder="Your PGP passphrase" @keyup.enter="ensureUnlockedForEncrypt" />
          </div>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
      </div>

      <div class="compose-footer">
        <button type="button" class="send-btn" :disabled="sending" @click="doSend">{{ sending ? "Sending…" : "Send" }}</button>
        <button type="button" class="icon-btn" :disabled="savingDraft" @click="doSaveDraft()">{{ savingDraft ? "Saving…" : "Save draft" }}</button>
        <div class="spacer" />
        <button type="button" class="icon-btn danger" @click="discard">Discard</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.compose-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  align-items: flex-end;
  justify-content: flex-end;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.15);
}

.compose-panel {
  width: 480px;
  max-width: 100%;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-soft);
  overflow: hidden;
}

.compose-header {
  display: flex;
  align-items: center;
  padding: 0.6rem 0.85rem;
  background: var(--accent);
  color: var(--accent-contrast);
  font-weight: 600;
  font-size: 0.9rem;
}

.compose-header .icon-btn {
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 1rem;
  padding: 0.1rem 0.4rem;
}

.compose-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 0.75rem 0.85rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.field label {
  font-size: 0.72rem;
  text-transform: uppercase;
  color: var(--text-secondary);
  letter-spacing: 0.02em;
}

.field input,
.field select {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.5rem;
  font-family: inherit;
  font-size: 0.85rem;
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.cc-toggle {
  align-self: flex-start;
  background: none;
  border: none;
  color: var(--accent-strong);
  font-size: 0.75rem;
  cursor: pointer;
  padding: 0;
  font-family: inherit;
}

.body-input {
  flex: 1;
  min-height: 180px;
  resize: vertical;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.6rem;
  font-family: inherit;
  font-size: 0.85rem;
  background: var(--bg-elevated);
  color: var(--text-primary);
}

.hint {
  margin: 0;
  font-size: 0.75rem;
  color: var(--warning);
}

.error {
  margin: 0;
  font-size: 0.8rem;
  color: var(--danger);
}

.pgp-row {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.5rem 0.6rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.encrypt-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  cursor: pointer;
}

.warning {
  margin: 0;
  font-size: 0.75rem;
  color: var(--danger);
}

.hint.ok {
  color: var(--success);
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

.attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  align-items: center;
}

.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  border-radius: var(--radius-sm);
  padding: 0.25rem 0.5rem;
  font-size: 0.78rem;
}

.attachment-chip button {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-secondary);
  padding: 0;
  font-size: 0.75rem;
}

.attach-btn {
  border: 1px dashed var(--border);
  border-radius: var(--radius-sm);
  padding: 0.25rem 0.6rem;
  font-size: 0.78rem;
  cursor: pointer;
  color: var(--text-secondary);
}

.compose-footer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 0.85rem;
  border-top: 1px solid var(--border);
}

.icon-btn {
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.7rem;
  cursor: pointer;
  font-size: 0.82rem;
  font-family: inherit;
}

.icon-btn.danger {
  color: var(--danger);
  border-color: var(--danger);
}

.send-btn {
  border: none;
  background: var(--accent-strong);
  color: var(--accent-contrast);
  border-radius: var(--radius-sm);
  padding: 0.45rem 1rem;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 600;
  font-family: inherit;
}

.send-btn:disabled,
.compose-footer .icon-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.spacer {
  flex: 1;
}
</style>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAccountsStore } from "@/stores/accounts";

const accounts = useAccountsStore();
const route = useRoute();
const router = useRouter();

const showForm = ref(false);
const editingId = ref(null);
const errorMsg = ref("");
const testResults = reactive({});
const busy = reactive({});
const linkBanner = ref(null); // { type: "success" | "error", text }

const editingAccount = computed(() => accounts.items.find((a) => a.id === editingId.value) || null);
const isOauthEdit = computed(() => editingAccount.value?.auth_type === "oauth_outlook");

const SECURITY_MODES = ["ssl", "starttls", "none"];

function blankForm() {
  return {
    label: "", email_address: "",
    imap_host: "", imap_port: 993, imap_security: "ssl", imap_username: "", imap_password: "",
    smtp_host: "", smtp_port: 587, smtp_security: "starttls", smtp_username: "", smtp_password: "",
    verify_ssl: true, auto_saves_sent: false,
  };
}
const form = reactive(blankForm());

onMounted(async () => {
  if (!accounts.loaded) await accounts.fetchAll();

  // The OAuth callback (routers/oauth.py) redirects back here as a plain
  // browser navigation with a query param -- not a store action -- since
  // it's Microsoft's server doing the redirect, not our SPA.
  if (route.query.outlook_linked) {
    linkBanner.value = { type: "success", text: "Outlook account linked!" };
    await accounts.fetchAll();
    router.replace({ query: {} });
  } else if (route.query.outlook_error) {
    linkBanner.value = { type: "error", text: route.query.outlook_error };
    router.replace({ query: {} });
  }
});

function startAdd() {
  Object.assign(form, blankForm());
  editingId.value = null;
  errorMsg.value = "";
  showForm.value = true;
}
function startEdit(account) {
  Object.assign(form, {
    label: account.label, email_address: account.email_address,
    imap_host: account.imap_host, imap_port: account.imap_port, imap_security: account.imap_security,
    imap_username: account.imap_username, imap_password: "",
    smtp_host: account.smtp_host, smtp_port: account.smtp_port, smtp_security: account.smtp_security,
    smtp_username: account.smtp_username, smtp_password: "",
    verify_ssl: account.verify_ssl, auto_saves_sent: account.auto_saves_sent,
  });
  editingId.value = account.id;
  errorMsg.value = "";
  showForm.value = true;
}
function cancelForm() {
  showForm.value = false;
  editingId.value = null;
  errorMsg.value = "";
}

async function submitForm() {
  errorMsg.value = "";
  try {
    if (editingId.value) {
      let payload;
      if (isOauthEdit.value) {
        // Connection details are fixed by the OAuth link itself (host/port/
        // security/username are Outlook constants, auth is the stored
        // refresh token) -- only these fields mean anything to change.
        payload = { label: form.label, email_address: form.email_address, verify_ssl: form.verify_ssl, auto_saves_sent: form.auto_saves_sent };
      } else {
        payload = { ...form };
        // Blank password fields on an edit mean "leave unchanged".
        if (!payload.imap_password) delete payload.imap_password;
        if (!payload.smtp_password) delete payload.smtp_password;
      }
      await accounts.update(editingId.value, payload);
    } else {
      await accounts.create({ ...form });
    }
    cancelForm();
  } catch (err) {
    errorMsg.value = err.detail || err.message || "Save failed";
  }
}

async function doTestConnect(id) {
  busy[id] = true;
  try {
    testResults[id] = await accounts.testConnect(id);
  } catch (err) {
    const detail = err.detail || err.message || "Connection check failed";
    testResults[id] = { imap: { ok: false, detail }, smtp: { ok: false, detail } };
  } finally {
    busy[id] = false;
  }
}
async function doRefreshFolders(id) {
  busy[id] = true;
  try {
    await accounts.refreshFolders(id);
  } finally {
    busy[id] = false;
  }
}
async function doDelete(account) {
  if (!confirm(`Remove account "${account.label}"? This deletes all locally synced mail for it.`)) return;
  await accounts.remove(account.id);
}
async function toggleActive(account) {
  await accounts.update(account.id, { is_active: !account.is_active });
}
</script>

<template>
  <div class="accounts-view">
    <div class="header-row">
      <h1>Mail accounts</h1>
      <div class="header-actions">
        <a class="btn-link" href="/api/accounts/oauth/outlook/start">Link Outlook Account</a>
        <button type="button" class="primary" @click="startAdd">+ Add account</button>
      </div>
    </div>

    <div v-if="linkBanner" class="banner" :class="linkBanner.type">
      <span>{{ linkBanner.text }}</span>
      <button type="button" class="dismiss" @click="linkBanner = null">✕</button>
    </div>

    <p v-if="accounts.loading && !accounts.loaded" class="hint">Loading…</p>
    <p v-else-if="accounts.loaded && accounts.items.length === 0" class="hint">
      No accounts yet — add one to start syncing mail.
    </p>

    <ul class="account-list">
      <li v-for="account in accounts.items" :key="account.id" class="account-card">
        <div class="card-row">
          <div class="card-main">
            <strong>{{ account.label }}</strong>
            <span class="muted">{{ account.email_address }}</span>
            <span v-if="!account.is_active" class="pill">inactive</span>
            <span v-if="account.auth_type === 'oauth_outlook'" class="pill oauth">Outlook (OAuth)</span>
          </div>
          <div class="card-actions">
            <button type="button" :disabled="busy[account.id]" @click="doTestConnect(account.id)">Test connect</button>
            <button type="button" :disabled="busy[account.id]" @click="doRefreshFolders(account.id)">Refresh folders</button>
            <button type="button" @click="toggleActive(account)">{{ account.is_active ? "Deactivate" : "Activate" }}</button>
            <button type="button" @click="startEdit(account)">Edit</button>
            <button type="button" class="danger" @click="doDelete(account)">Delete</button>
          </div>
        </div>
        <div v-if="testResults[account.id]" class="test-result">
          <span :class="testResults[account.id].imap.ok ? 'ok' : 'fail'">IMAP: {{ testResults[account.id].imap.detail }}</span>
          <span :class="testResults[account.id].smtp.ok ? 'ok' : 'fail'">SMTP: {{ testResults[account.id].smtp.detail }}</span>
        </div>
      </li>
    </ul>

    <div v-if="showForm" class="form-overlay" @click.self="cancelForm">
      <form class="account-form" @submit.prevent="submitForm">
        <h2>{{ editingId ? "Edit account" : "Add account" }}</h2>
        <p v-if="errorMsg" class="error">{{ errorMsg }}</p>

        <div class="field-grid">
          <label>Label <input v-model="form.label" required maxlength="128" /></label>
          <label>Email address <input v-model="form.email_address" type="email" required /></label>
        </div>

        <p v-if="isOauthEdit" class="hint">
          Connection details are managed by the Outlook OAuth link ({{ form.imap_host }} / {{ form.smtp_host }}) and aren't editable here — unlink and re-link via "Delete" + "Link Outlook Account" if you need to change the linked mailbox.
        </p>

        <fieldset v-if="!isOauthEdit">
          <legend>IMAP</legend>
          <div class="field-grid">
            <label>Host <input v-model="form.imap_host" required /></label>
            <label>Port <input v-model.number="form.imap_port" type="number" required /></label>
            <label>Security
              <select v-model="form.imap_security">
                <option v-for="m in SECURITY_MODES" :key="m" :value="m">{{ m }}</option>
              </select>
            </label>
            <label>Username <input v-model="form.imap_username" required /></label>
            <label>
              Password
              <input v-model="form.imap_password" type="password" :placeholder="editingId ? '(unchanged)' : ''" :required="!editingId" />
            </label>
          </div>
        </fieldset>

        <fieldset v-if="!isOauthEdit">
          <legend>SMTP</legend>
          <div class="field-grid">
            <label>Host <input v-model="form.smtp_host" required /></label>
            <label>Port <input v-model.number="form.smtp_port" type="number" required /></label>
            <label>Security
              <select v-model="form.smtp_security">
                <option v-for="m in SECURITY_MODES" :key="m" :value="m">{{ m }}</option>
              </select>
            </label>
            <label>Username <input v-model="form.smtp_username" required /></label>
            <label>
              Password
              <input v-model="form.smtp_password" type="password" :placeholder="editingId ? '(unchanged)' : ''" :required="!editingId" />
            </label>
          </div>
        </fieldset>

        <div class="checkbox-row">
          <label><input v-model="form.verify_ssl" type="checkbox" /> Verify TLS certificate</label>
          <label><input v-model="form.auto_saves_sent" type="checkbox" /> Server auto-saves sent mail</label>
        </div>

        <div class="form-actions">
          <button type="button" @click="cancelForm">Cancel</button>
          <button type="submit" class="primary">Save</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.accounts-view {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  max-width: 900px;
  margin: 0 auto;
  width: 100%;
}

.header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1rem;
}

h1 {
  font-size: 1.3rem;
  margin: 0;
}

.hint {
  color: var(--text-secondary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.btn-link {
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.7rem;
  font-size: 0.85rem;
  text-decoration: none;
}

.btn-link:hover {
  background: var(--bg-hover);
}

.banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  border-radius: var(--radius-sm);
  padding: 0.6rem 0.85rem;
  margin-bottom: 1rem;
  font-size: 0.85rem;
}

.banner.success {
  background: color-mix(in srgb, var(--success) 20%, var(--bg-primary));
  color: var(--text-primary);
  border: 1px solid var(--success);
}

.banner.error {
  background: color-mix(in srgb, var(--danger) 15%, var(--bg-primary));
  color: var(--text-primary);
  border: 1px solid var(--danger);
}

.banner .dismiss {
  border: none;
  background: none;
  cursor: pointer;
  color: inherit;
  font-size: 0.9rem;
}

.pill.oauth {
  background: var(--accent);
  color: var(--accent-contrast);
}

button {
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.7rem;
  cursor: pointer;
  font-size: 0.85rem;
  font-family: inherit;
}

button.primary {
  background: var(--accent);
  color: var(--accent-contrast);
  border-color: var(--accent-strong);
}

button.danger {
  color: var(--danger);
  border-color: var(--danger);
}

.account-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.account-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 0.9rem 1rem;
}

.card-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.card-main {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.muted {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.pill {
  background: var(--bg-hover);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 0.1rem 0.5rem;
  font-size: 0.72rem;
}

.card-actions {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.test-result {
  margin-top: 0.6rem;
  display: flex;
  gap: 1rem;
  font-size: 0.82rem;
}

.test-result .ok {
  color: var(--success);
}

.test-result .fail {
  color: var(--danger);
}

.form-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.25);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding: 3rem 1rem;
  overflow-y: auto;
  z-index: 40;
}

.account-form {
  background: var(--bg-primary);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
  padding: 1.5rem;
  max-width: 560px;
  width: 100%;
}

.account-form h2 {
  margin-top: 0;
}

.error {
  color: var(--danger);
  font-size: 0.85rem;
}

fieldset {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  margin: 0.75rem 0;
}

legend {
  color: var(--text-secondary);
  font-size: 0.8rem;
  padding: 0 0.4rem;
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.6rem 0.8rem;
}

.field-grid label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.field-grid input,
.field-grid select {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.5rem;
  font-size: 0.85rem;
  font-family: inherit;
  background: var(--bg-body);
  color: var(--text-primary);
}

.checkbox-row {
  display: flex;
  gap: 1.2rem;
  margin: 0.75rem 0;
  font-size: 0.85rem;
}

.checkbox-row label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}
</style>

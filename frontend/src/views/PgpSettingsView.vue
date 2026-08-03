<script setup>
import { onMounted, reactive, ref } from "vue";
import { usePgpStore } from "@/stores/pgp";
import { api } from "@/api/client";

const pgp = usePgpStore();

const genForm = reactive({ name: "", email: "", passphrase: "", passphrase2: "" });
const importForm = reactive({ publicKeyArmored: "", privateKeyArmored: "" });
const unlockPassphrase = ref("");
const busy = ref(false);
const errorMsg = ref("");
const infoMsg = ref("");
const showImport = ref(false);

onMounted(() => pgp.init());

async function doGenerate() {
  errorMsg.value = "";
  infoMsg.value = "";
  if (genForm.passphrase.length < 8) {
    errorMsg.value = "Passphrase must be at least 8 characters.";
    return;
  }
  if (genForm.passphrase !== genForm.passphrase2) {
    errorMsg.value = "Passphrases don't match.";
    return;
  }
  busy.value = true;
  try {
    await pgp.generate({ name: genForm.name, email: genForm.email, passphrase: genForm.passphrase });
    infoMsg.value = "Key generated. Unlock it below to start using it for compose/reading.";
    genForm.passphrase = "";
    genForm.passphrase2 = "";
  } catch (e) {
    errorMsg.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function doImport() {
  errorMsg.value = "";
  infoMsg.value = "";
  busy.value = true;
  try {
    await pgp.importKeypair({ publicKeyArmored: importForm.publicKeyArmored, privateKeyArmored: importForm.privateKeyArmored });
    infoMsg.value = "Key imported.";
    importForm.publicKeyArmored = "";
    importForm.privateKeyArmored = "";
    showImport.value = false;
  } catch (e) {
    errorMsg.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function doUnlock() {
  errorMsg.value = "";
  busy.value = true;
  try {
    await pgp.unlock(unlockPassphrase.value);
    unlockPassphrase.value = "";
  } catch {
    errorMsg.value = "Wrong passphrase, or the stored key data is corrupt.";
  } finally {
    busy.value = false;
  }
}

function doExportPublic() {
  const blob = new Blob([pgp.publicKeyArmored], { type: "application/pgp-keys" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "nekomail-public-key.asc";
  a.click();
  URL.revokeObjectURL(url);
}

async function doDeleteKeypair() {
  if (!confirm("Delete your PGP keypair from this browser? This can't be undone here — make sure you have a backup if you'll need to decrypt old mail later.")) return;
  await pgp.deleteKeypair();
}

// --- Contact public keys (not sensitive -- stored server-side, see Contact.pgp_public_key) ---
const contacts = ref([]);
const keyDrafts = reactive({});
const contactBusy = reactive({});
const newContact = reactive({ email: "", display_name: "", pgp_public_key: "" });

async function loadContacts() {
  contacts.value = await api.get("/contacts?limit=25");
  contacts.value.forEach((c) => {
    if (!(c.id in keyDrafts)) keyDrafts[c.id] = c.pgp_public_key || "";
  });
}
onMounted(loadContacts);

async function saveContactKey(contact) {
  contactBusy[contact.id] = true;
  try {
    await api.patch(`/contacts/${contact.id}`, { pgp_public_key: keyDrafts[contact.id] || null });
    await loadContacts();
  } finally {
    contactBusy[contact.id] = false;
  }
}

async function addContact() {
  errorMsg.value = "";
  try {
    await api.post("/contacts", {
      email: newContact.email,
      display_name: newContact.display_name || null,
      pgp_public_key: newContact.pgp_public_key || null,
    });
    newContact.email = "";
    newContact.display_name = "";
    newContact.pgp_public_key = "";
    await loadContacts();
  } catch (e) {
    errorMsg.value = e.detail || e.message || "Couldn't add contact";
  }
}
</script>

<template>
  <div class="pgp-view">
    <h1>PGP</h1>
    <p class="hint intro">
      Encryption and signing happen entirely in your browser — your private key is never sent to or stored on the NekoMail server, only in this browser's local storage. That means it's per-device: set it up again on any other device/browser you want to read encrypted mail from.
    </p>

    <p v-if="errorMsg" class="error">{{ errorMsg }}</p>
    <p v-if="infoMsg" class="info">{{ infoMsg }}</p>

    <section class="card">
      <h2>Your key</h2>

      <template v-if="!pgp.hasKeypair">
        <div class="field-grid">
          <label>Name <input v-model="genForm.name" placeholder="Your name" /></label>
          <label>Email <input v-model="genForm.email" type="email" placeholder="you@example.com" /></label>
          <label>Passphrase <input v-model="genForm.passphrase" type="password" /></label>
          <label>Confirm passphrase <input v-model="genForm.passphrase2" type="password" /></label>
        </div>
        <div class="actions">
          <button type="button" class="primary" :disabled="busy" @click="doGenerate">Generate new key</button>
          <button type="button" @click="showImport = !showImport">{{ showImport ? "Cancel import" : "Import existing key instead" }}</button>
        </div>

        <div v-if="showImport" class="import-form">
          <label>Armored public key<textarea v-model="importForm.publicKeyArmored" rows="4" placeholder="-----BEGIN PGP PUBLIC KEY BLOCK-----" /></label>
          <label>Armored private key (must already be passphrase-protected)<textarea v-model="importForm.privateKeyArmored" rows="4" placeholder="-----BEGIN PGP PRIVATE KEY BLOCK-----" /></label>
          <button type="button" class="primary" :disabled="busy" @click="doImport">Import</button>
        </div>
      </template>

      <template v-else>
        <p class="fingerprint">Fingerprint: <code>{{ pgp.fingerprint }}</code></p>
        <p v-if="pgp.isUnlocked" class="status unlocked">🔓 Unlocked for this session</p>
        <p v-else class="status locked">🔒 Locked</p>

        <div v-if="!pgp.isUnlocked" class="unlock-row">
          <input v-model="unlockPassphrase" type="password" placeholder="Passphrase" @keyup.enter="doUnlock" />
          <button type="button" class="primary" :disabled="busy" @click="doUnlock">Unlock</button>
        </div>
        <div v-else class="actions">
          <button type="button" @click="pgp.lock()">Lock</button>
        </div>

        <div class="actions">
          <button type="button" @click="doExportPublic">Export public key</button>
          <button type="button" class="danger" @click="doDeleteKeypair">Delete key from this browser</button>
        </div>
      </template>
    </section>

    <section class="card">
      <h2>Recipients' public keys</h2>
      <p class="hint">To send someone encrypted mail, add their public key here first. Search picks up contacts already seen in synced mail.</p>

      <ul class="contact-list">
        <li v-for="c in contacts" :key="c.id" class="contact-row">
          <div class="contact-main">
            <strong>{{ c.display_name || c.email }}</strong>
            <span class="muted">{{ c.email }}</span>
            <span v-if="c.pgp_public_key" class="pill has-key">has key</span>
          </div>
          <textarea v-model="keyDrafts[c.id]" rows="2" placeholder="Paste armored public key here" />
          <button type="button" :disabled="contactBusy[c.id]" @click="saveContactKey(c)">Save</button>
        </li>
      </ul>

      <div class="add-contact">
        <h3>Add a contact</h3>
        <div class="field-grid">
          <label>Email <input v-model="newContact.email" type="email" /></label>
          <label>Name (optional) <input v-model="newContact.display_name" /></label>
        </div>
        <textarea v-model="newContact.pgp_public_key" rows="3" placeholder="Armored public key (optional, can add later)" />
        <button type="button" class="primary" @click="addContact">Add contact</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pgp-view {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  max-width: 800px;
  margin: 0 auto;
  width: 100%;
}

h1 {
  font-size: 1.3rem;
  margin: 0 0 0.5rem;
}

.hint {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.intro {
  margin-bottom: 1.25rem;
}

.error {
  color: var(--danger);
  font-size: 0.85rem;
}

.info {
  color: var(--success);
  font-size: 0.85rem;
}

.card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
}

.card h2 {
  margin-top: 0;
  font-size: 1.05rem;
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.6rem 0.8rem;
  margin-bottom: 0.75rem;
}

.field-grid label,
label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

input,
textarea {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.5rem;
  font-size: 0.85rem;
  font-family: inherit;
  background: var(--bg-body);
  color: var(--text-primary);
}

textarea {
  font-family: ui-monospace, monospace;
  font-size: 0.75rem;
  resize: vertical;
  width: 100%;
}

.actions {
  display: flex;
  gap: 0.5rem;
  margin: 0.6rem 0;
  flex-wrap: wrap;
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

.import-form {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border);
}

.fingerprint code {
  font-size: 0.78rem;
  background: var(--bg-elevated);
  padding: 0.15rem 0.4rem;
  border-radius: var(--radius-sm);
}

.status {
  font-size: 0.85rem;
  margin: 0.3rem 0;
}

.status.unlocked {
  color: var(--success);
}

.unlock-row {
  display: flex;
  gap: 0.5rem;
  margin: 0.5rem 0;
}

.unlock-row input {
  flex: 1;
}

.contact-list {
  list-style: none;
  margin: 0.75rem 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.contact-row {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.6rem;
}

.contact-main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
  flex-wrap: wrap;
}

.muted {
  color: var(--text-secondary);
  font-size: 0.82rem;
}

.pill {
  background: var(--bg-hover);
  color: var(--text-secondary);
  border-radius: 999px;
  padding: 0.1rem 0.5rem;
  font-size: 0.7rem;
}

.pill.has-key {
  background: var(--accent);
  color: var(--accent-contrast);
}

.contact-row textarea {
  margin-bottom: 0.4rem;
}

.add-contact {
  border-top: 1px solid var(--border);
  padding-top: 0.75rem;
  margin-top: 0.5rem;
}

.add-contact h3 {
  font-size: 0.9rem;
  margin: 0 0 0.5rem;
}

.add-contact textarea {
  margin-bottom: 0.5rem;
}
</style>

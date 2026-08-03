<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useAccountsStore } from "@/stores/accounts";
import { useRulesStore } from "@/stores/rules";
import { api } from "@/api/client";

const accounts = useAccountsStore();
const rules = useRulesStore();

const showForm = ref(false);
const editingId = ref(null);
const errorMsg = ref("");
const folderCache = reactive({}); // accountId -> Folder[]

const CONDITION_FIELDS = ["subject", "from", "to", "cc", "body", "has_attachment"];
const ACTION_TYPES = ["mark_read", "mark_unread", "star", "unstar", "archive", "trash", "move_to_folder"];

const FIELD_LABELS = { subject: "Subject", from: "From", to: "To", cc: "Cc", body: "Body", has_attachment: "Has attachment" };
const OPERATOR_LABELS = {
  contains: "contains", not_contains: "doesn't contain", equals: "equals",
  starts_with: "starts with", ends_with: "ends with", matches_regex: "matches regex (advanced)",
  is_true: "yes", is_false: "no",
};
const ACTION_LABELS = {
  mark_read: "Mark read", mark_unread: "Mark unread", star: "Star", unstar: "Unstar",
  archive: "Archive", trash: "Trash", move_to_folder: "Move to folder",
};

function fieldLabel(f) { return FIELD_LABELS[f] || f; }
function operatorLabel(op) { return OPERATOR_LABELS[op] || op; }
function actionLabel(t) { return ACTION_LABELS[t] || t; }
function operatorsFor(field) { return field === "has_attachment" ? ["is_true", "is_false"] : ["contains", "not_contains", "equals", "starts_with", "ends_with", "matches_regex"]; }

function blankForm() {
  return {
    name: "", account_id: "", is_active: true, priority: 0,
    conditions: [{ field: "subject", operator: "contains", value: "" }],
    actions: [{ type: "mark_read", params: {} }],
  };
}
const form = reactive(blankForm());

async function ensureFolders(accountId) {
  if (!accountId || folderCache[accountId]) return;
  folderCache[accountId] = await api.get(`/accounts/${accountId}/folders`);
}

onMounted(async () => {
  if (!accounts.loaded) await accounts.fetchAll();
  if (!rules.loaded) await rules.fetchAll();
});

const sortedRules = computed(() => [...rules.items].sort((a, b) => a.priority - b.priority || a.name.localeCompare(b.name)));

function scopeLabel(rule) {
  if (!rule.account_id) return "All accounts";
  return accounts.items.find((a) => a.id === rule.account_id)?.label || "Unknown account";
}
function summarize(rule) {
  const conds = rule.conditions
    .map((c) => `${fieldLabel(c.field)} ${operatorLabel(c.operator)}${c.field === "has_attachment" ? "" : ` "${c.value}"`}`)
    .join(" AND ");
  const acts = rule.actions.map((a) => actionLabel(a.type)).join(", ");
  return `If ${conds} → ${acts}`;
}

function startAdd() {
  Object.assign(form, blankForm());
  editingId.value = null;
  errorMsg.value = "";
  showForm.value = true;
}
function startEdit(rule) {
  Object.assign(form, {
    name: rule.name, account_id: rule.account_id || "", is_active: rule.is_active, priority: rule.priority,
    conditions: rule.conditions.map((c) => ({ ...c })),
    actions: rule.actions.map((a) => ({ type: a.type, params: { ...a.params } })),
  });
  if (form.account_id) ensureFolders(form.account_id);
  editingId.value = rule.id;
  errorMsg.value = "";
  showForm.value = true;
}
function cancelForm() {
  showForm.value = false;
  editingId.value = null;
  errorMsg.value = "";
}

function onFieldChange(condition) {
  const valid = operatorsFor(condition.field);
  if (!valid.includes(condition.operator)) condition.operator = valid[0];
}
function addCondition() {
  form.conditions.push({ field: "subject", operator: "contains", value: "" });
}
function addAction() {
  form.actions.push({ type: "mark_read", params: {} });
}

async function submitForm() {
  errorMsg.value = "";
  const moveActions = form.actions.filter((a) => a.type === "move_to_folder");
  if (moveActions.length && !form.account_id) {
    errorMsg.value = 'A "Move to folder" action requires a specific account, not "All accounts".';
    return;
  }
  if (moveActions.some((a) => !a.params.folder_id)) {
    errorMsg.value = 'Pick a target folder for every "Move to folder" action.';
    return;
  }

  const payload = {
    name: form.name,
    account_id: form.account_id || null,
    is_active: form.is_active,
    priority: form.priority,
    conditions: form.conditions,
    actions: form.actions,
  };
  try {
    if (editingId.value) await rules.update(editingId.value, payload);
    else await rules.create(payload);
    cancelForm();
  } catch (err) {
    errorMsg.value = err.detail || err.message || "Save failed";
  }
}

async function toggleActive(rule) {
  await rules.update(rule.id, { is_active: !rule.is_active });
}
async function doDelete(rule) {
  if (!confirm(`Delete rule "${rule.name}"?`)) return;
  await rules.remove(rule.id);
}
</script>

<template>
  <div class="rules-view">
    <div class="header-row">
      <h1>Mail rules</h1>
      <button type="button" class="primary" @click="startAdd">+ Add rule</button>
    </div>

    <p class="hint intro">Rules only ever apply to new incoming mail as it arrives — never retroactively to mail you already have.</p>

    <p v-if="rules.loading && !rules.loaded" class="hint">Loading…</p>
    <p v-else-if="rules.loaded && rules.items.length === 0" class="hint">No rules yet.</p>

    <ul class="rule-list">
      <li v-for="rule in sortedRules" :key="rule.id" class="rule-card">
        <div class="card-row">
          <div class="card-main">
            <strong>{{ rule.name }}</strong>
            <span class="muted">{{ scopeLabel(rule) }}</span>
            <span v-if="!rule.is_active" class="pill">inactive</span>
            <span class="pill priority">priority {{ rule.priority }}</span>
          </div>
          <div class="card-actions">
            <button type="button" @click="toggleActive(rule)">{{ rule.is_active ? "Deactivate" : "Activate" }}</button>
            <button type="button" @click="startEdit(rule)">Edit</button>
            <button type="button" class="danger" @click="doDelete(rule)">Delete</button>
          </div>
        </div>
        <p class="summary">{{ summarize(rule) }}</p>
      </li>
    </ul>

    <div v-if="showForm" class="form-overlay" @click.self="cancelForm">
      <form class="rule-form" @submit.prevent="submitForm">
        <h2>{{ editingId ? "Edit rule" : "Add rule" }}</h2>
        <p v-if="errorMsg" class="error">{{ errorMsg }}</p>

        <div class="field-grid">
          <label>Name <input v-model="form.name" required maxlength="128" /></label>
          <label>Applies to
            <select v-model="form.account_id" @change="ensureFolders(form.account_id)">
              <option value="">All accounts</option>
              <option v-for="a in accounts.items" :key="a.id" :value="a.id">{{ a.label }}</option>
            </select>
          </label>
          <label>Priority (lower runs first) <input v-model.number="form.priority" type="number" /></label>
        </div>
        <label class="checkbox-inline"><input v-model="form.is_active" type="checkbox" /> Active</label>

        <fieldset>
          <legend>Conditions — all must match</legend>
          <div v-for="(c, i) in form.conditions" :key="i" class="rule-row">
            <select v-model="c.field" @change="onFieldChange(c)">
              <option v-for="f in CONDITION_FIELDS" :key="f" :value="f">{{ fieldLabel(f) }}</option>
            </select>
            <select v-model="c.operator">
              <option v-for="op in operatorsFor(c.field)" :key="op" :value="op">{{ operatorLabel(op) }}</option>
            </select>
            <input v-if="c.field !== 'has_attachment'" v-model="c.value" placeholder="value" />
            <button type="button" class="remove-row" :disabled="form.conditions.length === 1" @click="form.conditions.splice(i, 1)">✕</button>
          </div>
          <button type="button" class="add-row" @click="addCondition">+ Condition</button>
        </fieldset>

        <fieldset>
          <legend>Actions — all run, in order</legend>
          <div v-for="(a, i) in form.actions" :key="i" class="rule-row">
            <select v-model="a.type">
              <option v-for="t in ACTION_TYPES" :key="t" :value="t">{{ actionLabel(t) }}</option>
            </select>
            <select v-if="a.type === 'move_to_folder'" v-model="a.params.folder_id" :disabled="!form.account_id">
              <option value="" disabled>{{ form.account_id ? "Pick a folder" : "Pick an account above first" }}</option>
              <option v-for="f in folderCache[form.account_id] || []" :key="f.id" :value="f.id">{{ f.name }}</option>
            </select>
            <button type="button" class="remove-row" :disabled="form.actions.length === 1" @click="form.actions.splice(i, 1)">✕</button>
          </div>
          <button type="button" class="add-row" @click="addAction">+ Action</button>
        </fieldset>

        <div class="form-actions">
          <button type="button" @click="cancelForm">Cancel</button>
          <button type="submit" class="primary">Save</button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.rules-view {
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
  margin-bottom: 0.5rem;
}

h1 {
  font-size: 1.3rem;
  margin: 0;
}

.hint {
  color: var(--text-secondary);
}

.intro {
  font-size: 0.85rem;
  margin: 0 0 1rem;
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

.rule-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.rule-card {
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
  flex-wrap: wrap;
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

.summary {
  margin: 0.6rem 0 0;
  font-size: 0.82rem;
  color: var(--text-secondary);
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

.rule-form {
  background: var(--bg-primary);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
  padding: 1.5rem;
  max-width: 620px;
  width: 100%;
}

.rule-form h2 {
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

.checkbox-inline {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0.75rem 0 0;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.rule-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.6rem;
}

.rule-row select,
.rule-row input {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.35rem 0.5rem;
  font-size: 0.82rem;
  font-family: inherit;
  background: var(--bg-body);
  color: var(--text-primary);
}

.rule-row input {
  flex: 1;
  min-width: 0;
}

.remove-row {
  border: none;
  background: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 0.85rem;
  padding: 0.2rem 0.4rem;
}

.remove-row:disabled {
  opacity: 0.35;
  cursor: default;
}

.add-row {
  margin: 0.2rem 0.6rem 0.6rem;
  border: 1px dashed var(--border);
  background: none;
  font-size: 0.8rem;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}
</style>

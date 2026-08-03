<script setup>
import { computed } from "vue";
import { useMailStore } from "@/stores/mail";

defineProps({
  accountId: { type: String, default: null },
  folderId: { type: String, default: null },
});
const emit = defineEmits(["select", "close"]);
const mail = useMailStore();
</script>

<template>
  <div class="move-picker" @click.stop>
    <p class="move-picker-title">Move to…</p>
    <button
      v-for="f in (mail.foldersByAccount[accountId] || []).filter((f) => f.is_selectable && f.id !== folderId)"
      :key="f.id"
      type="button"
      class="move-option"
      @click="emit('select', f.id)"
    >
      {{ f.name }}
    </button>
    <button type="button" class="move-cancel" @click="emit('close')">Cancel</button>
  </div>
</template>

<style scoped>
.move-picker {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-soft);
  padding: 0.5rem;
  min-width: 200px;
  max-height: 300px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.move-picker-title {
  margin: 0.25rem 0.5rem 0.4rem;
  font-size: 0.75rem;
  text-transform: uppercase;
  color: var(--text-secondary);
}

.move-option,
.move-cancel {
  text-align: left;
  background: none;
  border: none;
  padding: 0.5rem 0.6rem;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-primary);
  font-size: 0.85rem;
  font-family: inherit;
}

.move-option:hover {
  background: var(--bg-hover);
}

.move-cancel {
  color: var(--text-secondary);
  margin-top: 0.25rem;
  border-top: 1px solid var(--border);
}
</style>

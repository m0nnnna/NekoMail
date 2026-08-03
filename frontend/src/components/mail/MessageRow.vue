<script setup>
const props = defineProps({
  message: { type: Object, required: true },
  selected: { type: Boolean, default: false },
});
const emit = defineEmits(["toggle-select", "toggle-star", "open"]);

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function senderLabel() {
  const from = props.message.from_addrs?.[0];
  return from?.name || from?.email || "(unknown sender)";
}
</script>

<template>
  <div
    class="row"
    :class="{ unread: !message.flags.includes('\\Seen'), selected }"
    @click="emit('open', message)"
  >
    <input
      type="checkbox"
      class="check"
      :checked="selected"
      @click.stop
      @change="emit('toggle-select', message.id)"
    />
    <button type="button" class="star" :class="{ starred: message.flags.includes('\\Flagged') }" @click.stop="emit('toggle-star', message.id)">
      {{ message.flags.includes('\\Flagged') ? "★" : "☆" }}
    </button>
    <span v-if="!message.flags.includes('\\Seen')" class="unread-dot" />
    <span class="sender">{{ senderLabel() }}</span>
    <span class="subject">{{ message.subject || "(no subject)" }}</span>
    <span class="snippet">{{ message.is_encrypted ? "🔒 Encrypted message" : message.snippet }}</span>
    <span v-if="message.has_attachments" class="attach" title="Has attachments">📎</span>
    <span class="date">{{ formatDate(message.date) }}</span>
  </div>
</template>

<style scoped>
.row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  height: 100%;
  padding: 0 0.75rem;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--text-primary);
}

.row:hover {
  background: var(--bg-hover);
}

.row.selected {
  background: var(--bg-elevated);
}

.row.unread .sender,
.row.unread .subject {
  font-weight: 700;
}

.unread-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--unread-dot);
  flex-shrink: 0;
}

.star {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1rem;
  color: var(--text-muted);
  padding: 0;
  flex-shrink: 0;
}

.star.starred {
  color: var(--star);
}

.sender {
  width: 160px;
  flex-shrink: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.subject {
  flex-shrink: 0;
  max-width: 30%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.snippet {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
}

.attach {
  flex-shrink: 0;
}

.date {
  flex-shrink: 0;
  width: 70px;
  text-align: right;
  color: var(--text-secondary);
  font-size: 0.78rem;
}
</style>

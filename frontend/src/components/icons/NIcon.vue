<script setup>
// Icon that is a thin-line inline SVG under the Ultimit theme and the
// original emoji otherwise (also the fallback for unknown names).
import { computed } from "vue";
import { useThemeStore } from "@/stores/theme";

const props = defineProps({
  name: { type: String, required: true },
  size: { type: Number, default: 18 },
  filled: { type: Boolean, default: false },
  // Decorative extra: render only under the Ultimit theme (nothing for neko).
  only: { type: Boolean, default: false },
});

const theme = useThemeStore();

// 24x24 grid, 1.3 stroke, square caps/miter joins (Ultimit's rail icons).
const PATHS = {
  inbox: ["M3 13l3-8h12l3 8v6H3z", "M3 13h5l1.5 3h5L16 13h5"],
  sent: ["M21 3L10 14", "M21 3l-7 18-4-7-7-4z"],
  drafts: ["M5 3h10l4 4v14H5z", "M15 3v4h4", "M8 15l5-5 2 2-5 5H8z"],
  trash: ["M4 7h16", "M9 7V4h6v3", "M6 7l1 13h10l1-13", "M10 11v6M14 11v6"],
  junk: ["M12 3a9 9 0 100 18 9 9 0 000-18z", "M5.6 5.6l12.8 12.8"],
  archive: ["M3 4h18v4H3z", "M5 8v12h14V8", "M9 12h6"],
  flagged: ["M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"],
  important: ["M12 4v11", "M12 18.5v1.5"],
  all: ["M3 8l9-5 9 5-9 5z", "M3 13l9 5 9-5"],
  folder: ["M3 6h7l2 2h9v11H3z"],
  mailbox: ["M3 6h18v12H3z", "M3 6l9 7 9-7"],
  mailopen: ["M3 10l9-6 9 6v10H3z", "M3 10l9 6 9-6"],
  compose: ["M4 20h4L19 9l-4-4L4 16z", "M13 7l4 4"],
  reply: ["M9 6L3 12l6 6", "M3 12h11a7 7 0 017 7v1"],
  replyall: ["M9 6L3 12l6 6", "M14 6l-6 6 6 6", "M8 12h6a7 7 0 017 7v1"],
  forward: ["M15 6l6 6-6 6", "M21 12H10a7 7 0 00-7 7v1"],
  star: ["M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"],
  attach: ["M20 11l-8 8a5 5 0 01-7-7l9-9a3.5 3.5 0 015 5l-9 9a2 2 0 01-3-3l8-8"],
  lock: ["M6 11h12v9H6z", "M8 11V8a4 4 0 018 0v3"],
  unlock: ["M6 11h12v9H6z", "M8 11V8a4 4 0 017.5-1.5"],
  check: ["M4 12l5 5L20 6"],
  warn: ["M12 3l10 18H2z", "M12 10v5M12 18v1"],
  close: ["M5 5l14 14M19 5L5 19"],
  menu: ["M3 6h18M3 12h18M3 18h18"],
  back: ["M20 12H5", "M11 6l-6 6 6 6"],
  chevron: ["M9 6l6 6-6 6"],
  move: ["M3 6h7l2 2h9v11H3z", "M9 14h8M14 11l3 3-3 3"],
  // A small neko: ears, face, whiskers -- the character stays as an accent.
  cat: [
    "M5 9V3l5 3.5h4L19 3v6c1 2 1 5-1 8-2 3-4 4-6 4s-4-1-6-4c-2-3-2-6-1-8z",
    "M9.5 11.5v1.5M14.5 11.5v1.5M11 16l1 1 1-1",
    "M2.5 13.5L7 14.5M2.5 17L7 16M21.5 13.5L17 14.5M21.5 17L17 16",
  ],
};

const EMOJI = {
  inbox: "📥", sent: "📤", drafts: "📝", trash: "🗑️", junk: "🚫", archive: "🗄️", flagged: "⭐",
  important: "❗", all: "📚", folder: "📁", mailbox: "📬", compose: "✏️", attach: "📎", lock: "🔒",
  unlock: "🔓", check: "✅", warn: "⚠️", close: "✕", menu: "☰", back: "←", chevron: "▸", cat: "🐾",
  star: "☆", reply: "↩", replyall: "↩↩", forward: "↪", move: "📁", mailopen: "📭",
};

const paths = computed(() => PATHS[props.name]);
const useSvg = computed(() => theme.isUltimit && !!paths.value);
const emoji = computed(() => (props.name === "star" ? (props.filled ? "★" : "☆") : EMOJI[props.name] || ""));
const showEmoji = computed(() => !useSvg.value && !props.only);
</script>

<template>
  <svg
    v-if="useSvg"
    class="nicon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.3"
    stroke-linecap="square"
    stroke-linejoin="miter"
    aria-hidden="true"
  >
    <path v-for="(d, i) in paths" :key="i" :d="d" :fill="filled && i === 0 ? 'currentColor' : 'none'" />
  </svg>
  <span v-else-if="showEmoji" class="nicon-emoji" aria-hidden="true">{{ emoji }}</span>
</template>

<style scoped>
.nicon {
  flex-shrink: 0;
  vertical-align: -0.2em;
}
</style>

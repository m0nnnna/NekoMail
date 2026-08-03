<script setup>
import { onBeforeUnmount, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import { useMailStore } from "@/stores/mail";
import { useComposeStore } from "@/stores/compose";
import { usePgpStore } from "@/stores/pgp";
import { connectWs } from "@/api/ws";
import ComposeModal from "@/components/mail/ComposeModal.vue";

const auth = useAuthStore();
const ui = useUiStore();
const mail = useMailStore();
const compose = useComposeStore();
const pgp = usePgpStore();
const route = useRoute();

let closeWs = null;

onMounted(() => {
  ui.applyTheme();
  pgp.init();
});
onBeforeUnmount(() => closeWs?.());

watch(
  () => auth.status,
  (status) => {
    if (status === "authenticated" && !closeWs) {
      closeWs = connectWs((event) => mail.handleWsEvent(event));
    } else if (status !== "authenticated" && closeWs) {
      closeWs();
      closeWs = null;
    }
  },
  { immediate: true },
);
</script>

<template>
  <div class="app-shell">
    <header v-if="!route.meta.public && auth.status === 'authenticated'" class="topbar">
      <RouterLink to="/mail" class="wordmark logo-ears">NekoMail</RouterLink>
      <nav class="top-nav">
        <RouterLink to="/mail" active-class="active">Mail</RouterLink>
        <RouterLink to="/accounts" active-class="active">Accounts</RouterLink>
        <RouterLink to="/rules" active-class="active">Rules</RouterLink>
        <RouterLink to="/pgp" active-class="active">PGP</RouterLink>
      </nav>
      <div class="spacer" />
      <button class="icon-btn" @click="ui.toggleDark()">{{ ui.dark ? "☀️" : "🌙" }}</button>
      <span class="whoami">{{ auth.user?.display_name || auth.user?.username }}</span>
      <button class="icon-btn" @click="auth.logout()">Sign out</button>
    </header>
    <router-view />
    <ComposeModal v-if="compose.open" />
  </div>
</template>

<style>
@import "@/theme/tokens.css";
</style>

<style scoped>
.app-shell {
  min-height: 100vh;
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1.25rem;
  background: var(--bg-primary);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.wordmark {
  color: var(--accent-strong);
  font-weight: 700;
  font-size: 1.1rem;
  text-decoration: none;
}

.top-nav {
  display: flex;
  gap: 0.35rem;
  margin-left: 0.75rem;
}

.top-nav a {
  color: var(--text-secondary);
  text-decoration: none;
  padding: 0.35rem 0.65rem;
  border-radius: var(--radius-sm);
  font-size: 0.85rem;
}

.top-nav a:hover {
  background: var(--bg-hover);
}

.top-nav a.active {
  background: var(--accent);
  color: var(--accent-contrast);
}

.spacer {
  flex: 1;
}

.whoami {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.icon-btn {
  border: 1px solid var(--border);
  background: var(--bg-elevated);
  color: var(--text-primary);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.7rem;
  cursor: pointer;
  font-size: 0.85rem;
}
</style>

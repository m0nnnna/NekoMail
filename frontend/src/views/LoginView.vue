<script setup>
import { ref } from "vue";
import { useRouter, useRoute } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { ApiError } from "@/api/client";

const username = ref("");
const password = ref("");
const error = ref("");
const loading = ref(false);

const auth = useAuthStore();
const router = useRouter();
const route = useRoute();

async function onSubmit() {
  error.value = "";
  loading.value = true;
  try {
    await auth.login(username.value, password.value);
    router.push(route.query.next || "/");
  } catch (err) {
    error.value = err instanceof ApiError ? err.detail : "Login failed.";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="onSubmit">
      <h1 class="wordmark logo-ears">NekoMail</h1>
      <p class="tagline">nya~ welcome back</p>

      <label>
        Username
        <input v-model="username" type="text" autocomplete="username" required autofocus />
      </label>
      <label>
        Password
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>

      <p v-if="error" class="error">{{ error }}</p>

      <button type="submit" :disabled="loading">{{ loading ? "Signing in…" : "Sign in" }}</button>
    </form>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.login-card {
  width: 100%;
  max-width: 340px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-soft);
  padding: 2rem;
  display: flex;
  flex-direction: column;
  gap: 0.9rem;
}

.wordmark {
  margin: 0 0 0.1rem;
  text-align: center;
  color: var(--accent-strong);
  font-size: 1.6rem;
}

.tagline {
  margin: 0 0 0.5rem;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.85rem;
}

label {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

input {
  padding: 0.6rem 0.7rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--bg-body);
  color: var(--text-primary);
  font-size: 0.95rem;
}

input:focus {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}

button {
  margin-top: 0.4rem;
  padding: 0.65rem;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--accent-strong);
  color: var(--accent-contrast);
  font-weight: 600;
  cursor: pointer;
}

button:disabled {
  opacity: 0.7;
  cursor: default;
}

.error {
  margin: 0;
  color: var(--danger);
  font-size: 0.85rem;
}
</style>

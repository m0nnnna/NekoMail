import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "@/stores/auth";

const routes = [
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/LoginView.vue"),
    meta: { public: true },
  },
  { path: "/", redirect: "/mail" },
  {
    path: "/mail",
    name: "mail",
    component: () => import("@/views/InboxView.vue"),
  },
  {
    path: "/mail/:accountId/:folderId",
    name: "mail-folder",
    component: () => import("@/views/InboxView.vue"),
  },
  {
    path: "/mail/:accountId/:folderId/:messageId",
    name: "mail-message",
    component: () => import("@/views/InboxView.vue"),
  },
  {
    path: "/accounts",
    name: "accounts",
    component: () => import("@/views/AccountsView.vue"),
  },
  {
    path: "/rules",
    name: "rules",
    component: () => import("@/views/RulesView.vue"),
  },
  {
    path: "/pgp",
    name: "pgp",
    component: () => import("@/views/PgpSettingsView.vue"),
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();

  if (auth.status === "unknown") {
    await auth.fetchMe();
  }

  if (!to.meta.public && auth.status !== "authenticated") {
    return { name: "login", query: { next: to.fullPath } };
  }

  if (to.name === "login" && auth.status === "authenticated") {
    return { name: "mail" };
  }

  return true;
});

export default router;

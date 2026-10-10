import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import router from "./router";
import { useThemeStore } from "./stores/theme";

const app = createApp(App);

const pinia = createPinia();
app.use(pinia);
app.use(router);

const themeStore = useThemeStore(pinia);
themeStore.start();
// The native window pushes Ultimit skin changes here (page timers are
// throttled while the window is unfocused, so polling alone lags).
window.__nekomailRefreshSkin = () => themeStore.refresh();

app.mount("#app");

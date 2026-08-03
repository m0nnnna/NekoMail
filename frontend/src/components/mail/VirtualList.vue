<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps({
  items: { type: Array, required: true },
  itemHeight: { type: Number, default: 64 },
  overscan: { type: Number, default: 6 },
  keyField: { type: String, default: "id" },
});
const emit = defineEmits(["scroll-end"]);

const containerRef = ref(null);
const scrollTop = ref(0);
const viewportHeight = ref(0);
let resizeObserver = null;

function onScroll() {
  const el = containerRef.value;
  if (!el) return;
  scrollTop.value = el.scrollTop;
  if (el.scrollHeight - (el.scrollTop + el.clientHeight) < el.clientHeight) {
    emit("scroll-end");
  }
}

onMounted(() => {
  if (!containerRef.value) return;
  viewportHeight.value = containerRef.value.clientHeight;
  resizeObserver = new ResizeObserver(() => {
    viewportHeight.value = containerRef.value?.clientHeight ?? 0;
  });
  resizeObserver.observe(containerRef.value);
});
onBeforeUnmount(() => resizeObserver?.disconnect());

const totalHeight = computed(() => props.items.length * props.itemHeight);
const startIndex = computed(() => Math.max(0, Math.floor(scrollTop.value / props.itemHeight) - props.overscan));
const endIndex = computed(() =>
  Math.min(props.items.length, Math.ceil((scrollTop.value + viewportHeight.value) / props.itemHeight) + props.overscan),
);
const visibleRows = computed(() =>
  props.items.slice(startIndex.value, endIndex.value).map((item, i) => ({
    item,
    index: startIndex.value + i,
    top: (startIndex.value + i) * props.itemHeight,
  })),
);

defineExpose({
  scrollToTop() {
    if (containerRef.value) containerRef.value.scrollTop = 0;
  },
});
</script>

<template>
  <div ref="containerRef" class="virtual-list" @scroll="onScroll">
    <div class="virtual-list-spacer" :style="{ height: totalHeight + 'px' }">
      <div
        v-for="row in visibleRows"
        :key="row.item[keyField]"
        class="virtual-list-row"
        :style="{ transform: `translateY(${row.top}px)`, height: itemHeight + 'px' }"
      >
        <slot :item="row.item" :index="row.index" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.virtual-list {
  overflow-y: auto;
  height: 100%;
  position: relative;
}

.virtual-list-spacer {
  position: relative;
}

.virtual-list-row {
  position: absolute;
  left: 0;
  right: 0;
}
</style>

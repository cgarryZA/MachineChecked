<script>
  import { statusView } from "../lib/presentation.js";
  let { record, small = false } = $props();
  const view = $derived(statusView(record));
</script>

<span class={"chip st-" + view.class} class:small title={view.explanation} data-status={record?.status_code || "unknown"}><span class="dot" aria-hidden="true"></span>{view.label}</span>

<style>
  .chip {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 2px 10px 2px 8px; border-radius: 999px; font-size: 13px;
    background: color-mix(in srgb, var(--st) 14%, var(--surface));
    border: 1px solid color-mix(in srgb, var(--st) 45%, var(--surface));
    white-space: nowrap;
  }
  .chip.small { font-size: 12px; padding: 0 8px 0 6px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--st); flex: none; }
</style>

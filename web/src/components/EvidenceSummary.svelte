<script>
  import { evidenceFacts } from "../lib/presentation.js";
  import StatusChip from "./StatusChip.svelte";
  let { record } = $props();
  const facts = $derived(evidenceFacts(record));
</script>
{#if facts.length}
  <span class="facts" data-status={record?.status_code || "unknown"}>{#each facts as f}<span title={f.detail}><span class="label">{f.label}</span> {f.word}</span>{/each}</span>
{:else}<StatusChip {record} />{/if}
<style>
  .facts { display: inline-flex; flex-wrap: wrap; gap: 6px 16px; text-align: left; font-size: 14px; }
  .label { color: var(--muted); margin-right: 4px; }
</style>

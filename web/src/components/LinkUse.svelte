<script>
  import { linkUses } from "../lib/linkuse.js";

  // Under a linked declaration: how each main result uses it (`impact.link_uses`), with where the
  // main results come from. A use is a path of references in the Lean terms of this build; it
  // changes no status.
  let { doc = null, claimId, name } = $props();
  const view = $derived(linkUses(doc, claimId, name));
</script>

{#if view?.unavailable}
  <p class="small faint link-use" data-link-use={name}>How the main results use it: {view.unavailable}.</p>
{:else if view?.entries.length}
  <div class="link-use" data-link-use={name}>
    <p class="small faint">How the main results use it ({view.basis}):</p>
    <ul class="small">
      {#each view.entries as e (e.main)}
        <li data-main={e.main} data-use={e.use}><code>{e.main}</code>: {e.answer}{#if e.via.length}<span class="faint">{" (through " + e.via.join(", ") + ")"}</span>{/if}</li>
      {/each}
    </ul>
  </div>
{/if}

<style>
  .link-use { margin: 4px 0 8px; }
  .link-use p { margin: 2px 0; }
  .link-use ul { margin: 2px 0; padding-left: 20px; }
  .link-use li { overflow-wrap: anywhere; }
  .small { font-size: 13px; }
  .faint { color: var(--faint); }
  code { font-size: 12px; }
</style>

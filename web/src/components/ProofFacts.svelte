<script>
  import { proofFacts, rememberedWorkspace, updateWorkspace, newId } from "../lib/workspace.js";
  import LeanText from "./LeanText.svelte";

  // The typed facts inside one declaration's proof, read from Lean on request under
  // `machinechecked view` (the same answer as `compare --query proof-facts`). Each fact is shown
  // with the assumptions it needs and the cases it lies in: it is established inside this proof
  // under that context, never an exported theorem. A fact can be cited as evidence in the open
  // investigation; the citation keeps that basis.
  let { name, claim, onref = null } = $props();

  let doc = $state(null);
  let error = $state(null);
  let busy = $state(false);
  let match = $state("");
  let cited = $state({});

  async function load() {
    busy = true; error = null;
    try { doc = await proofFacts(name, match.trim()); }
    catch (e) { error = String(e.message || e); }
    busy = false;
  }

  const sub = $derived(doc?.subject || {});
  const locals = $derived(Object.fromEntries((sub.locals || []).map((l) => [l.id, l])));
  const hyps = (f) => (f.assumptions || []).filter((a) => a.role === "hypothesis");
  const label = (f) => f.kind === "application" ? f.head : f.name;
  const where = (f) => f.source?.line ? `${f.source.file}:${f.source.line}` : null;

  async function cite(f) {
    const ws = rememberedWorkspace();
    if (!ws) { error = "Open an investigation below first, then cite the fact."; return; }
    busy = true; error = null;
    try {
      await updateWorkspace(ws, [{ op: "put", record: { id: newId("e"), kind: "evidence", claim: claim.id,
        ref: { fact: f.ref }, role: "supports" } }]);
      cited = { ...cited, [f.id]: true };
      globalThis.dispatchEvent?.(new CustomEvent("machinechecked-workspace-changed"));
    } catch (e) { error = String(e.message || e); }
    busy = false;
  }
</script>

<details class="facts" data-decl={name}>
  <summary>Facts inside the proof</summary>
  {#if !doc}
    <p class="small">Lean reads this declaration's proof and lists the propositions it establishes along the way, each with the assumptions it needs.</p>
    <button class="act" disabled={busy} onclick={load}>{busy ? "Reading the proof…" : "Read the proof"}</button>
  {:else}
    <p class="small"><input class="q" bind:value={match} placeholder="a bound or symbol to look for" aria-label="Look for" onkeydown={(e) => e.key === "Enter" && load()} />
      <button class="act" disabled={busy} onclick={load}>{match.trim() ? "Rank" : "Show all"}</button></p>
    {#if doc.match}<p class="faint small">{doc.match.candidates} of {doc.match.of} facts share symbols with “{doc.match.query}”. Sharing symbols does not mean one bound gives another.</p>{/if}
    {#each doc.results as f (f.id)}
      <div class="fact" data-kind={f.kind} data-fact={f.id}>
        <p class="small"><span class="what">{f.what}</span>{#if label(f)} <code>{label(f)}</code>{/if}
          {#if where(f)}<span class="faint"> · {where(f)}{f.source.located === "the declaration only" ? " (its line is not known)" : ""}</span>{/if}</p>
        <LeanText pp={f.type} {onref} />
        {#if hyps(f).length}<p class="small"><span class="faint">assuming</span> {#each hyps(f) as a, i}{i ? "; " : ""}<code>{a.name} : {a.type}</code>{/each}</p>{/if}
        {#each f.cases || [] as c}<p class="small faint">{c}</p>{/each}
        {#each f.premises || [] as p}<p class="small"><span class="faint">needs</span> <code>{p.name} : {p.type.text}</code>, <span class="faint">supplied by</span> {locals[p.supplied_by]?.name ?? "a proof term"}</p>{/each}
        <p class="small faint basis">{f.basis}{f.used_by?.length ? " · used by " + f.used_by.join(", ") : ""}
          · {#if cited[f.id]}cited{:else}<button class="link" disabled={busy} onclick={() => cite(f)}>Cite in the investigation</button>{/if}</p>
      </div>
    {:else}
      <p class="small muted">{doc.match ? "No fact of this proof shares a symbol with it." : "Lean keeps no typed fact in this proof's term."}</p>
    {/each}
    {#each sub.source_only || [] as o}
      <div class="fact" data-kind="source">
        <p class="small"><span class="what">source text only</span> <span class="faint">· {o.source.file}:{o.source.line}</span></p>
        <pre class="src">{o.text}</pre>
        <p class="small faint">{o.note}</p>
      </div>
    {/each}
    {#if sub.proof && !sub.proof.complete}<p class="small bad">Incomplete: {sub.proof.cut.join("; ")}.</p>{/if}
    {#if sub.proof?.auxiliary?.length}<p class="small faint">Not entered: {sub.proof.auxiliary.join(", ")}, lemmas Lean generated for parts of the proof.</p>{/if}
    <p class="small faint">{sub.note}</p>
  {/if}
  {#if error}<p class="bad small" role="alert">{error}</p>{/if}
</details>

<style>
  .facts { margin: 8px 0; }
  .facts > summary { cursor: pointer; font-size: 13px; color: var(--accent); }
  .fact { border-left: 3px solid var(--border); padding: 2px 0 2px 10px; margin: 8px 0; }
  .fact[data-kind="source"] { border-left-style: dashed; }
  .fact p { margin: 2px 0; }
  .what { margin-right: 6px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--faint); }
  .src { font: 12px/1.4 var(--mono); white-space: pre-wrap; margin: 2px 0; color: var(--muted); }
  .q { font: inherit; font-size: 13px; padding: 1px 6px; border: 1px solid var(--border); border-radius: 6px; width: 16em; }
  .act { font: inherit; font-size: 13px; padding: 3px 10px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }
  .act:disabled { opacity: 0.5; cursor: default; }
  .link { font: inherit; background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; }
  .bad { color: var(--st-refuted); }
</style>

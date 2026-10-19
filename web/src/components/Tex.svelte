<script>
  import renderMathInElement from "katex/contrib/auto-render";

  // A short piece of TeX with its mathematics typeset (a symbol to choose when linking). The
  // paper's statements are shown by PaperStatement.svelte, which typesets a passage only whole.
  let { text } = $props();
  let el;

  $effect(() => {
    if (!el) return;
    el.textContent = text;
    renderMathInElement(el, {
      delimiters: [
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
      trust: false,
    });
  });
</script>

<div class="tex" bind:this={el}></div>

<style>
  .tex { font-family: var(--serif); font-size: 16px; line-height: 1.6; padding: 10px 14px; background: var(--surface); border-radius: var(--radius); margin-top: 6px; }
</style>

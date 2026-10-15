<script>
  import renderMathInElement from "katex/contrib/auto-render";

  // Manuscript source with its inline and display mathematics typeset; macros the page does not
  // know are shown as source.
  let { text } = $props();
  let el;
  $effect(() => {
    if (!el) return;
    el.textContent = text
      .replace(/\\label\{[^}]*\}/g, "")
      .replace(/\\(emph|textit|textbf)\{([^}]*)\}/g, "$2")
      .replace(/~/g, " ");
    renderMathInElement(el, {
      delimiters: [
        { left: "\\[", right: "\\]", display: true },
        { left: "\\begin{equation}", right: "\\end{equation}", display: true },
        { left: "$$", right: "$$", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
    });
  });
</script>

<div class="tex" bind:this={el}></div>

<style>
  .tex { font-family: var(--serif); font-size: 16px; line-height: 1.6; padding: 10px 14px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-top: 6px; }
</style>

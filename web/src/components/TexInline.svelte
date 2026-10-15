<script>
  import renderMathInElement from "katex/contrib/auto-render";

  // A short piece of the paper's TeX (a theorem's title) typeset inline: its mathematics by
  // KaTeX, its text markup reduced to the text it prints.
  let { text } = $props();
  let el;

  export function plain(t) {
    return String(t || "")
      .replace(/\\texorpdfstring\{((?:[^{}]|\{[^{}]*\})*)\}\{(?:[^{}]|\{[^{}]*\})*\}/g, "$1")
      .replace(/\\(emph|textit|textbf|textsc|textrm|textup|mbox|text)\{([^{}]*)\}/g, "$2")
      .replace(/\\(cite|citep|citet)(\[[^\]]*\])?\{([^}]*)\}/g, "[$3]")
      .replace(/\\(eqref)\{([^}]*)\}/g, "($2)")
      .replace(/``/g, "“").replace(/''/g, "”").replace(/---/g, "—").replace(/--/g, "–")
      .replace(/~/g, " ").replace(/\\[,;:! ]/g, " ").replace(/\\&/g, "&");
  }

  $effect(() => {
    if (!el) return;
    el.textContent = plain(text);
    renderMathInElement(el, {
      delimiters: [
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
    });
  });
</script>

<span class="ti" bind:this={el}></span>

<style>
  .ti :global(.katex) { font-size: 1.05em; }
</style>

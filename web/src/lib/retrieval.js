// Search the project's declarations by mathematical content: the engine's retrieval
// (engine/python/prooflens/retrieval.py) over the index it exports (data/retrieval.json). The
// tables of words and symbols and the constants come from that index, so the reader, the
// suggestions and `machinechecked compare --query search` rank alike; the cases in
// tests/fixtures/retrieval/cases.json check that they do. A result is a candidate to inspect:
// it never makes a link or changes a status.

const TEX_COMMENT = /(?<!\\)%[^\n]*/g;
const TEX_DROP = /\\(?:label|ref|eqref|cref|Cref|autoref|cite|citep|citet|lean|leanok|mathlibok|notready|uses)\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?/g;
const TEX_BB = /\\(?:mathbb|mathbf|bm)\s*\{?\s*([A-Za-z])\s*\}?/g;
const TEX_CMD = /\\([A-Za-z]+)/g;
const TEX_SPACE = /\\[,;:! ]/g;
const TOKEN = /[A-Za-z_][A-Za-z0-9_'!?]*(?:\.[A-Za-z_][A-Za-z0-9_'!?]*)*|[0-9]+|<->|<=|>=|!=|\\\||\S/gu;
const CAMEL = /([a-z0-9])([A-Z])|([A-Z]+)([A-Z][a-z])/g;
const PAPER_Q = /∀|\bfor (?:all|every|each|any)\b|\bwhenever\b|∃|\bthere (?:exists?|is|are)\b|\bfor some\b/gi;
const OPEN = "([{⟨⦃", CLOSE = ")]}⟩⦄";

const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

export function round(x, digits) {
  const f = 10 ** digits;
  return Math.round(x * f) / f;
}

function stem(w) {
  if (w.length > 4 && w.endsWith("ies")) return w.slice(0, -3) + "y";
  if (w.endsWith("sses")) return w.slice(0, -2);
  if (w.length > 3 && w.endsWith("s") && !(w.endsWith("ss") || w.endsWith("us") || w.endsWith("is"))) w = w.slice(0, -1);
  if (w.length > 5 && w.endsWith("ing")) return w.slice(0, -3);
  if (w.length > 4 && w.endsWith("ed") && !w.endsWith("eed")) return w.slice(0, -2);
  return w;
}

function rstrip(s, chars) {
  let i = s.length;
  while (i > 0 && chars.includes(s[i - 1])) i--;
  return s.slice(0, i);
}

export class Tokenizer {
  constructor(tables) {
    this.t = tables;
    this.symbols = new Set([...tables.symbols]);
    this.stop = new Set(tables.stop);
    this.env = new Set(tables.env_words);
  }

  prepareTex(text) {
    const t = this.t;
    text = (text || "").replace(TEX_COMMENT, " ").replace(TEX_DROP, " ");
    text = text.replace(TEX_BB, (m, l) => (l === l.toUpperCase() ? " " + (t.blackboard[l.toUpperCase()] ?? " ") + " " : " "));
    text = text.replace(TEX_SPACE, " ").replaceAll("\\|", " ‖ ");
    return text.replace(TEX_CMD, (m, name) => " " + (Object.hasOwn(t.tex_macros, name) ? t.tex_macros[name] : " ") + " ");
  }

  wordTerms(piece) {
    if (/^[0-9]+$/.test(piece)) return ["#" + (piece.replace(/^0+/, "") || "0")];
    if (Object.hasOwn(this.t.word_terms, piece)) return [...this.t.word_terms[piece]];
    if (piece.length < 2 || this.stop.has(piece) || this.env.has(piece)) return [];
    return [stem(piece)];
  }

  splitName(part) {
    part = part.replace(CAMEL, (m, a, b, c, d) => (a ?? c) + " " + (b ?? d));
    return part.split(/[_\s'!?]+/).filter(Boolean).map((p) => p.toLowerCase());
  }

  terms(text, constants = true) {
    const out = [];
    const src = this.prepareTex((text || "").normalize("NFC"));
    const toks = [...src.matchAll(TOKEN)].map((m) => m[0]);
    for (let k = 0; k < toks.length; k++) {
      let tok = toks[k];
      if (/^[A-Za-z_]/.test(tok)) {
        tok = rstrip(tok, "'!?");
        const parts = tok.split(".");
        if (parts.length > 1 && constants && parts.every(Boolean)) out.push("@" + tok);
        for (const p of this.splitName(parts[parts.length - 1])) out.push(...this.wordTerms(p));
      } else if (/^[0-9]/.test(tok)) {
        out.push(...this.wordTerms(tok));
      } else if (Object.hasOwn(this.t.ascii_ops, tok)) {
        out.push("§" + this.t.ascii_ops[tok]);
      } else {
        const s = this.t.symbol_aliases[tok] ?? tok;
        if (this.symbols.has(s)) out.push("§" + s);
        // A power 2 (`n ^ 2`, `n^{2}`) is also a square.
        if (s === "^" && toks.slice(k + 1, k + 3).filter((t) => t !== "{")[0] === "2") out.push("square");
      }
    }
    return out;
  }

  paperQuantifiers(text) {
    const t = this.prepareTex(text);
    const seq = [...t.matchAll(PAPER_Q)].map((m) => {
      const g = m[0], l = g.toLowerCase();
      return g === "∃" || l.startsWith("there") || l.startsWith("for some") ? "∃" : "∀";
    });
    return collapse(seq);
  }
}

export function displayTerm(t) {
  return "§#@".includes(t[0]) ? t.slice(1) : t;
}

function collapse(seq) {
  let out = "";
  for (const q of seq) if (!out || out[out.length - 1] !== q) out += q;
  return out;
}

function topLevel(s, sep) {
  let depth = 0;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (OPEN.includes(ch)) depth++;
    else if (CLOSE.includes(ch)) depth--;
    else if (depth === 0 && s.startsWith(sep, i)) return i;
  }
  return -1;
}

// The order of the quantifiers a Lean statement's text opens with and its conclusion opens
// with, skipping its hypotheses; a binder `(x : T) →` counts as `∀`.
export function leanQuantifiers(ty) {
  const seq = [];
  let s = (ty || "").trim();
  for (let k = 0; k < 200; k++) {
    s = s.trimStart();
    if (s[0] === "∀" || s[0] === "∃") {
      seq.push(s[0]);
      const j = topLevel(s, ",");
      if (j < 0) break;
      s = s.slice(j + 1);
      continue;
    }
    const j = topLevel(s, "→");
    if (j < 0) break;
    const head = s.slice(0, j).trim();
    if ((head === "" || "({⦃[".includes(head[0])) && head.includes(" : ")) seq.push("∀");
    s = s.slice(j + 1);
  }
  return collapse(seq);
}

// A sentence when the paper and a statement end with ∀ and ∃ in opposite orders; only the last
// alternation is compared, as a paper often leaves the outer "for all" unsaid.
export function quantifierDifference(paper, lean) {
  if (!paper || !lean || paper.length < 2 || lean.length < 2) return null;
  paper = paper.slice(-2); lean = lean.slice(-2);
  if (paper === lean) return null;
  const words = (q) => [...q].map((c) => (c === "∀" ? "for all" : "there is")).join(" then ");
  return `the quantifiers come in a different order (the paper: ${words(paper)}; the Lean statement: ${words(lean)}), so what each choice may depend on differs`;
}

export class Retrieval {
  constructor(data) {
    if (data?.schema !== "machinechecked/retrieval@1") throw new Error("not a retrieval index of this version");
    this.p = data.params;
    this.tables = data.tables;
    this.tok = new Tokenizer(data.tables);
    this.docs = data.docs;
    this.byName = new Map();
    this.df = new Map();
    this.postings = new Map();
    this.usedBy = new Map();
    this.docs.forEach((d, i) => {
      if (!this.byName.has(d.name)) this.byName.set(d.name, i);
      for (const t of Object.keys(d.t)) {
        this.df.set(t, (this.df.get(t) || 0) + 1);
        if (!this.postings.has(t)) this.postings.set(t, []);
        this.postings.get(t).push(i);
      }
    });
    const push = (u, v) => { if (!this.usedBy.has(u)) this.usedBy.set(u, []); this.usedBy.get(u).push(v); };
    for (const d of this.docs) {
      for (const u of [...new Set(d.value_uses || [])].sort(cmp)) push(u, [d.name, "value"]);
      for (const u of [...new Set(d.uses || [])].sort(cmp)) push(u, [d.name, "statement"]);
    }
    this.sig = new Map();
  }

  get size() { return this.docs.length; }

  idf(t) {
    const n = this.docs.length, df = this.df.get(t) || 0;
    return Math.log(1 + (n - df + 0.5) / (df + 0.5));
  }

  queryCounts(q) {
    const ts = typeof q === "string" ? this.tok.terms(q) : q;
    const out = new Map();
    for (const t of ts) out.set(t, Math.min(this.p.query_tf_max, (out.get(t) || 0) + 1));
    return out;
  }

  weights(qc) {
    const w = new Map();
    for (const [t, n] of qc) w.set(t, n * this.idf(t));
    let total = 0;
    for (const [t, v] of w) total += v * (this.df.get(t) ? 1 : this.p.unseen);
    return [w, total];
  }

  scoreDoc(qc, i, ww) {
    const [w, total] = ww || this.weights(qc);
    if (total <= 0) return [0, []];
    const td = this.docs[i].t;
    let got = 0;
    const matched = [];
    for (const [t, wt] of w) {
      const e = td[t];
      if (e) {
        const c = (wt * e[0]) / (e[0] + this.p.match_k);
        got += c;
        matched.push([t, c, e[1]]);
      }
    }
    const D = this.p.digits;
    matched.sort((a, b) => round(b[1], D) - round(a[1], D) || cmp(a[0], b[0]));
    return [round(got / total, D), matched];
  }

  signature(i) {
    if (!this.sig.has(i)) this.sig.set(i, leanQuantifiers(this.docs[i].type || ""));
    return this.sig.get(i);
  }

  // The declarations best matching `query`, best first, with their reasons: the same
  // operation as `Retrieval.search` in the engine.
  search(query, { kinds = null, limit = 20, after = null, exclude = [], paperOrder = null, minScore = 0 } = {}) {
    const D = this.p.digits;
    const qc = this.queryCounts(query);
    const [w, total] = this.weights(qc);
    const ok = kinds ? (i) => kinds(this.docs[i].kind) : () => true;
    // Term at a time: each declaration's sum is taken in the query's term order.
    const acc = new Map();
    for (const [t, wt] of w) {
      for (const i of this.postings.get(t) || []) {
        const e = this.docs[i].t[t][0];
        acc.set(i, (acc.get(i) || 0) + (wt * e) / (e + this.p.match_k));
      }
    }
    const hits = new Map();
    if (total > 0) for (const [i, got] of acc) {
      const c = round(got / total, D);
      if (c > 0) hits.set(i, { score: c, content: c, via: null });
    }
    const byScore = (a, b) => hits.get(b).score - hits.get(a).score || cmp(this.docs[a].name, this.docs[b].name);
    const top = [...hits.keys()].filter(ok).sort(byScore).slice(0, this.p.expand_top);
    for (const i of top) {
      if (hits.get(i).content < this.p.expand_min) continue;
      const name = this.docs[i].name;
      for (const [user, rel] of this.usedBy.get(name) || []) {
        const j = this.byName.get(user);
        if (j === undefined || j === i) continue;
        const sc = round(this.p.expand_factor * hits.get(i).content, D);
        let h = hits.get(j);
        if (!h) { h = { score: 0, content: 0, via: null }; hits.set(j, h); }
        if (sc > h.score) { h.score = sc; h.via = { name, relation: rel }; }
      }
    }
    const excl = new Set(exclude);
    const order = [...hits.keys()].filter((i) => ok(i) && hits.get(i).score >= minScore && hits.get(i).score > 0 && !excl.has(this.docs[i].name)).sort(byScore);
    let start = 0;
    if (after) {
      const k = order.findIndex((i) => this.docs[i].name === after);
      if (k < 0) throw new Error(`cursor ${after} is not a result of this search`);
      start = k + 1;
    }
    const part = limit ? order.slice(start, start + limit) : order.slice(start);
    const more = start + part.length < order.length;
    return { results: part.map((i) => this.result(i, hits.get(i), qc, paperOrder)), query: { terms: [...qc.keys()].map(displayTerm) },
      page: { total: order.length, returned: part.length, after, next: more && part.length ? this.docs[part[part.length - 1]].name : null, complete: !more && !start } };
  }

  result(i, h, qc, paperOrder) {
    const d = this.docs[i];
    const reasons = [];
    const matched = h.content ? this.scoreDoc(qc, i)[1] : [];
    if (matched.length) reasons.push(this.contentReason(matched, h.content));
    if (h.via) {
      const rel = h.via.relation === "value" ? (d.kind === "theorem" ? "its proof uses" : "its body uses") : "its statement mentions";
      reasons.push({ signal: "uses", via: h.via.name, relation: h.via.relation, text: `${rel} ${h.via.name}, a close match` });
    }
    if (paperOrder) {
      const diff = quantifierDifference(paperOrder, this.signature(i));
      if (diff) reasons.push({ signal: "structure", text: diff, paper: paperOrder, lean: this.signature(i) });
    }
    return { name: d.name, kind: d.kind, module: d.module, line: d.line, score: h.score, content: h.content,
      reasons, statement: d.type || "", complete: true, doc: d.doc };
  }

  contentReason(matched, score) {
    const top = matched.slice(0, 5);
    const where = [...new Set(top.flatMap(([, , fs]) => [...fs]))].sort((a, b) => "sdnu".indexOf(a) - "sdnu".indexOf(b)).join("");
    const shared = top.map(([t]) => displayTerm(t)).join(", ");
    const places = [...where].map((f) => this.tables.field_words[f]);
    const place = places.length === 1 ? places[0] : places.slice(0, -1).join(", ") + " and " + places[places.length - 1];
    return { signal: "content", score, terms: top.map(([t]) => displayTerm(t)), fields: [...where], text: `shares ${shared} (in ${place})` };
  }
}

// The search a claim's own statement gives: its title and printed passage, over declarations
// of its sort, with the paper's order of quantifiers.
export function claimQuery(ret, claim) {
  const text = [claim.title, claim.statement_tex || claim.anchor?.statement].filter(Boolean).join(" ");
  const definition = claim.scope === "definition";
  return { text, kinds: definition ? (k) => k !== "theorem" : (k) => k === "theorem",
    paperOrder: ret.tok.paperQuantifiers(text), sort: definition ? "definitions" : "theorems" };
}

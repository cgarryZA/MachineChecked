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
// `=>` (of `fun x => …`) is one token, and not a term.
const TOKEN = /[A-Za-z_][A-Za-z0-9_'!?]*(?:\.[A-Za-z_][A-Za-z0-9_'!?]*)*|[0-9]+|<->|<=|>=|!=|=>|\\\||\S/gu;
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
// alternation is compared, as a paper often leaves the outer "for all" unsaid. `first` and
// `second` name the two.
export function quantifierDifference(paper, lean, first = "the paper", second = "the Lean statement") {
  if (!paper || !lean || paper.length < 2 || lean.length < 2) return null;
  paper = paper.slice(-2); lean = lean.slice(-2);
  if (paper === lean) return null;
  const words = (q) => [...q].map((c) => (c === "∀" ? "for all" : "there is")).join(" then ");
  return `the quantifiers come in a different order (${first}: ${words(paper)}; ${second}: ${words(lean)}), so what each choice may depend on differs`;
}

// The shape of a statement: the engine's lean_shape, normal_parts, compare_parts and
// structure_reasons.
const BINDER_REL = / (?:∈|∉|⊆|⊂|⊇|⊃|≤|<|≥|>|≠) /;
const SPACE = /[ \t\n\r\f\v]+/;
const trimSp = (s) => s.replace(/^ +| +$/g, "");

function close(s, i) {
  let depth = 0;
  for (let k = i; k < s.length; k++) {
    if (OPEN.includes(s[k])) depth++;
    else if (CLOSE.includes(s[k])) { depth--; if (depth === 0) return k; }
  }
  return -1;
}

function binderGroup(text, binders, premises) {
  const t = trimSp(text);
  if (t && !"({⦃[".includes(t[0]) && BINDER_REL.test(` ${t} `)) {
    binders.push([t.split(" ")[0], ""]);
    premises.push(t);
    return;
  }
  let i = 0;
  while (i < t.length) {
    if (t[i] === " ") { i++; continue; }
    if ("({⦃[".includes(t[i])) {
      const j = close(t, i);
      if (j < 0) return;
      const inner = trimSp(t.slice(i + 1, j));
      const k = topLevel(inner, " : ");
      if (t[i] === "[") premises.push(k >= 0 ? trimSp(inner.slice(k + 3)) : inner);
      else if (k >= 0) for (const n of inner.slice(0, k).split(" ")) if (n) binders.push([n, trimSp(inner.slice(k + 3))]);
      i = j + 1;
      continue;
    }
    let j = t.indexOf(" ", i);
    if (j < 0) j = t.length;
    binders.push([t.slice(i, j), ""]);
    i = j;
  }
}

// The variables a Lean statement binds before its conclusion (name and type text), its
// hypotheses and its conclusion, as printed.
export function leanShape(ty) {
  let s = (ty || "").split(SPACE).filter(Boolean).join(" ");
  const binders = [], premises = [];
  for (;;) {
    s = trimSp(s);
    if (s[0] === "∀") {
      const j = topLevel(s, ",");
      if (j < 0) break;
      binderGroup(s.slice(1, j), binders, premises);
      s = s.slice(j + 1);
      continue;
    }
    if (s[0] === "∃") break;
    const j = topLevel(s, "→");
    if (j < 0) break;
    const head = trimSp(s.slice(0, j));
    if (head && "({⦃[".includes(head[0]) && close(head, 0) === head.length - 1 && (head[0] === "[" || topLevel(head.slice(1, -1), " : ") >= 0)) binderGroup(head, binders, premises);
    else premises.push(head);
    s = s.slice(j + 1);
  }
  return { binders, premises, conclusion: trimSp(s) };
}

const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function normalParts(shape, typed = true) {
  const seen = new Map(), place = new Map();
  for (const [name, ty] of shape.binders) {
    if (place.has(name) || name === "_") continue;
    const key = typed ? ty : "";
    seen.set(key, (seen.get(key) || 0) + 1);
    place.set(name, `⟦${key}#${seen.get(key)}⟧`);
  }
  if (!place.size) return [[...shape.premises], shape.conclusion];
  const alt = [...place.keys()].sort((a, b) => b.length - a.length || cmp(a, b)).map(escapeRe).join("|");
  const pat = new RegExp(`(?<![\\p{L}\\p{N}_.'✝])(${alt})(?![\\p{L}\\p{N}_'✝])`, "gu");
  const sub = (t) => t.replace(pat, (m, n) => place.get(n));
  return [shape.premises.map(sub), sub(shape.conclusion)];
}

function compareParts(ref, cand) {
  let best = null;
  for (let k = 0; k < 2; k++) {
    const [rp, rc] = ref[k], [cp, cc] = cand[k];
    const same = rc === cc && !!cc;
    const missing = [], extra = [];
    rp.forEach((p, i) => { if (!cp.includes(p)) missing.push(i); });
    cp.forEach((p, i) => { if (!rp.includes(p)) extra.push(i); });
    const agree = [same ? 1 : 0, rp.length - missing.length];
    if (!best || agree[0] > best.agree[0] || (agree[0] === best.agree[0] && agree[1] > best.agree[1])) best = { agree, same, missing, extra };
  }
  return best;
}

function listed(items, most = 3) {
  if (!items.length) return "";
  const shown = items.slice(0, most);
  const text = shown.length === 1 ? shown[0] : shown.slice(0, -1).join(", ") + " and " + shown[shown.length - 1];
  return text + (items.length > most ? ` (and ${items.length - most} more)` : "");
}

const count = (xs, x) => xs.filter((y) => y === x).length;

// How a statement's parts compare with those of the declaration searched from, as printed, up
// to the names of their variables. Whether one implies the other is left to review.
export function structureReasons(ref, refShape, shape, refParts, parts) {
  const { same, missing: lack, extra: more } = compareParts(refParts, parts);
  if (!same && lack.length === refShape.premises.length) return [];
  const missing = lack.map((k) => refShape.premises[k]), extra = more.map((k) => shape.premises[k]);
  const rt = refShape.binders.map(([, t]) => t).filter(Boolean), ct = shape.binders.map(([, t]) => t).filter(Boolean);
  const onlyHere = ct.filter((t, k) => count(ct.slice(0, k + 1), t) > count(rt, t));
  const onlyRef = rt.filter((t, k) => count(rt.slice(0, k + 1), t) > count(ct, t));
  if (same && !missing.length && !extra.length && !onlyHere.length && !onlyRef.length) return [{ signal: "structure", aspect: "same", text: `the same hypotheses and conclusion as ${ref}, as printed` }];
  const out = [{ signal: "structure", aspect: "conclusion", text: same ? `the same conclusion as ${ref}` : `a different conclusion from ${ref}'s` }];
  if (missing.length) out.push({ signal: "structure", aspect: "fewer hypotheses", hypotheses: missing, text: `it does not assume ${listed(missing)}, which ${ref} assumes` });
  if (extra.length) out.push({ signal: "structure", aspect: "more hypotheses", hypotheses: extra, text: `it also assumes ${listed(extra)}, which ${ref} does not` });
  if (!missing.length && !extra.length && shape.premises.length) out.push({ signal: "structure", aspect: "hypotheses", text: `the same hypotheses as ${ref}` });
  if (onlyHere.length || onlyRef.length) {
    const here = listed([...new Set(onlyHere)]), there = listed([...new Set(onlyRef)]);
    const text = onlyHere.length && onlyRef.length ? `it binds variables of type ${here} where ${ref} binds ${there}`
      : onlyHere.length ? `it also binds variables of type ${here}, which ${ref} does not`
      : `it does not bind variables of type ${there}, which ${ref} binds`;
    out.push({ signal: "structure", aspect: "variables", here: onlyHere, there: onlyRef, text });
  }
  return out;
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
    this.shapes = new Map();
    this.partsOf = new Map();
    this.conclusions = null;
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

  shape(i) {
    if (!this.shapes.has(i)) this.shapes.set(i, leanShape(this.docs[i].type || ""));
    return this.shapes.get(i);
  }

  parts(i) {
    if (!this.partsOf.has(i)) { const sh = this.shape(i); this.partsOf.set(i, [normalParts(sh, true), normalParts(sh, false)]); }
    return this.partsOf.get(i);
  }

  // The theorems whose conclusion is doc i's, as printed, up to the names of their variables.
  sameConclusion(i) {
    if (!this.conclusions) {
      this.conclusions = [new Map(), new Map()];
      this.docs.forEach((d, j) => {
        if (d.kind !== "theorem") return;
        this.parts(j).forEach(([, c], k) => {
          if (!c) return;
          const m = this.conclusions[k];
          if (!m.has(c)) m.set(c, []);
          m.get(c).push(j);
        });
      });
    }
    const found = new Set();
    this.parts(i).forEach(([, c], k) => { if (c) for (const j of this.conclusions[k].get(c) || []) found.add(j); });
    return [...found].sort((a, b) => a - b);
  }

  // The terms of a declaration's complete statement and docstring, each once, in the index's order.
  likeTerms(name) {
    const i = this.byName.get(name);
    if (i === undefined) throw new Error(`${name} is not in the index`);
    return Object.entries(this.docs[i].t).filter(([, e]) => e[1].includes("s") || e[1].includes("d")).map(([t]) => t);
  }

  // The declarations of name's sort whose statements best match its own: the engine's search_like.
  searchLike(name, { limit = 20, after = null, exclude = [] } = {}) {
    const i = this.byName.get(name);
    if (i === undefined) throw new Error(`${name} is not in the index`);
    const theorem = this.docs[i].kind === "theorem";
    return this.search(this.likeTerms(name), { kinds: theorem ? (k) => k === "theorem" : (k) => k !== "theorem", limit, after, exclude: [name, ...exclude], like: name });
  }

  // The declarations best matching `query`, best first, with their reasons: the same
  // operation as `Retrieval.search` in the engine.
  search(query, { kinds = null, limit = 20, after = null, exclude = [], paperOrder = null, minScore = 0, like = null } = {}) {
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
    const hits = new Map(), raw = new Map();
    if (total > 0) for (const [i, got] of acc) {
      raw.set(i, got / total);
      const c = round(got / total, D);
      if (c > 0) hits.set(i, { score: c, content: c, via: null });
    }
    const ref = like ? this.byName.get(like) : undefined;
    if (ref !== undefined && this.docs[ref].kind === "theorem") {
      // Halfway to 1 from the unrounded content score, which is never a tie to round.
      for (const i of this.sameConclusion(ref)) {
        if (!hits.has(i)) hits.set(i, { score: 0, content: 0, via: null });
        const h = hits.get(i);
        h.score = round((1 + (h.content ? raw.get(i) ?? 0 : 0)) / 2, D);
      }
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
    return { results: part.map((i) => this.result(i, hits.get(i), qc, paperOrder, like)), query: { terms: [...qc.keys()].map(displayTerm) },
      page: { total: order.length, returned: part.length, after, next: more && part.length ? this.docs[part[part.length - 1]].name : null, complete: !more && !start } };
  }

  result(i, h, qc, paperOrder, like = null) {
    const d = this.docs[i];
    const theorem = d.kind === "theorem";
    const reasons = [];
    const matched = h.content ? this.scoreDoc(qc, i)[1] : [];
    if (matched.length) {
      const shape = theorem ? this.shape(i) : null;
      const conclusion = shape && shape.premises.length ? new Set(this.tok.terms(shape.conclusion)) : null;
      reasons.push(this.contentReason(matched, h.content, conclusion));
    }
    if (h.via) {
      const rel = h.via.relation === "value" ? (theorem ? "its proof uses" : "its body uses") : "its statement mentions";
      const what = h.via.name === like ? "the declaration searched from" : "a close match";
      reasons.push({ signal: "uses", via: h.via.name, relation: h.via.relation, text: `${rel} ${h.via.name}, ${what}` });
    }
    if (paperOrder) {
      const diff = quantifierDifference(paperOrder, this.signature(i));
      if (diff) reasons.push({ signal: "structure", text: diff, paper: paperOrder, lean: this.signature(i) });
    }
    const j = like ? this.byName.get(like) : undefined;
    if (j !== undefined && theorem && this.docs[j].kind === "theorem") {
      const diff = quantifierDifference(this.signature(j), this.signature(i), like, "this statement");
      if (diff) reasons.push({ signal: "structure", aspect: "quantifiers", text: diff, searched: this.signature(j), lean: this.signature(i) });
      reasons.push(...structureReasons(like, this.shape(j), this.shape(i), this.parts(j), this.parts(i)));
    }
    return { name: d.name, kind: d.kind, module: d.module, line: d.line, score: h.score, content: h.content,
      reasons, statement: d.type || "", complete: true, doc: d.doc };
  }

  contentReason(matched, score, conclusion = null) {
    const top = matched.slice(0, 5);
    const where = [...new Set(top.flatMap(([, , fs]) => [...fs]))].sort((a, b) => "sdnu".indexOf(a) - "sdnu".indexOf(b)).join("");
    const shared = top.map(([t]) => displayTerm(t)).join(", ");
    const places = [...where].map((f) => this.tables.field_words[f]);
    const place = places.length === 1 ? places[0] : places.slice(0, -1).join(", ") + " and " + places[places.length - 1];
    const out = { signal: "content", score, terms: top.map(([t]) => displayTerm(t)), fields: [...where], text: `shares ${shared} (in ${place})` };
    if (conclusion) {
      const stated = top.filter(([, , fs]) => fs.includes("s")).map(([t]) => t);
      const inside = stated.filter((t) => conclusion.has(t));
      // A constant the index has by its full name may be printed shorter in the conclusion.
      const unsure = stated.filter((t) => t.startsWith("@") && !conclusion.has(t));
      if (inside.length) {
        out.conclusion = inside.map(displayTerm);
        out.text += `; its conclusion has ${out.conclusion.join(", ")}`;
      } else if (stated.length && !unsure.length) {
        out.conclusion = [];
        out.text += "; its conclusion has none of them";
      }
    }
    return out;
  }
}

// What the content index covers, as `machinechecked compare --query search` says it: every
// built module, unless the build left out libraries formalization.yaml maps only to other papers.
export function scopeText(index, size) {
  const left = index?.index_scope?.left_out || [];
  if (!left.length) return `among ${size} declarations of the project, linked or not`;
  return `among ${size} declarations of the libraries this paper's build indexes, linked or not; ${left.join(", ")}, which formalization.yaml maps only to other papers, ${left.length === 1 ? "is" : "are"} not searched here (\`machinechecked compare --query search … --all-libraries\` searches every library)`;
}

// The search a claim's own statement gives: its title and printed passage, over declarations
// of its sort, with the paper's order of quantifiers.
export function claimQuery(ret, claim) {
  const text = [claim.title, claim.statement_tex || claim.anchor?.statement].filter(Boolean).join(" ");
  const definition = claim.scope === "definition";
  return { text, kinds: definition ? (k) => k !== "theorem" : (k) => k === "theorem",
    paperOrder: ret.tok.paperQuantifiers(text), sort: definition ? "definitions" : "theorems" };
}

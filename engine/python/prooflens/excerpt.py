"""Paper passages typeset from their pinned LaTeX source, or not at all.

A display excerpt is the raw text of a passage of the paper (a theorem's body, a labelled
display, or an explicitly bounded region), read from the same snapshot that was compiled, with
everything needed to typeset it faithfully: the paper's own macro definitions in effect at the
passage, and the numbers its references, citations and equations print, from the compiled
`.aux` files. The passage is parsed into paragraphs, lists and mathematics. Anything the
renderer cannot reproduce exactly (an unknown text command, an unsupported environment, a
macro defined in a form this module does not interpret or inside a group, an unresolved
reference or citation, an equation whose printed number is unknown) makes the whole excerpt
`ready: false`, with its reasons, and the reader shows the PDF instead. Nothing is dropped to
obtain a render.

The excerpt is display only: its `fingerprint` (scheme `tex-excerpt-v1`) covers the raw passage
and its rendering context, and is separate from the audited `source_sha256`. No status reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .source_regions import ENV, COMMAND, Region, RegionError, environments, extract, source_file
from .util import content_id

SCHEME = "tex-excerpt-v1"
LETTERS = re.compile(r"[A-Za-z@]+")
# Displays KaTeX typesets; their numbered forms are turned into starred ones with `\tag`.
MATH_ENVS = {"equation", "align", "gather", "alignat"}
LISTS = {"itemize", "enumerate"}
VERBATIM = {"verbatim", "Verbatim", "lstlisting", "minted", "comment"}
STYLES = {"emph": "em", "textit": "it", "textsl": "it", "textbf": "bf", "textsc": "sc",
          "texttt": "tt", "textrm": "rm", "textup": "rm", "textnormal": "rm", "textsf": "sf",
          "textmd": "rm", "mbox": None, "text": None}
SYMBOLS = {"ldots": "…", "dots": "…", "textellipsis": "…", "S": "§", "textendash": "–",
           "textemdash": "—", "textquoteleft": "‘", "textquoteright": "’", "quad": "\u2003",
           "qquad": "\u2003\u2003", "enspace": "\u2002", "slash": "/", "ss": "ß",
           "textasciitilde": "~", "textbackslash": "\\", "copyright": "©"}
ESCAPES = {"%": "%", "&": "&", "$": "$", "#": "#", "_": "_", "{": "{", "}": "}", " ": " ",
           ",": "\u2009", ";": "\u2005", ":": "\u2005", "!": "", "-": "", "/": "", "@": "",
           "\n": " "}
INVISIBLE = {"noindent", "nobreak", "relax", "unskip", "ignorespaces"}
DEFINERS = {"newcommand", "renewcommand", "providecommand", "DeclareRobustCommand", "def",
            "gdef", "edef", "xdef", "let", "DeclareMathOperator", "newenvironment",
            "renewenvironment", "NewDocumentCommand", "RenewDocumentCommand",
            "DeclareDocumentCommand", "newtheorem", "renewtheorem"}
LIST_LABELS = re.compile(r"\\(labelenum|theenum|labelitem)[iv]+\b|\\set(list|enumerate|itemize)\b"
                         r"|\\usepackage(\[[^\]]*\])?\{[^}]*\b(enumitem|enumerate|paralist)\b")


class Unsupported(ValueError):
    """The passage cannot be typeset faithfully; the reader shows the PDF."""


@dataclass
class Definition:
    name: str
    params: int
    body: str
    file: str
    line: int
    problem: str | None = None    # why this definition cannot be used, if it cannot

    def record(self) -> dict:
        return {"params": self.params, "body": self.body, "file": self.file, "line": self.line}


# -- the source in reading order ---------------------------------------------------------------

def _skip_space(text: str, i: int) -> int:
    while i < len(text):
        if text[i] in " \t\r\n":
            i += 1
        elif text[i] == "%":
            end = text.find("\n", i)
            i = end + 1 if end >= 0 else len(text)
        else:
            break
    return i


def _group(text: str, i: int, open_: str = "{", close: str = "}") -> tuple[str, int]:
    """The balanced group opening at `text[i]` (after spaces), without its delimiters."""
    i = _skip_space(text, i)
    if i >= len(text) or text[i] != open_:
        raise Unsupported(f"expected {open_}")
    depth, j = 0, i
    while j < len(text):
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == "%":
            end = text.find("\n", j)
            j = end + 1 if end >= 0 else len(text)
            continue
        if c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    raise Unsupported("unbalanced braces")


def _optional(text: str, i: int) -> tuple[str | None, int]:
    j = _skip_space(text, i)
    if j < len(text) and text[j] == "[":
        depth, k = 0, j
        while k < len(text):
            if text[k] == "\\":
                k += 2
                continue
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            elif text[k] == "]" and depth == 0:
                return text[j + 1:k], k + 1
            k += 1
        raise Unsupported("unbalanced optional argument")
    return None, i


def _name_arg(text: str, i: int) -> tuple[str, int]:
    """The command a definition defines: `{\\name}` or `\\name`."""
    j = _skip_space(text, i)
    if j < len(text) and text[j] == "{":
        inner, k = _group(text, j)
        inner = inner.strip()
        if not COMMAND.fullmatch(inner):
            raise Unsupported("the defined name is not a single command")
        return inner, k
    m = COMMAND.match(text, j)
    if not m:
        raise Unsupported("a definition without a command name")
    return m.group(), m.end()


class Context:
    """The definitions the paper makes, read in the order TeX reads them, up to a position."""

    def __init__(self, root: Path, main: str):
        self.root = root
        self.main = main
        self.base = Path(main).parent
        self.defs: dict[str, Definition] = {}
        self.envs: dict[str, str] = {}          # environments the paper (re)defines
        self.inputs: list[str] = []
        self.list_labels = False
        self.problems: list[str] = []
        self.cond = 0                            # depth of TeX conditionals being read
        self.style = "plain"                     # the current \\theoremstyle
        self.theorems: dict[str, str] = {}       # theorem-like environments and their styles

    def resolve(self, name: str, exts: tuple[str, ...]) -> str | None:
        """A file of the snapshot that `\\input{name}` (or a package or class) names."""
        for ext in exts:
            rel = (self.base / (name if name.endswith(ext) else name + ext)).as_posix()
            try:
                if source_file(self.root, rel).is_file():
                    return rel
            except RegionError:
                return None
        return None

    def read(self, stop: tuple[str, int]) -> bool:
        """Read from the main file until `stop` (file, offset); whether it was reached."""
        self._stop = stop
        try:
            self._file(self.main, 0, [])
        except _Reached:
            return True
        return False

    def _define(self, d: Definition, scoped: bool):
        if self.cond:
            d.problem = d.problem or "it is defined inside a TeX conditional"
        if scoped:
            d.problem = d.problem or "it is defined inside a group, so its meaning at the passage is not known"
        self.defs[d.name] = d

    def _file(self, rel: str, depth: int, stack: list[str]):
        if rel in stack or len(stack) > 20:
            self.problems.append(f"{rel} is input recursively")
            return
        self.inputs.append(rel)
        text = source_file(self.root, rel).read_text(encoding="utf-8", errors="replace")
        if LIST_LABELS.search(text):
            self.list_labels = True
        stop = self._stop[1] if self._stop[0] == rel else None
        i = 0
        line_starts = [0] + [m.end() for m in re.finditer("\n", text)]

        def line_of(pos: int) -> int:
            lo, hi = 0, len(line_starts)
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if line_starts[mid] <= pos:
                    lo = mid
                else:
                    hi = mid
            return lo + 1

        while i < len(text):
            if stop is not None and i >= stop:
                raise _Reached()
            c = text[i]
            if c == "%":
                end = text.find("\n", i)
                i = end + 1 if end >= 0 else len(text)
                continue
            if c == "{":
                depth += 1
                i += 1
                continue
            if c == "}":
                depth -= 1
                if depth < 0:
                    self.problems.append(f"unbalanced braces in {rel}")
                    depth = 0
                i += 1
                continue
            if c != "\\":
                i += 1
                continue
            m = COMMAND.match(text, i)
            name = m.group()[1:]
            j = m.end()
            if stop is not None and stop < j:
                raise _Reached()
            try:
                if name in ("begin", "end"):
                    env, k = _group(text, j)
                    if name == "begin" and env in VERBATIM:
                        close = text.find("\\end{" + env + "}", k)
                        i = len(text) if close < 0 else close + len(env) + 6
                        continue
                    if env != "document":
                        depth += 1 if name == "begin" else -1
                        depth = max(depth, 0)
                    i = k
                    continue
                if name in ("begingroup", "bgroup"):
                    depth += 1
                elif name in ("endgroup", "egroup"):
                    depth = max(depth - 1, 0)
                elif name == "endinput":
                    return
                elif name == "theoremstyle":
                    arg, i = _group(text, j)
                    self.style = arg.strip()
                    continue
                elif name == "newif":
                    nm = COMMAND.match(text, _skip_space(text, j))
                    i = nm.end() if nm else j
                    continue
                elif name == "fi":
                    self.cond = max(self.cond - 1, 0)
                elif name.startswith("if"):
                    self.cond += 1
                elif name == "verb":
                    k = j + (1 if text[j:j + 1] == "*" else 0)
                    close = text.find(text[k], k + 1) if k < len(text) else -1
                    i = len(text) if close < 0 else close + 1
                    continue
                elif name in ("input", "include", "subfile", "InputIfFileExists"):
                    k = _skip_space(text, j)
                    if k < len(text) and text[k] == "{":
                        arg, k = _group(text, k)
                    else:
                        mm = re.compile(r"[^\s{}%\\]+").match(text, k)
                        arg, k = (mm.group(), mm.end()) if mm else ("", k)
                    found = self.resolve(arg.strip(), (".tex", "")) if arg.strip() else None
                    if found:
                        self._file(found, depth, stack + [rel])
                    elif name == "subfile":
                        self.problems.append(f"\\subfile{{{arg}}} is not read")
                    i = k
                    continue
                elif name in ("usepackage", "RequirePackage", "documentclass", "LoadClass"):
                    _, k = _optional(text, j)
                    arg, k = _group(text, k)
                    ext = ".cls" if name in ("documentclass", "LoadClass") else ".sty"
                    for pkg in (p.strip() for p in arg.split(",")):
                        found = pkg and self.resolve(pkg, (ext,))
                        if found:
                            self._file(found, 0, stack + [rel])
                    i = k
                    continue
                elif name in DEFINERS:
                    i = self._definition(name, text, j, depth > 0, rel, line_of(i))
                    continue
            except Unsupported as e:
                self.problems.append(f"{rel}:{line_of(i)}: {e}")
            i = j

    def _definition(self, name: str, text: str, j: int, scoped: bool, rel: str, line: int) -> int:
        star = j < len(text) and text[j] == "*"
        if star:
            j += 1
        if name in ("newcommand", "renewcommand", "providecommand", "DeclareRobustCommand"):
            cs, k = _name_arg(text, j)
            n, k = _optional(text, k)
            default, k = _optional(text, k)
            body, k = _group(text, k)
            params = int(n.strip()) if n and n.strip().isdigit() else 0
            d = Definition(cs, params, body, rel, line)
            if n is not None and not n.strip().isdigit():
                d.problem = "its number of arguments is not a number"
            elif default is not None:
                d.problem = "it has an optional argument"
            elif name == "providecommand" and cs not in self.defs:
                d.problem = "\\providecommand takes effect only if nothing else defines it"
            if name == "providecommand" and cs in self.defs:
                return k
            self._define(d, scoped)
            return k
        if name in ("def", "gdef", "edef", "xdef"):
            cs, k = _name_arg(text, j)
            brace = text.find("{", k)
            if brace < 0:
                raise Unsupported(f"\\{name}{cs} has no body")
            spec = text[k:brace]
            body, k = _group(text, brace)
            d = Definition(cs, 0, body, rel, line)
            if re.fullmatch(r"(#\d)*", spec):
                d.params = len(spec) // 2
                if spec != "".join(f"#{i + 1}" for i in range(d.params)):
                    d.problem = "its parameters are out of order"
            else:
                d.problem = "it has delimited parameters"
            if name in ("edef", "xdef"):
                d.problem = f"\\{name} expands its body when it is defined"
            self._define(d, scoped and name not in ("gdef", "xdef"))
            return k
        if name == "let":
            cs, k = _name_arg(text, j)
            k = _skip_space(text, k)
            if text[k:k + 1] == "=":
                k = _skip_space(text, k + 1)
            m = COMMAND.match(text, k)
            k = m.end() if m else k + 1
            self._define(Definition(cs, 0, "", rel, line, "it is defined with \\let"), scoped)
            return k
        if name == "DeclareMathOperator":
            cs, k = _name_arg(text, j)
            body, k = _group(text, k)
            op = "\\operatorname*" if star else "\\operatorname"
            self._define(Definition(cs, 0, op + "{" + body + "}", rel, line), scoped)
            return k
        if name in ("newenvironment", "renewenvironment"):
            env, k = _group(text, j)
            self.envs[env.strip()] = rel
            return k
        if name in ("newtheorem", "renewtheorem"):
            env, k = _group(text, j)
            self.theorems[env.strip()] = self.style
            return k
        # xparse definitions: their argument specifications are not interpreted.
        cs, k = _name_arg(text, j)
        self._define(Definition(cs, 0, "", rel, line, f"it is defined with \\{name}"), scoped)
        return k


class _Reached(Exception):
    pass


# -- labels and citations from the compiled .aux -------------------------------------------------

def read_aux(cwd: Path, stem: str) -> dict:
    """The labels (`\\newlabel`) and citation labels (`\\bibcite`) the compilation wrote, the
    files `\\@input` names included. A value that is not a single group of text is kept as
    None: its printed form is not known here."""
    labels, cites, seen = {}, {}, set()

    def first_group(s: str) -> str | None:
        try:
            g, _ = _group(s, 0)
        except Unsupported:
            return None
        return g

    def read(p: Path):
        if p in seen or not p.is_file():
            return
        seen.add(p)
        text = p.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"\\@input\{([^}]*)\}", text):
            read(cwd / m.group(1))
        for m in re.finditer(r"^\\newlabel\{([^}]*)\}", text, re.M):
            try:
                outer, _ = _group(text, m.end())
            except Unsupported:
                continue
            labels[m.group(1)] = first_group(outer)
        for m in re.finditer(r"^\\bibcite\{([^}]*)\}", text, re.M):
            try:
                value, _ = _group(text, m.end())
            except Unsupported:
                continue
            cites[m.group(1)] = None if "{" in value or "\\" in value else value
    read(cwd / f"{stem}.aux")
    return {"labels": labels, "cites": cites}


# -- the passage ---------------------------------------------------------------------------------

def tex_lines(raw: str) -> str:
    """The passage as TeX reads it: comments end with their line, leading spaces of a line are
    skipped, a line's end is a space and an empty line ends a paragraph (`\\n\\n`). A comment
    therefore never swallows the next line."""
    out, par = [], False
    for line in raw.split("\n"):
        s = line.rstrip("\r").lstrip(" \t")
        if not s.strip():
            par = True
            continue
        cut, k = None, 0
        while k < len(s):
            if s[k] == "\\":
                k += 2
                continue
            if s[k] == "%":
                cut = k
                break
            k += 1
        if par and out:
            out.append("\n\n")
        par = False
        if cut is not None:
            out.append(s[:cut])
        else:
            out.append(s.rstrip(" \t") + " ")
    return "".join(out).strip(" ")


class Passage:
    """Parse a passage into blocks the reader typesets; raise Unsupported on anything else."""

    def __init__(self, text: str, ctx: Context, aux: dict, macros: set[str]):
        self.s = text
        self.ctx = ctx
        self.aux = aux
        self.used = macros            # paper macros the mathematics uses
        self.refs: dict[str, str] = {}
        self.cites: dict[str, str] = {}

    def blocks(self, i: int = 0, stop=None) -> tuple[list, int]:
        """The paragraphs, displays and lists from `i` on, until `stop(i)` holds."""
        blocks, para = [], []

        def close():
            nonlocal para
            if para and "text" in para[0]:
                para[0] = {"text": para[0]["text"].lstrip(" ")}
            if para and "text" in para[-1]:
                para[-1] = {"text": para[-1]["text"].rstrip(" ")}
            para = [n for n in para if n.get("text", True)]
            if para:
                blocks.append({"p": para})
            para = []

        s = self.s
        while i < len(s):
            if stop and stop(i):
                break
            if s.startswith("\n\n", i):
                close()
                i += 2
                continue
            if s.startswith("$$", i) or s.startswith("\\[", i):
                closer = "$$" if s[i] == "$" else "\\]"
                end = self._find(closer, i + 2)
                close()
                blocks.append({"math": self.math(s[i + 2:end]), "display": True})
                i = end + 2
                continue
            if s[i] == "$" or s.startswith("\\(", i):
                closer, start = ("$", i + 1) if s[i] == "$" else ("\\)", i + 2)
                end = self._find(closer, start)
                para.append({"math": self.math(s[start:end])})
                i = end + len(closer)
                continue
            env = ENV.match(s, i)
            if env and env.group(1) == "begin":
                name = env.group(2)
                base = name.rstrip("*")
                if name in self.ctx.envs or base in self.ctx.envs:
                    raise Unsupported(f"the paper defines the environment {name}")
                if base in MATH_ENVS:
                    end, after = self._env_end(env.end(), name)
                    close()
                    blocks.append({"math": self.display(name, s[env.end():end]), "display": True})
                    i = after
                    continue
                if name in LISTS:
                    close()
                    item, i = self.list_block(name, env.end())
                    blocks.append(item)
                    continue
                raise Unsupported(f"the environment {name} is not supported")
            if env:
                raise Unsupported(f"\\end{{{env.group(2)}}} without its \\begin")
            node, i = self.inline(i)
            if node is not None:
                if node.get("par"):
                    close()
                elif node.get("text") == " " and (not para or para[-1].get("text", "").endswith(" ")):
                    pass
                elif "text" in node and para and "text" in para[-1]:
                    para[-1] = {"text": para[-1]["text"] + node["text"]}
                else:
                    para.append(node)
        close()
        return blocks, i

    def _find(self, closer: str, i: int) -> int:
        s = self.s
        while i < len(s):
            if s[i] == "\\":
                if s.startswith(closer, i):
                    return i
                i += 2
                continue
            if s.startswith(closer, i):
                return i
            if s.startswith("\n\n", i):
                raise Unsupported("a paragraph break inside mathematics")
            i += 1
        raise Unsupported(f"mathematics without its closing {closer}")

    def _env_end(self, start: int, name: str) -> tuple[int, int]:
        stack = [name]
        try:
            for op, env, a, b in environments(self.s, start):
                if op == "begin":
                    stack.append(env)
                elif stack.pop() != env:
                    raise Unsupported(f"mismatched \\end{{{env}}}")
                if not stack:
                    if "\n\n" in self.s[start:a]:
                        raise Unsupported("a paragraph break inside mathematics")
                    return a, b
        except (RegionError, IndexError):
            raise Unsupported(f"malformed environment {name}")
        raise Unsupported(f"the environment {name} has no matching end")

    def list_block(self, name: str, i: int) -> tuple[dict, int]:
        opt, j = _optional(self.s, i)
        if opt is not None:
            raise Unsupported(f"the {name} has options")
        end, after = self._env_end(i, name)
        body = self.s[:end]
        items, k = [], _skip_space(body, i)
        if not body.startswith("\\item", k):
            raise Unsupported(f"text before the first \\item of a {name}")
        while k < end:
            m = re.compile(r"\\item(?![A-Za-z])").match(body, k)
            if not m:
                raise Unsupported(f"malformed {name}")
            label, k = _optional(body, m.end())
            if label is None and name == "enumerate" and self.ctx.list_labels:
                raise Unsupported("the paper customises its list labels")
            sub = Passage(body, self.ctx, self.aux, self.used)
            sub.refs, sub.cites = self.refs, self.cites

            def at_next(p: int) -> bool:
                if body.startswith("\\item", p) and not body[p + 5:p + 6].isalpha():
                    return True
                return p >= end

            blocks, k = sub.blocks(k, at_next)
            if label is not None:
                label = self.plain(label)
            items.append({"label": label, "blocks": blocks})
        if name == "enumerate" and any(it["label"] is None for it in items) and \
                any(it["label"] is not None for it in items):
            raise Unsupported("an enumerate mixes explicit and automatic labels")
        return {"list": name, "items": items}, after

    def plain(self, text: str) -> str:
        """Text without mathematics or structure (a list label, a citation note)."""
        sub = Passage(text, self.ctx, self.aux, self.used)
        sub.refs, sub.cites = self.refs, self.cites
        blocks, _ = sub.blocks()
        out = []
        for b in blocks:
            for n in b.get("p", []):
                if set(n) != {"text"}:
                    raise Unsupported("a label or note with more than text")
                out.append(n["text"])
        return "".join(out)

    def inline(self, i: int):
        s = self.s
        c = s[i]
        if c == "{":
            body_end = self._brace_end(i)
            sub = Passage(s[i + 1:body_end], self.ctx, self.aux, self.used)
            sub.refs, sub.cites = self.refs, self.cites
            blocks, _ = sub.blocks()
            return self._inline_of(blocks, None), body_end + 1
        if c == "}":
            raise Unsupported("unbalanced braces")
        if c == "~":
            return {"text": "\u00a0"}, i + 1
        if c in "<>|\"":
            raise Unsupported(f"the character {c} prints differently in text")
        if c in "^_&#":
            raise Unsupported(f"the character {c} outside mathematics")
        if s.startswith("---", i):
            return {"text": "—"}, i + 3
        if s.startswith("--", i):
            return {"text": "–"}, i + 2
        if s.startswith("``", i):
            return {"text": "“"}, i + 2
        if s.startswith("''", i):
            return {"text": "”"}, i + 2
        if c == "`":
            return {"text": "‘"}, i + 1
        if c == "'":
            return {"text": "’"}, i + 1
        if c in " \t\n":
            return {"text": " "}, i + 1
        if c != "\\":
            return {"text": c}, i + 1
        m = COMMAND.match(s, i)
        cmd = m.group()
        j = m.end()
        word = cmd[1:]
        if LETTERS.fullmatch(word):
            k = j
            while k < len(s) and s[k] in " \t\n" and not s.startswith("\n\n", k):
                k += 1
            after = k
        else:
            after = j
        if cmd in self.ctx.defs:
            d = self.ctx.defs[cmd]
            if d.problem or d.body.strip():
                raise Unsupported(f"the paper defines {cmd}, used in the text")
            # A command that prints nothing (as `\\lean{…}` of a blueprint): its arguments
            # are read and nothing is shown, as TeX does.
            self.used.add(cmd)
            k = j
            for _ in range(d.params):
                _, k = _group(s, k)
            return None, (after if d.params == 0 else k)
        if cmd == "\\\\":
            k = j + (1 if s[j:j + 1] == "*" else 0)
            opt, k = _optional(s, k)
            if opt is not None:
                raise Unsupported("a line break with extra space")
            return {"br": True}, k
        if word in ESCAPES:
            return ({"text": ESCAPES[word]} if ESCAPES[word] else None), j
        if word == "par":
            return {"par": True}, after
        if word in INVISIBLE:
            return None, after
        if word in SYMBOLS:
            k = after
            if s.startswith("{}", k):
                k += 2
            return {"text": SYMBOLS[word]}, k
        if word in STYLES:
            arg, k = _group(s, j)
            sub = Passage(arg, self.ctx, self.aux, self.used)
            sub.refs, sub.cites = self.refs, self.cites
            blocks, _ = sub.blocks()
            return self._inline_of(blocks, STYLES[word]), k
        if word == "label":
            _, k = _group(s, j)
            return None, k
        if word in ("ref", "eqref"):
            key, k = _group(s, j)
            value = self.label(key.strip())
            return {"ref": value if word == "ref" else f"({value})", "key": key.strip()}, k
        if word == "cite":
            note, k = _optional(s, j)
            second, k2 = _optional(s, k)
            if second is not None:
                raise Unsupported("a citation with two optional arguments")
            keys, k = _group(s, k)
            nums = [self.cite(x.strip()) for x in keys.split(",") if x.strip()]
            if not nums:
                raise Unsupported("an empty citation")
            return {"cite": nums, "note": self.plain(note) if note else None,
                    "keys": [x.strip() for x in keys.split(",") if x.strip()]}, k
        raise Unsupported(f"the text command {cmd} is not supported")

    def _brace_end(self, i: int) -> int:
        depth, j = 0, i
        s = self.s
        while j < len(s):
            if s[j] == "\\":
                j += 2
                continue
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    return j
            j += 1
        raise Unsupported("unbalanced braces")

    @staticmethod
    def _inline_of(blocks: list, style: str | None) -> dict:
        if len(blocks) > 1 or any("p" not in b for b in blocks):
            raise Unsupported("a paragraph or display inside a text command")
        children = blocks[0]["p"] if blocks else []
        return {"style": style, "children": children}

    def label(self, key: str) -> str:
        value = self.aux["labels"].get(key, "missing")
        if value == "missing":
            raise Unsupported(f"the reference {key} is not resolved")
        if value is None or "\\" in value or "{" in value or not value.strip():
            raise Unsupported(f"the reference {key} prints TeX this reader does not typeset")
        self.refs[key] = value
        return value

    def cite(self, key: str) -> str:
        if key not in self.aux["cites"]:
            raise Unsupported(f"the citation {key} is not resolved")
        value = self.aux["cites"][key]
        if value is None:
            raise Unsupported(f"the citation {key} is printed by a bibliography style this reader does not reproduce")
        self.cites[key] = value
        return value

    # Mathematics -------------------------------------------------------------------------------

    def math(self, src: str) -> str:
        """Inline or unnumbered display mathematics, with its references resolved."""
        src = re.sub(r"\\label\s*\{[^{}]*\}", "", src)
        return self._refs_in_math(src)

    def _refs_in_math(self, src: str) -> str:
        def ref(m):
            value = self.label(m.group(2).strip())
            return "\\text{" + (value if m.group(1) == "ref" else f"({value})") + "}"
        src = re.sub(r"\\(ref|eqref)\s*\{([^{}]*)\}", ref, src)
        if re.search(r"\\(cite|cref|Cref|autoref|pageref|footnote)(?![A-Za-z])", src):
            raise Unsupported("a citation or cross-reference inside mathematics")
        for m in COMMAND.finditer(src):
            if m.group() in self.ctx.defs:
                self.used.add(m.group())
        return src

    def display(self, name: str, body: str) -> str:
        """A display environment as KaTeX typesets it, with the numbers the paper prints:
        a numbered row's `\\label` becomes `\\tag{number}`; a numbered row without a label (whose
        number is not recorded) is not supported."""
        base, starred = name.rstrip("*"), name.endswith("*")
        arg = ""
        if base == "alignat":
            n, k = _group(body, 0)
            arg, body = "{" + n + "}", body[k:]
        rows = self._rows(body) if base != "equation" else [body]
        out = []
        for row in rows:
            labels = re.findall(r"\\label\s*\{([^{}]*)\}", row)
            row = re.sub(r"\\label\s*\{[^{}]*\}", "", row)
            if starred or re.search(r"\\(nonumber|notag)(?![A-Za-z])", row):
                row = re.sub(r"\\(nonumber|notag)(?![A-Za-z])", "", row)
            elif re.search(r"\\tag\*?\s*\{", row):
                pass
            elif len(labels) == 1:
                row = row.rstrip() + " \\tag{" + self.label(labels[0].strip()) + "}"
            elif labels:
                raise Unsupported("a numbered row with several labels")
            else:
                raise Unsupported(f"a numbered {base} row without a label: its number is not recorded")
            out.append(self._refs_in_math(row))
        star = base + "*"
        return "\\begin{" + star + "}" + arg + "\\\\".join(out) + "\\end{" + star + "}"

    @staticmethod
    def _rows(body: str) -> list[str]:
        rows, depth, start, i = [], 0, 0, 0
        while i < len(body):
            c = body[i]
            if body.startswith("\\begin", i):
                depth += 1
                i += 6
                continue
            if body.startswith("\\end", i):
                depth -= 1
                i += 4
                continue
            if body.startswith("\\\\", i):
                if depth == 0:
                    rows.append(body[start:i])
                    start = i + 2
                i += 2
                continue
            if c == "\\":
                i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        last = body[start:]
        if last.strip() or not rows:
            rows.append(last)
        return rows


def macro_closure(ctx: Context, used: set[str]) -> dict[str, Definition]:
    """The paper's definitions the mathematics uses, and those their bodies use, as in effect at
    the passage."""
    out, todo = {}, list(used)
    while todo:
        name = todo.pop()
        if name in out or name not in ctx.defs:
            continue
        d = ctx.defs[name]
        out[name] = d
        todo += [m.group() for m in COMMAND.finditer(d.body) if m.group() in ctx.defs]
    return out


# -- selecting and building one excerpt ----------------------------------------------------------

def region_at(root: Path, file: str, start: int, end: int, kind: str) -> Region:
    text = source_file(root, file).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    sl = text.count("\n", 0, start) + 1
    el = text.count("\n", 0, end) + 1
    sc = start - (text.rfind("\n", 0, start) + 1) + 1
    ec = end - (text.rfind("\n", 0, end) + 1) + 1
    return Region(file, sl, el, sc, ec, kind, text[start:end],
                  tuple(l.rstrip("\r\n") for l in lines[sl - 1:el]))


def _offset(root: Path, region: Region) -> int:
    text = source_file(root, region.file).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    return sum(len(l) for l in lines[:region.start_line - 1]) + region.start_column - 1


def environment_body(root: Path, file: str, line: int, env: str) -> tuple[Region, str]:
    """The environment `env` opening on `line` of `file`: its region, and its body (after the
    optional title, up to its matching end) as raw text."""
    text = source_file(root, file).read_text(encoding="utf-8")
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    if not 1 <= line <= len(starts):
        raise RegionError("source line is outside the file")
    m = re.compile(r"\\begin\s*\{" + re.escape(env) + r"\}").search(text, starts[line - 1])
    if m is None or "\n" in text[starts[line - 1]:m.start()]:
        raise RegionError(f"no \\begin{{{env}}} on line {line}")
    stack = []
    for op, name, a, b in environments(text, m.start()):
        if op == "begin":
            stack.append(name)
        elif not stack or stack.pop() != name:
            raise RegionError("mismatched source environment")
        if not stack:
            _, k = _optional(text, m.end())
            return region_at(root, file, m.start(), b, "environment"), text[k:a]
    raise RegionError("source environment has no matching end")


def find_label(root: Path, files: list[str], key: str, envs: set[str]) -> Region:
    """The environment that carries `\\label{key}`: the innermost display or theorem-like
    environment around it. The label must occur exactly once in the files read."""
    hits = []
    pat = re.compile(r"\\label\s*\{" + re.escape(key) + r"\}")
    for f in dict.fromkeys(files):
        text = source_file(root, f).read_text(encoding="utf-8", errors="replace")
        for m in pat.finditer(text):
            line = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
            if "%" in line.replace("\\%", ""):
                continue
            hits.append((f, text, m.start()))
    if len(hits) != 1:
        raise RegionError(f"the label {key} occurs {len(hits)} times")
    f, text, pos = hits[0]
    stack = []
    for op, name, a, b in environments(text, 0):
        if a >= pos:
            break
        if op == "begin":
            stack.append((name, a))
        elif stack:
            stack.pop()
    for name, a in reversed(stack):
        if name.rstrip("*") in MATH_ENVS | {"multline", "flalign", "eqnarray"} or name in envs:
            depth = 0
            for op, n2, a2, b2 in environments(text, a):
                depth += 1 if op == "begin" else -1
                if depth == 0:
                    return region_at(root, f, a, b2, "environment")
            raise RegionError(f"the environment around {key} has no matching end")
    raise RegionError(f"the label {key} is not inside a display or a theorem")


def build_excerpt(root: Path, main: str, aux: dict, region: Region, body: str | None,
                  revision: str | None, selector: dict | None, env: str | None = None) -> dict:
    """One excerpt record: the region, its raw text, and either the parsed blocks with their
    rendering context (`ready`) or the reasons it cannot be typeset. `env` is the theorem-like
    environment whose body the passage is, if it is one: its style sets the body's shape."""
    raw = body if body is not None else region.text
    rec = {"scheme": SCHEME, "revision": revision, "file": region.file,
           "start_line": region.start_line, "end_line": region.end_line,
           "start_column": region.start_column, "end_column": region.end_column,
           "kind": region.kind, "selector": selector, "text": raw}
    ctx = Context(root, main)
    reasons = []
    reached = ctx.read((region.file, _offset(root, region)))
    used: set[str] = set()
    blocks, macros, refs, cites = None, {}, {}, {}
    if not reached:
        reasons.append("the passage is not part of the compiled document, so its macros are not known")
    else:
        if re.search(r"\\(" + "|".join(sorted(DEFINERS)) + r")(?![A-Za-z])", raw):
            reasons.append("the passage defines a macro")
        try:
            p = Passage(tex_lines(raw), ctx, aux, used)
            blocks, _ = p.blocks()
            refs, cites = p.refs, p.cites
            for name, d in sorted(macro_closure(ctx, used).items()):
                if d.problem:
                    reasons.append(f"{name} ({d.file}:{d.line}) cannot be used: {d.problem}")
                macros[name] = d.record()
            if not blocks:
                reasons.append("the passage is empty")
        except Unsupported as e:
            reasons.append(str(e))
        if ctx.problems:
            reasons.append("the paper's definitions could not all be read: " + ctx.problems[0])
    # amsthm's styles: a `plain` theorem's body is italic, `definition` and `remark` are upright;
    # another style is not known here.
    style = ctx.theorems.get(env) if env and reached else None
    rec.update(ready=not reasons, reasons=reasons, macros=macros, refs=refs, cites=cites,
               blocks=blocks if not reasons else None,
               body_style={"plain": "italic", "definition": "upright",
                           "remark": "upright"}.get(style or ""))
    rec["fingerprint"] = SCHEME + ":" + content_id(
        {k: rec[k] for k in ("scheme", "revision", "file", "start_line", "end_line",
                             "start_column", "end_column", "text", "macros", "refs", "cites",
                             "blocks", "body_style")})
    return rec


def error_record(message: str, selector: dict | None, revision: str | None) -> dict:
    return {"scheme": SCHEME, "revision": revision, "selector": selector, "ready": False,
            "reasons": [message], "text": None, "blocks": None, "fingerprint": None}


def excerpt_for(root: Path, main: str, aux: dict, revision: str | None, envs: set[str],
                anchor: dict | None, location: dict | None, selector) -> dict | None:
    """The excerpt of one claim: from its display selector (a label, or a location with an
    explicit end), else from its theorem-like environment, else from its audited region when that
    is a whole display or an explicitly bounded passage. None when there is nothing to show."""
    try:
        if selector is False:
            return None
        if isinstance(selector, dict):
            if set(selector) == {"label"} and isinstance(selector["label"], str):
                files = Context(root, main)
                files.read(("", -1))
                region = find_label(root, files.inputs, selector["label"], envs)
                body, env = None, None
                m = ENV.match(region.text)
                if m and m.group(2) in envs:
                    env = m.group(2)
                    region, body = environment_body(root, region.file, region.start_line, env)
                return build_excerpt(root, main, aux, region, body, revision, selector, env)
            if "location" in selector and set(selector) <= {"location", "end_line", "start_column",
                                                            "end_column"}:
                span = {k: v for k, v in selector.items() if k != "location"}
                claim = {"location": selector["location"], **({"source_region": span} if span else {})}
                return build_excerpt(root, main, aux, extract(root, claim), None, revision, selector)
            raise RegionError("an excerpt selector is {\"label\": …} or {\"location\": \"file:line\", "
                              "\"end_line\": …, \"end_column\": …}")
        if selector is not None:
            raise RegionError("an excerpt selector is an object, or false")
        if anchor and anchor.get("file") and anchor.get("line") and anchor.get("env"):
            region, body = environment_body(root, anchor["file"], anchor["line"], anchor["env"])
            return build_excerpt(root, main, aux, region, body, revision, None, anchor["env"])
        if location and location.get("kind") in ("environment", "span"):
            claim = {"location": f"{location['file']}:{location['start_line']}"}
            if location["kind"] == "span":
                claim["source_region"] = {"end_line": location["end_line"],
                                          "start_column": location["start_column"],
                                          "end_column": location["end_column"]}
            return build_excerpt(root, main, aux, extract(root, claim), None, revision, None)
        return None
    except (RegionError, Unsupported, OSError, UnicodeError) as e:
        return error_record(str(e), selector if isinstance(selector, dict) else None, revision)


def collect(claims: list[dict], paper: str, root: Path, main: str, aux: dict,
            revision: str | None, envs: list[str], anchors: list[dict], regions: dict,
            selectors: dict) -> dict:
    """The excerpt of every claim of `paper` that has one, by claim id. `selectors` holds the
    display overlay's `excerpt` entries by claim id."""
    from .assess import line_location, match_anchor
    out = {}
    for c in claims:
        if c["paper"] != paper:
            continue
        line_claim = line_location(c) is not None
        anchor = None if line_claim else match_anchor(c, anchors)
        rec = excerpt_for(root, main, aux, revision, set(envs), anchor,
                          regions.get(c["id"]) if line_claim else None, selectors.get(c["id"]))
        if rec is not None:
            out[c["id"]] = rec
    return out

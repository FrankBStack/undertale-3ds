#!/usr/bin/env python3
"""Which of the engine's builtin functions leave cached variable slots alone.

gmlaot.py keeps a pointer to each self/other/global variable it has looked up (see "Cached variable slots" in
engine/src/aot/vm_aot.h) and drops them all at anything that could insert a variable into an instance's map, change
which instance a scope refers to, or run GML (which can do either). A builtin call is one of those unless the builtin
can't reach any of that. This module works that out from the engine's sources, so the answer follows the engine:

  - every function defined in engine/src (and engine/src/physics) is read, with comments and string literals removed;
  - a function refers to every function whose name appears in its body other than as a struct field, called or not
    (so callbacks passed to qsort and the like count);
  - a builtin is pure when, following those references, it can't reach any of ROOTS: the functions that insert into a
    variable map, copy an instance's variables, create (with its events), copy or destroy an instance, change rooms,
    or run code or events. Making a struct isn't one: a new map moves no slot of an existing one.

That over-approximates (any mention counts, and same-named static functions are merged), which only ever makes a
builtin impure. Every doubt fails closed (impure, or an error), never open:

  - A builtin registered more than once (#if/#else arms) stands for every function registered under its name.
  - A registration that names a macro (#define NAME function, one per build variant, such as
    VMBUILTINS_PATH_ADD_POINT) stands for every function a #define gives it, and the C function of that name too
    when there is one (a one-sided #if redirect). #defines are read with comments removed and continuation lines
    joined, indented or not; a #define of that name whose body is anything but one function name (parentheses, an
    expression, ##, an empty body, parameters) makes the builtin impure.
  - Registrations an X-macro makes (PHYSICS_FUNCTIONS: VM_registerBuiltin(ctx, #name, builtin_##name) for each
    X(name, ...) of a list) are read like the others, so a name that isn't in audit() is no builtin.
  - A registration whose name is only known at run time (RUNTIME_NAMED) is listed by runtime_named(); any other form
    of VM_registerBuiltin call is an error, so a new kind can't slip past.
  - A builtin whose body isn't found (one defined by a macro body) is impure.
What it can't see is a call through a function pointer stored in a struct: those are the platform's renderer, audio,
file system and window callbacks, which run no GML and touch no instance.

Usage: builtin_audit.py [name ...]   prints, for each builtin (all registered ones by default), pure or why not.
"""
import glob
import os
import re
import sys

ENGINE_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "engine", "src")

ROOTS = frozenset((
    # inserting into a variable map
    "Instance_setSelfVar", "IntRValueHashMap_getOrInsertUndefined", "IntRValueHashMap_getOrInsertUndefinedFast",
    "IntRValueHashMap_clear", "vmScopeVarWriteSlot", "Instance_copyFields", "VM_structSet", "VM_structSetAndFreeVal",
    # creating, copying and destroying instances
    "Runner_createInstance", "Runner_createInstanceWithDepth", "Runner_createInstanceWithLayer",
    "Runner_copyInstance", "Runner_destroyInstance", "Runner_cleanupDestroyedInstances", "Runner_handlePendingRoomChange",
    # running code
    "VM_callCodeIndex", "VM_executeCode", "runScriptFrame", "runScriptFrameWith", "executeLoop",
    "Runner_executeEvent", "Runner_executeEventForAll", "Runner_executeEventFromObject",
))

_DEF = re.compile(r'^(?:static\s+)?(?:inline\s+)?(?:NOINLINE\s+)?(?:__attribute__\(\([^)]*\)\)\s+)?'
                  r'[A-Za-z_][A-Za-z_0-9\s\*]*?\b([A-Za-z_][A-Za-z_0-9]*)\s*\([^;]*$')
_STRIP = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)
_NAME = re.compile(r'(?<![.>\w])([A-Za-z_][A-Za-z_0-9]*)\b')   # not a struct field (a.x, a->x)
_REGISTER = re.compile(r'VM_registerBuiltin\(\s*ctx\s*,\s*"([^"]+)"\s*,\s*([A-Za-z_0-9]+)\s*\)')
_KEYWORDS = frozenset(("if", "while", "for", "switch", "return", "sizeof"))
# One #define of a logical line (comments removed, continuations joined): name, parameter list or None, body. Only
# spaces and tabs separate its parts, so an empty #define never takes the next line's first word.
_DEFINE = re.compile(r'^[ \t]*#[ \t]*define[ \t]+([A-Za-z_][A-Za-z_0-9]*)(\([^)\n]*\))?([^\n]*)$', re.M)
_IDENT = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
_COMMENTS = re.compile(r'//[^\n]*|/\*.*?\*/|("(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')', re.S)
_ANY_REGISTER = re.compile(r'\bVM_registerBuiltin\b')
# VM_registerBuiltin(ctx, #p, prefix##p) in the body of a function-like #define: an X-macro registration.
_PASTED = re.compile(r'VM_registerBuiltin\(\s*ctx\s*,\s*#\s*([A-Za-z_][A-Za-z_0-9]*)\s*,\s*([A-Za-z_0-9]*)\s*##\s*'
                     r'([A-Za-z_][A-Za-z_0-9]*)\s*\)')
# VM_registerBuiltin(ctx, <a name computed at run time>, function)
_RUNTIME = re.compile(r'VM_registerBuiltin\(\s*ctx\s*,\s*[^",()][^,()]*(?:\([^()]*\))?[^,()]*,\s*([A-Za-z_][A-Za-z_0-9]*)\s*\)')
# The registrations made under a name only known at run time, each read by hand. Each replaces a script it has
# matched by digest and runs that script itself for anything it doesn't handle (the wavers' and utrect's
# VM_callCodeIndex), or reads no instance (btnprompt), so a call by that name is the script's own behaviour.
# runtime_named() gives their verdicts; a new one is an error until it is read and added here.
RUNTIME_NAMED = frozenset(("btnpromptGetButtonSprite", "utfWaver", "utkWaver", "utrFill"))


def _sources(src):
    files = glob.glob(os.path.join(src, "*.c")) + glob.glob(os.path.join(src, "*.h")) + \
        glob.glob(os.path.join(src, "physics", "*.c"))
    # Not the desktop drivers: their main loops (loop.c's loop, which runs whole frames) and bench script would make
    # every builtin with a local called "loop" reach everything.
    return [f for f in sorted(files) if os.path.basename(f) not in ("bench_script.c", "loop.c")]


def _functions(files):
    """{name: [body, ...]}: a body runs from the definition's line to the first line that is just "}"."""
    funcs = {}
    for path in files:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            m = _DEF.match(line)
            if m and not line[:1].isspace() and not line.startswith(("#", "//", "}")) and m.group(1) not in _KEYWORDS:
                j = i
                while j < len(lines) and "{" not in lines[j] and ";" not in lines[j]:
                    j += 1
                if j < len(lines) and "{" in lines[j]:
                    k = j
                    while k < len(lines) and lines[k].rstrip() != "}" and not (k == j and lines[k].rstrip().endswith("}")):
                        k += 1
                    funcs.setdefault(m.group(1), []).append("\n".join(lines[i:k + 1]))
                    i = k + 1
                    continue
            i += 1
    return funcs


def _logical(path):
    """A source file's text with comments removed (string literals kept) and continuation lines joined."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    text = _COMMENTS.sub(lambda m: m.group(1) or " ", text)
    return re.sub(r"\\[ \t]*\r?\n", " ", text)


def _scan_registrations(files):
    """({builtin name: [each C function registered for it]}, [functions registered under a run-time name]).
    Raises ValueError for a VM_registerBuiltin call of any other form."""
    registered, runtime = {}, []

    def add(name, fn):
        registered.setdefault(name, [])
        if fn not in registered[name]:
            registered[name].append(fn)

    for path in files:
        text = _logical(path)
        all_defines = list(_DEFINE.finditer(text))
        defines = {m.group(1): m for m in all_defines}
        for m in _ANY_REGISTER.finditer(text):
            at = m.start()
            line_start = text.rfind("\n", 0, at) + 1
            line = text[line_start:text.find("\n", at) if "\n" in text[at:] else len(text)]
            head = line.lstrip()
            # its declaration, definition, #undef and the vm.h cast wrapper
            if re.match(r"(?:void\s+VM_registerBuiltin\b|#\s*undef\b|#\s*define\s+VM_registerBuiltin\b)", head):
                continue
            plain = _REGISTER.match(text, at)
            if plain:
                add(plain.group(1), plain.group(2))
                continue
            pasted = _PASTED.match(text, at)
            if pasted:
                param, prefix, pasted_param = pasted.groups()
                owner = next((d for d in all_defines if d.group(2) and d.start() <= at < d.end()), None)
                params = _IDENT.findall(owner.group(2)) if owner else []
                if owner is None or param != pasted_param or param not in params:
                    raise ValueError("%s: X-macro registration not read: %s" % (path, line.strip()))
                index = params.index(param)
                lists = re.findall(r"\b([A-Za-z_][A-Za-z_0-9]*)\(\s*%s\s*\)" % owner.group(1), text)
                if not lists:
                    raise ValueError("%s: X-macro %s is never expanded" % (path, owner.group(1)))
                for list_name in lists:
                    lst = defines.get(list_name)
                    if lst is None or not lst.group(2) or len(_IDENT.findall(lst.group(2))) != 1:
                        raise ValueError("%s: X-macro list %s not read" % (path, list_name))
                    x = _IDENT.findall(lst.group(2))[0]
                    entries = re.findall(r"\b%s\(([^()]*)\)" % x, lst.group(3))
                    if not entries:
                        raise ValueError("%s: X-macro list %s has no entries" % (path, list_name))
                    for entry in entries:
                        args = [a.strip() for a in entry.split(",")]
                        if len(args) <= index or not _IDENT.fullmatch(args[index]):
                            raise ValueError("%s: X-macro entry %s(%s) not read" % (path, x, entry))
                        add(args[index], prefix + args[index])
                continue
            dynamic = _RUNTIME.match(text, at)
            if dynamic and dynamic.group(1) in RUNTIME_NAMED:
                if dynamic.group(1) not in runtime:
                    runtime.append(dynamic.group(1))
                continue
            raise ValueError("%s: VM_registerBuiltin call not read (add its form to builtin_audit.py): %s"
                             % (path, line.strip()))
    return registered, runtime


def _registered(files):
    """{builtin name: [each C function VM_registerBuiltin registers for it]} (more than one under #if/#else)."""
    return _scan_registrations(files)[0]


def _macros(files):
    """({macro: [each function name a #define gives it]}, {macro: why a #define of it is no function name}), for the
    registrations that name a macro (_targets)."""
    macros, opaque = {}, {}
    for path in files:
        for m in _DEFINE.finditer(_logical(path)):
            name, params, body = m.group(1), m.group(2), m.group(3).strip()
            macros.setdefault(name, [])
            if params is None and _IDENT.fullmatch(body):
                if body not in macros[name]:
                    macros[name].append(body)
            else:
                opaque.setdefault(name, "#define %s%s %s" % (name, params or "", body))
    return macros, opaque


def _names(fn, macros):
    """fn and every name #defines of it lead to (the names whose #defines decide what fn stands for)."""
    out, todo = [], [fn]
    while todo:
        cur = todo.pop(0)
        if cur not in out:
            out.append(cur)
            todo.extend(macros.get(cur, []))
    return out


def _targets(fn, macros, funcs=None):
    """The functions a registration's name stands for: itself when it is a C function (or nothing else is known), and
    every function a #define of that name gives, followed through #defines of #defines."""
    out, todo, seen = [], [fn], set()
    while todo:
        cur = todo.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        given = macros.get(cur, [])
        if (funcs is not None and cur in funcs) or not given:
            out.append(cur)
        todo.extend(given)
    return out


def builtin_body_hashes(src=ENGINE_SRC):
    """{builtin name: SHA-1 (12 hex digits) of its function's body, comments and string literals removed and
    whitespace collapsed}, for builtins whose function has exactly one body. gmlaot.py inlines a copy of a few math
    builtins (INLINE_MATH) only while the engine's body still hashes to what the copy was made from."""
    import hashlib
    files = _sources(src)
    funcs = _functions(files)
    result = {}
    for name, fns in _registered(files).items():
        bodies = funcs.get(fns[0], []) if len(fns) == 1 else []
        if len(bodies) == 1:
            text = " ".join(_STRIP.sub(" ", bodies[0]).split())
            result[name] = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return result


def _reach(funcs):
    refs = {n: set(_NAME.findall(_STRIP.sub(" ", "\n".join(bodies)))) - {n} for n, bodies in funcs.items()}
    reach = set(ROOTS)
    changed = True
    while changed:
        changed = False
        for n, r in refs.items():
            if n not in reach and r & reach:
                reach.add(n)
                changed = True
    return refs, reach


def runtime_named(src=ENGINE_SRC):
    """{function registered under a run-time name: True when it is pure by the same reading as audit()}."""
    files = _sources(src)
    funcs = _functions(files)
    reach = _reach(funcs)[1]
    return {fn: fn in funcs and fn not in reach for fn in _scan_registrations(files)[1]}


def audit(src=ENGINE_SRC):
    """{builtin name: None when pure, else the chain of functions that reaches a root (or why it can't be read)}."""
    files = _sources(src)
    funcs = _functions(files)
    refs, reach = _reach(funcs)
    registered = _registered(files)
    macros, opaque = _macros(files)
    result = {}
    for name, regs in registered.items():
        targets = []
        for reg in regs:
            targets += [t for t in _targets(reg, macros, funcs) if t not in targets]
        dark = next((t for reg in regs for t in _names(reg, macros) if t in opaque), None)
        if dark is not None:
            result[name] = "%s: a #define that names no function (%s)" % (dark, opaque[dark])
            continue
        fn = next((t for t in targets if t not in funcs or t in reach), targets[0])
        if fn not in funcs:
            result[name] = "%s: no body found" % fn
        elif fn in reach:
            chain, cur, seen = [fn], fn, {fn}
            while cur not in ROOTS:
                nxt = sorted(c for c in refs.get(cur, ()) if c in reach and c not in seen)
                if not nxt:
                    break
                cur = nxt[0]
                seen.add(cur)
                chain.append(cur)
            result[name] = " > ".join(chain)
        else:
            result[name] = None
    return result


def pure_builtins(src=ENGINE_SRC):
    return frozenset(n for n, why in audit(src).items() if why is None)


if __name__ == "__main__":
    res = audit()
    names = sys.argv[1:] or sorted(res)
    for name in names:
        why = res.get(name, "not registered")
        print("%-36s %s" % (name, "pure" if why is None else why))
    if not sys.argv[1:]:
        print("%d of %d builtins pure" % (sum(1 for w in res.values() if w is None), len(res)), file=sys.stderr)

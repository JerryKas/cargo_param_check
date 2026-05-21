import json
import os
import re


class ParseError(Exception):
    def __init__(self, message, path=None, line=None, context=None):
        super(ParseError, self).__init__(message)
        self.path = path
        self.line = line
        self.context = context


def _remove_single_line_comment(line):
    pos_base = 0
    while True:
        slash_pos = line.find("//", pos_base)
        if slash_pos == -1:
            return line
        pos_base = slash_pos + 2
        if line.count('"', 0, pos_base) % 2 == 0:
            return line[:slash_pos]


def strip_json_comments(lines):
    out_lines = []
    multi_comment_start = False
    for raw in lines:
        line = raw
        if len(line) == 0:
            out_lines.append("")
            continue

        if not multi_comment_start:
            line = _remove_single_line_comment(line)
            if len(line) == 0:
                out_lines.append("")
                continue

        pos_start = line.find("/*")
        pos_end = line.find("*/")

        if pos_start != -1 and pos_end != -1 and pos_end > pos_start:
            line = line[:pos_start] + line[pos_end + 2 :]
            out_lines.append(line)
            continue

        if pos_start != -1:
            if multi_comment_start:
                out_lines.append("")
                continue
            multi_comment_start = True
            out_lines.append(line[:pos_start])
            continue

        if pos_end != -1:
            multi_comment_start = False
            out_lines.append(line[pos_end + 2 :])
            continue

        if multi_comment_start:
            out_lines.append("")
            continue

        out_lines.append(line)

    return "\n".join(out_lines)


def _no_duplicate_object_pairs_hook(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("duplicate key: %s" % k)
        out[k] = v
    return out


def _extract_error_line(message):
    m = re.search(r"line\s+(\d+)", message)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _read_text_file(path):
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "latin1"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read()
        except Exception as e:
            last_err = e
            continue
    raise last_err


def parse_json_file(path, context_lines=2):
    abs_path = os.path.abspath(path)
    try:
        raw_text = _read_text_file(abs_path)
    except Exception as e:
        raise ParseError("cannot read file: %s" % e, path=abs_path)

    raw_lines = raw_text.splitlines()
    stripped = strip_json_comments(raw_lines)

    try:
        parsed = json.loads(stripped, object_pairs_hook=_no_duplicate_object_pairs_hook)
    except Exception as e:
        msg = str(e)
        err_line = _extract_error_line(msg)
        ctx = None
        if err_line is not None and err_line >= 1:
            start = max(err_line - 1 - context_lines, 0)
            end = min(err_line - 1 + context_lines, len(raw_lines) - 1)
            parts = []
            for i in range(start, end + 1):
                parts.append("%d: %s" % (i + 1, raw_lines[i]))
            ctx = "\n".join(parts)
        raise ParseError(msg, path=abs_path, line=err_line, context=ctx)

    return parsed


def _is_leaf(v):
    return not isinstance(v, (dict, list))


def _parse_ignore_tokens(text):
    if not text:
        return []
    parts = []
    for raw in text.replace("\n", " ").split(","):
        s = raw.strip().strip('"').strip("'").strip()
        if not s:
            continue
        parts.append(s)
    return parts


def load_ignore_paths(path):
    abs_path = os.path.abspath(path)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        return {}
    tokens = _parse_ignore_tokens(text)
    out = {}
    for t in tokens:
        segs = []
        for s in str(t).split("."):
            s = s.strip()
            if not s:
                continue
            if s.isdigit():
                try:
                    segs.append(int(s))
                    continue
                except Exception:
                    pass
            segs.append(s)
        if segs:
            tup = tuple(segs)
            out.setdefault(tup[-1], []).append(tup)
    return out


def _should_ignore(path, ignore_paths):
    if not ignore_paths or not path:
        return False
    cand = ignore_paths.get(path[-1]) or []
    for t in cand:
        if len(path) >= len(t) and path[-len(t):] == t:
            return True
    return False


def build_diff_tree(base_val, other_val, ignore_paths=None, path=()):
    if _should_ignore(path, ignore_paths):
        return None
    if isinstance(base_val, dict) and isinstance(other_val, dict):
        keys = set(base_val.keys()) | set(other_val.keys())
        children = {}
        status = "unchanged"
        for k in sorted(keys, key=lambda x: str(x)):
            in_base = k in base_val
            in_other = k in other_val
            if (not in_base) and in_other:
                node = build_diff_tree(None, other_val[k], ignore_paths=ignore_paths, path=path + (k,))
                if node is None:
                    continue
                node["status"] = "added"
            elif in_base and (not in_other):
                node = build_diff_tree(base_val[k], None, ignore_paths=ignore_paths, path=path + (k,))
                if node is None:
                    continue
                node["status"] = "removed"
            else:
                node = build_diff_tree(base_val[k], other_val[k], ignore_paths=ignore_paths, path=path + (k,))
                if node is None:
                    continue
            children[k] = node
            if node["status"] != "unchanged":
                status = "changed"
        return {"type": "object", "status": status, "base": None, "other": None, "children": children}

    if isinstance(base_val, list) and isinstance(other_val, list):
        max_len = max(len(base_val), len(other_val))
        children = {}
        status = "unchanged"
        for i in range(max_len):
            in_base = i < len(base_val)
            in_other = i < len(other_val)
            if (not in_base) and in_other:
                node = build_diff_tree(None, other_val[i], ignore_paths=ignore_paths, path=path + (i,))
                if node is None:
                    continue
                node["status"] = "added"
            elif in_base and (not in_other):
                node = build_diff_tree(base_val[i], None, ignore_paths=ignore_paths, path=path + (i,))
                if node is None:
                    continue
                node["status"] = "removed"
            else:
                node = build_diff_tree(base_val[i], other_val[i], ignore_paths=ignore_paths, path=path + (i,))
                if node is None:
                    continue
            children[i] = node
            if node["status"] != "unchanged":
                status = "changed"
        return {"type": "array", "status": status, "base": None, "other": None, "children": children}

    if base_val is None and other_val is None:
        return {"type": "value", "status": "unchanged", "base": None, "other": None, "children": None}

    if base_val is None and other_val is not None:
        return {"type": "value" if _is_leaf(other_val) else ("array" if isinstance(other_val, list) else "object"),
                "status": "added",
                "base": None,
                "other": other_val,
                "children": None
                if _is_leaf(other_val)
                else build_diff_tree(
                    {} if isinstance(other_val, dict) else [],
                    other_val,
                    ignore_paths=ignore_paths,
                    path=path,
                )["children"]}

    if base_val is not None and other_val is None:
        return {"type": "value" if _is_leaf(base_val) else ("array" if isinstance(base_val, list) else "object"),
                "status": "removed",
                "base": base_val,
                "other": None,
                "children": None
                if _is_leaf(base_val)
                else build_diff_tree(
                    base_val,
                    {} if isinstance(base_val, dict) else [],
                    ignore_paths=ignore_paths,
                    path=path,
                )["children"]}

    if (isinstance(base_val, (dict, list)) and _is_leaf(other_val)) or (_is_leaf(base_val) and isinstance(other_val, (dict, list))):
        return {"type": "value", "status": "type_changed", "base": base_val, "other": other_val, "children": None}

    if base_val != other_val:
        return {"type": "value", "status": "modified", "base": base_val, "other": other_val, "children": None}

    return {"type": "value", "status": "unchanged", "base": base_val, "other": other_val, "children": None}


def diff_summary(tree):
    counts = {"added": 0, "removed": 0, "modified": 0, "type_changed": 0}

    def walk(node):
        st = node.get("status")
        if st in counts:
            counts[st] += 1
        ch = node.get("children")
        if isinstance(ch, dict):
            for _, c in ch.items():
                walk(c)

    walk(tree)
    counts["total"] = counts["added"] + counts["removed"] + counts["modified"] + counts["type_changed"]
    return counts


def _json_repr(v):
    try:
        return json.dumps(v, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(v)


def html_report(tree, base_title, other_title, meta=None):
    meta = meta or {}
    summary = diff_summary(tree)

    def esc(s):
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;")
                 .replace('"', "&quot;"))

    def node_to_html(key, node):
        st = node.get("status", "unchanged")
        label = esc(str(key))
        ch = node.get("children")
        if isinstance(ch, dict) and len(ch) > 0:
            items = []
            for ck in sorted(ch.keys(), key=lambda x: str(x)):
                items.append(node_to_html(ck, ch[ck]))
            inner = "\n".join(items)
            return (
                '<details class="node %s" open>'
                '<summary><span class="tag">%s</span><span class="k">%s</span></summary>'
                '<div class="children">%s</div>'
                "</details>"
            ) % (st, esc(st), label, inner)

        bv = node.get("base")
        ov = node.get("other")
        left = esc(_json_repr(bv)) if st in ("modified", "removed", "type_changed", "unchanged") else ""
        right = esc(_json_repr(ov)) if st in ("modified", "added", "type_changed", "unchanged") else ""
        return (
            '<div class="leaf node %s">'
            '<div class="row">'
            '<div class="cell key"><span class="tag">%s</span><span class="k">%s</span></div>'
            '<div class="cell base"><pre>%s</pre></div>'
            '<div class="cell other"><pre>%s</pre></div>'
            "</div>"
            "</div>"
        ) % (st, esc(st), label, left, right)

    root_children = tree.get("children") if isinstance(tree.get("children"), dict) else {}
    body_items = []
    for k in sorted(root_children.keys(), key=lambda x: str(x)):
        body_items.append(node_to_html(k, root_children[k]))
    body_html = "\n".join(body_items) if body_items else '<div class="empty">No differences</div>'

    title = "%s vs %s" % (base_title, other_title)
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>%s</title>
  <style>
    :root{
      --bg:#0b0e14;
      --panel:#0f1420;
      --line:#202a3e;
      --text:#e9eefc;
      --muted:#a8b4d8;
      --added:#3ddc84;
      --removed:#ff5a68;
      --modified:#ffcc66;
      --type:#7aa2ff;
      --shadow: 0 10px 35px rgba(0,0,0,.35);
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }
    *{box-sizing:border-box}
    body{margin:0;background:radial-gradient(1200px 800px at 20%% 10%%, rgba(122,162,255,.12), transparent 60%%),
                 radial-gradient(900px 700px at 80%% 20%%, rgba(61,220,132,.10), transparent 55%%),
                 radial-gradient(900px 700px at 60%% 90%%, rgba(255,90,104,.10), transparent 55%%),
                 var(--bg); color:var(--text); font-family:var(--sans)}
    header{position:sticky;top:0;z-index:2;backdrop-filter: blur(10px);
      background:linear-gradient(to bottom, rgba(11,14,20,.92), rgba(11,14,20,.70));
      border-bottom:1px solid rgba(32,42,62,.8)}
    .wrap{max-width:1200px;margin:0 auto;padding:18px 18px}
    h1{margin:0 0 8px 0; font-size:18px; letter-spacing:.2px}
    .meta{display:flex;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:12px}
    .pill{border:1px solid rgba(32,42,62,.9); background:rgba(15,20,32,.8); padding:6px 10px;border-radius:999px}
    .grid{display:grid; grid-template-columns: 1fr 1fr; gap:14px; margin-top:14px}
    .card{background:rgba(15,20,32,.76); border:1px solid rgba(32,42,62,.85); box-shadow:var(--shadow); border-radius:14px; overflow:hidden}
    .card h2{margin:0; padding:12px 14px; font-size:13px; color:var(--muted); border-bottom:1px solid rgba(32,42,62,.85)}
    .content{padding:12px 14px}
    .legend{display:flex; gap:10px; flex-wrap:wrap}
    .legend .i{display:flex; align-items:center; gap:8px}
    .dot{width:10px; height:10px; border-radius:3px}
    .dot.added{background:var(--added)} .dot.removed{background:var(--removed)}
    .dot.modified{background:var(--modified)} .dot.type_changed{background:var(--type)}
    main{max-width:1200px;margin:0 auto;padding:18px 18px 44px}
    details{border:1px solid rgba(32,42,62,.85); background:rgba(15,20,32,.62); border-radius:12px; margin:10px 0; overflow:hidden}
    summary{list-style:none; cursor:pointer; padding:10px 12px; display:flex; align-items:center; gap:10px}
    summary::-webkit-details-marker{display:none}
    .tag{font-family:var(--mono); font-size:11px; padding:2px 8px; border-radius:999px; border:1px solid rgba(255,255,255,.12); color:var(--muted)}
    .k{font-family:var(--mono); font-size:12px}
    .children{padding:0 12px 12px 12px}
    .leaf{border:1px solid rgba(32,42,62,.85); background:rgba(15,20,32,.62); border-radius:12px; margin:10px 0; overflow:hidden}
    .row{display:grid; grid-template-columns: 240px 1fr 1fr}
    .cell{padding:10px 12px; border-right:1px solid rgba(32,42,62,.85)}
    .cell:last-child{border-right:none}
    .cell.key{display:flex; align-items:center; gap:10px}
    pre{margin:0; white-space:pre-wrap; word-break:break-word; font-family:var(--mono); font-size:12px; color:var(--text)}
    .node.added summary .tag, .leaf.added .tag{border-color: rgba(61,220,132,.35); color: rgba(61,220,132,.95)}
    .node.removed summary .tag, .leaf.removed .tag{border-color: rgba(255,90,104,.35); color: rgba(255,90,104,.95)}
    .node.modified summary .tag, .leaf.modified .tag{border-color: rgba(255,204,102,.35); color: rgba(255,204,102,.95)}
    .node.type_changed summary .tag, .leaf.type_changed .tag{border-color: rgba(122,162,255,.35); color: rgba(122,162,255,.95)}
    .empty{color:var(--muted); padding:22px 10px; text-align:center; border:1px dashed rgba(32,42,62,.85); border-radius:12px}
    @media (max-width: 920px){
      .row{grid-template-columns: 1fr}
      .cell{border-right:none; border-bottom:1px solid rgba(32,42,62,.85)}
      .cell:last-child{border-bottom:none}
      .grid{grid-template-columns:1fr}
    }
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>%s</h1>
      <div class="meta">
        <div class="pill">BASE: %s</div>
        <div class="pill">OTHER: %s</div>
        <div class="pill">added=%d</div>
        <div class="pill">removed=%d</div>
        <div class="pill">modified=%d</div>
        <div class="pill">type_changed=%d</div>
        <div class="pill">total=%d</div>
      </div>
      <div class="grid">
        <div class="card">
          <h2>Legend</h2>
          <div class="content">
            <div class="legend">
              <div class="i"><span class="dot added"></span><span class="tag">added</span></div>
              <div class="i"><span class="dot removed"></span><span class="tag">removed</span></div>
              <div class="i"><span class="dot modified"></span><span class="tag">modified</span></div>
              <div class="i"><span class="dot type_changed"></span><span class="tag">type_changed</span></div>
            </div>
          </div>
        </div>
        <div class="card">
          <h2>Meta</h2>
          <div class="content">
            <pre>%s</pre>
          </div>
        </div>
      </div>
    </div>
  </header>
  <main>
    %s
  </main>
</body>
</html>
""" % (
        esc(title),
        esc(title),
        esc(str(base_title)),
        esc(str(other_title)),
        summary.get("added", 0),
        summary.get("removed", 0),
        summary.get("modified", 0),
        summary.get("type_changed", 0),
        summary.get("total", 0),
        esc(_json_repr(meta)),
        body_html,
    )

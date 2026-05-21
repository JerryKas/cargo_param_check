import os
import shlex
import subprocess
import sys
import time
import ctypes.util

from PyQt6.QtCore import QEvent, QObject, QRunnable, Qt, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QBrush, QColor, QPalette, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from jsondiff_engine import ParseError, build_diff_tree, diff_summary, html_report, load_ignore_paths, parse_json_file


APP_TITLE = "UOS JSON Diff"
PATH_ROLE = Qt.ItemDataRole.UserRole + 1
NAME_TO_UVIN = {
    "AET#55_GT": "tg45.outborder.car1",
    "AET#56_GT": "tg45.outborder.car2",
    "AET#57_GT": "tg45.outborder.car3",
    "AET#58_GT": "tg45.outborder.car4",
    "AET#59_GT": "tg45.outborder.car5",
    "AET#60_GT": "tg45.outborder.car6",
    "AET#71_GS": "t30_22.2ucvd32.car36",
    "AET#72_GS": "t30_22.2ucvd32.car37",
    "AET#73_GS": "t30_22.2ucvd32.car34",
    "AET#74_GS": "t30_22.2ucvd32.car35",
    "AET#75_GS": "t30_22.2ucvd32.car4",
    "AET#76_GS": "t30_22.2ucvd32.car9",
    "AET#77_GS": "t30_22.2ucvd32.car33",
    "AET#78_GS": "t30_22.2ucvd32.car38",
    "AET#79_GS": "t30_22.2ucvd32.car41",
    "AET#80_GS": "t30_22.2ucvd32.car42",
    "AET#1_GS": "t30_22.2ucvd32.car5",
}
UVIN_TO_NAME = {v: k for k, v in NAME_TO_UVIN.items()}


def _resource_path(rel_path):
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return os.path.join(getattr(sys, "_MEIPASS"), rel_path)
    return os.path.join(os.path.dirname(__file__), rel_path)


def _safe_basename(p):
    try:
        return os.path.basename(p)
    except Exception:
        return str(p)


def _short_path(p, max_len=84):
    if not p:
        return ""
    p = os.path.abspath(p)
    if len(p) <= max_len:
        return p
    head = p[: int(max_len * 0.35)]
    tail = p[-int(max_len * 0.55) :]
    return head + " … " + tail


def _json_files_in_folder(folder, recursive):
    out = []
    if recursive:
        for root, _, files in os.walk(folder):
            for n in files:
                if n.lower().endswith(".json"):
                    out.append(os.path.join(root, n))
        return sorted(out)
    try:
        names = os.listdir(folder)
    except Exception:
        return []
    for n in names:
        fp = os.path.join(folder, n)
        if os.path.isfile(fp) and fp.lower().endswith(".json"):
            out.append(fp)
    return sorted(out)

def _vehicle_name(parsed):
    try:
        v = parsed.get("_MOD_uos_config", {}).get("real_vehicle_name")
        if v is None:
            return ""
        return str(v)
    except Exception:
        return ""

def _safe_filename(name):
    out = []
    for ch in str(name):
        if ch.isalnum() or ch in ("-", "_", ".", " "):
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out).strip().replace(" ", "_")
    return s if s else "file"


def _rel_from_base(path, base_dir):
    if not path:
        return ""
    ap = os.path.abspath(path)
    if not base_dir:
        return os.path.basename(ap)
    try:
        rel = os.path.relpath(ap, os.path.abspath(base_dir))
        if rel.startswith(".."):
            return os.path.basename(ap)
        return rel
    except Exception:
        return os.path.basename(ap)


def _ensure_dir(dir_path):
    if not dir_path:
        return
    os.makedirs(dir_path, exist_ok=True)


def _linux_qt_platform_preflight():
    if sys.platform != "linux":
        return
    forced = os.environ.get("QT_QPA_PLATFORM", "").strip().lower()
    if forced and forced not in ("xcb",):
        return
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        return
    lib = ctypes.util.find_library("xcb-cursor") or ctypes.util.find_library("xcb_cursor")
    if lib:
        return
    sys.stderr.write(
        "\n".join(
            [
                "Qt xcb platform plugin 依赖缺失：libxcb-cursor0 / xcb-util-cursor",
                "",
                "请安装系统依赖后重试：",
                "  Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y libxcb-cursor0",
                "  Fedora/RHEL:   sudo dnf install -y xcb-util-cursor",
                "  Arch:         sudo pacman -S xcb-util-cursor",
                "  openSUSE:     sudo zypper install -y libxcb-cursor0",
                "",
            ]
        )
        + "\n"
    )
    raise SystemExit(1)


def _build_index_html(entries, base_title, base_path, exported_at):
    def esc(s):
        s = "" if s is None else str(s)
        return (
            s.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    tree = {"dirs": {}, "files": []}
    for e in entries:
        rel = e["rel_path"].replace("\\", "/")
        parts = [p for p in rel.split("/") if p]
        node = tree
        for d in parts[:-1]:
            node = node["dirs"].setdefault(d, {"dirs": {}, "files": []})
        node["files"].append(e)

    def node_summary(n):
        s = {"added": 0, "removed": 0, "modified": 0, "type_changed": 0, "total": 0}
        for f in n["files"]:
            for k in s.keys():
                s[k] += int(f["summary"].get(k, 0))
        for c in n["dirs"].values():
            cs = node_summary(c)
            for k in s.keys():
                s[k] += int(cs.get(k, 0))
        return s

    def render_node(name, n, depth=0):
        s = node_summary(n)
        header = '%s<span class="folder">%s</span><span class="sum">total=%d · +%d -%d ~%d T%d</span>' % (
            " " * (depth * 2),
            esc(name),
            s["total"],
            s["added"],
            s["removed"],
            s["modified"],
            s["type_changed"],
        )
        parts = []
        if name is not None:
            parts.append('<details class="dir" open><summary>%s</summary>' % header)
        parts.append('<div class="items">')
        for dn in sorted(n["dirs"].keys(), key=lambda x: x.lower()):
            parts.append(render_node(dn, n["dirs"][dn], depth + 1))
        for f in sorted(n["files"], key=lambda x: x["rel_path"].lower()):
            fs = f["summary"]
            parts.append(
                '<a class="file" href="%s"><span class="fname">%s</span>'
                '<span class="sum">total=%d · +%d -%d ~%d T%d</span></a>'
                % (
                    esc(f["report_rel"]),
                    esc(f["rel_path"].replace("\\", "/")),
                    int(fs.get("total", 0)),
                    int(fs.get("added", 0)),
                    int(fs.get("removed", 0)),
                    int(fs.get("modified", 0)),
                    int(fs.get("type_changed", 0)),
                )
            )
        parts.append("</div>")
        if name is not None:
            parts.append("</details>")
        return "\n".join(parts)

    root_sum = node_summary(tree)
    body = render_node(None, tree)
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>UOS JSON Diff Index</title>
  <style>
    :root{
      --bg:#0b0e14;
      --panel:#0f1420;
      --line:#202a3e;
      --text:#e9eefc;
      --muted:#a8b4d8;
      --shadow: 0 10px 35px rgba(0,0,0,.35);
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
      --add:#2bdc7c;
      --rm:#ff5a68;
      --mod:#ffcc66;
      --type:#7aa2ff;
    }
    *{box-sizing:border-box}
    body{margin:0;background:radial-gradient(1200px 800px at 20%% 10%%, rgba(122,162,255,.12), transparent 60%%),
                 radial-gradient(900px 700px at 80%% 20%%, rgba(43,220,124,.10), transparent 55%%),
                 radial-gradient(900px 700px at 60%% 90%%, rgba(255,90,104,.10), transparent 55%%),
                 var(--bg); color:var(--text); font-family:var(--sans)}
    header{position:sticky;top:0;z-index:2;backdrop-filter: blur(10px);
      background:linear-gradient(to bottom, rgba(11,14,20,.92), rgba(11,14,20,.70));
      border-bottom:1px solid rgba(32,42,62,.8)}
    .wrap{max-width:1200px;margin:0 auto;padding:18px 18px}
    h1{margin:0 0 10px 0; font-size:18px; letter-spacing:.2px}
    .meta{display:flex;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:12px}
    .pill{border:1px solid rgba(32,42,62,.9); background:rgba(15,20,32,.8); padding:6px 10px;border-radius:999px}
    main{max-width:1200px;margin:0 auto;padding:18px 18px 44px}
    .dir{border:1px solid rgba(32,42,62,.85); background:rgba(15,20,32,.62); border-radius:14px; margin:12px 0; overflow:hidden}
    summary{list-style:none; cursor:pointer; padding:10px 12px; display:flex; align-items:center; justify-content:space-between; gap:10px}
    summary::-webkit-details-marker{display:none}
    .folder{font-family:var(--mono); font-size:12px}
    .items{padding:8px 12px 12px 12px}
    .file{display:flex;justify-content:space-between;gap:10px;align-items:center;
      text-decoration:none;color:var(--text);padding:10px 10px;border:1px solid rgba(32,42,62,.65);
      border-radius:12px;margin:10px 0;background:rgba(15,20,32,.55)}
    .file:hover{border-color:rgba(47,59,86,.9);background:rgba(16,25,43,.65)}
    .fname{font-family:var(--mono);font-size:12px;word-break:break-all}
    .sum{font-family:var(--mono);font-size:11px;color:var(--muted)}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>UOS JSON Diff Index</h1>
      <div class="meta">
        <div class="pill">BASE: %s</div>
        <div class="pill">Base Path: %s</div>
        <div class="pill">Exported At: %s</div>
        <div class="pill">Files: %d</div>
        <div class="pill">Total Diffs: %d</div>
      </div>
    </div>
  </header>
  <main>
    %s
  </main>
</body>
</html>
""" % (
        esc(base_title),
        esc(base_path),
        esc(exported_at),
        len(entries),
        int(root_sum.get("total", 0)),
        body,
    )


class WorkerSignals(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(object)


class Worker(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self):
        try:
            res = self.fn()
        except Exception as e:
            self.signals.error.emit(e)
            return
        self.signals.finished.emit(res)


class _TabBarWheelScrollFilter(QObject):
    def __init__(self, tab_widget):
        super().__init__(tab_widget)
        self._tabs = tab_widget

    def _find_scroll_buttons(self):
        bar = self._tabs.tabBar()
        left_btn = None
        right_btn = None
        for b in bar.findChildren(QToolButton):
            try:
                arrow = b.arrowType()
            except Exception:
                continue
            if arrow == Qt.ArrowType.LeftArrow:
                left_btn = b
            elif arrow == Qt.ArrowType.RightArrow:
                right_btn = b
        return left_btn, right_btn

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel:
            return False

        delta = event.angleDelta()
        dx = delta.x()
        dy = delta.y()
        d = dx if abs(dx) > abs(dy) else dy
        if d == 0:
            return True

        left_btn, right_btn = self._find_scroll_buttons()
        if d < 0:
            if right_btn is not None and right_btn.isEnabled():
                right_btn.click()
        else:
            if left_btn is not None and left_btn.isEnabled():
                left_btn.click()
        return True



class Toast(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text, kind="info", duration_ms=2600):
        self._label.setText(text)
        bg = {"info": "#0f1420", "ok": "#0f1f18", "warn": "#201a10", "err": "#240f14"}.get(kind, "#0f1420")
        border = {"info": "#202a3e", "ok": "#1d5a3a", "warn": "#6b4a16", "err": "#6b1c2a"}.get(kind, "#202a3e")
        fg = "#e9eefc"
        self.setStyleSheet(
            "#Toast{background:%s;border:1px solid %s;border-radius:12px;}" % (bg, border)
            + "QLabel{color:%s;font-size:12px;}" % fg
        )
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._timer.start(duration_ms)

    def _place(self):
        p = self.parentWidget()
        if p is None:
            return
        geo = p.geometry()
        w = self.width()
        h = self.height()
        x = geo.x() + geo.width() - w - 18
        y = geo.y() + geo.height() - h - 18
        self.move(x, y)


class DiffView(QWidget):
    def __init__(self):
        super().__init__()
        self._diff_tree = None
        self._base_title = None
        self._other_title = None
        self._only_diff = True
        self._toast_fn = None
        self._search_matches = []
        self._search_pos = -1

        self._summary = QLabel("未对比")
        self._summary.setStyleSheet("color:#a8b4d8;font-size:12px;")

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索字段名/路径，例如 [a][b][0] 或 real_vehicle_name")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_text_changed)
        self._search.returnPressed.connect(self.find_next)

        self._prev_btn = QPushButton("上一个")
        self._next_btn = QPushButton("下一个")
        self._prev_btn.clicked.connect(self.find_prev)
        self._next_btn.clicked.connect(self.find_next)

        self._match_info = QLabel("")
        self._match_info.setStyleSheet("color:#a8b4d8;font-size:12px;")

        self._expand_btn = QPushButton("全部展开")
        self._collapse_btn = QPushButton("全部折叠")
        self._expand_btn.clicked.connect(self.expand_all)
        self._collapse_btn.clicked.connect(self.collapse_all)

        top = QHBoxLayout()
        top.addWidget(self._summary)
        top.addSpacing(10)
        top.addWidget(self._search, 1)
        top.addWidget(self._match_info)
        top.addWidget(self._prev_btn)
        top.addWidget(self._next_btn)
        top.addStretch(1)
        top.addWidget(self._expand_btn)
        top.addWidget(self._collapse_btn)

        self._tree = QTreeView()
        self._tree.setAlternatingRowColors(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setHeaderHidden(False)
        self._tree.doubleClicked.connect(self._on_double_click)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addLayout(top)
        lay.addWidget(self._tree)

        self._model = QStandardItemModel(0, 5, self)
        self._model.setHorizontalHeaderLabels(["字段", "徽标", "类型", "基准值", "对比值"])
        self._tree.setModel(self._model)
        self._tree.setColumnWidth(0, 300)
        self._tree.setColumnWidth(1, 70)
        self._tree.setColumnWidth(2, 110)
        self._tree.setColumnWidth(3, 360)
        self._tree.setColumnWidth(4, 360)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._update_search)

    def set_only_diff(self, only_diff):
        self._only_diff = bool(only_diff)
        if self._diff_tree is not None:
            self.render(self._diff_tree, self._base_title, self._other_title)

    def set_toast(self, toast_fn):
        self._toast_fn = toast_fn

    def clear(self, text="未对比"):
        self._diff_tree = None
        self._base_title = None
        self._other_title = None
        self._summary.setText(text)
        self._match_info.setText("")
        self._search_matches = []
        self._search_pos = -1
        self._model.removeRows(0, self._model.rowCount())

    def render(self, diff_tree, base_title, other_title):
        self._diff_tree = diff_tree
        self._base_title = base_title
        self._other_title = other_title

        self._model.removeRows(0, self._model.rowCount())
        s = diff_summary(diff_tree)
        self._summary.setText(
            "added=%d  removed=%d  modified=%d  type_changed=%d  total=%d"
            % (s["added"], s["removed"], s["modified"], s["type_changed"], s["total"])
        )

        def color_for(status):
            if status == "added":
                return QColor("#2bdc7c")
            if status == "removed":
                return QColor("#ff5a68")
            if status == "modified":
                return QColor("#ffcc66")
            if status == "type_changed":
                return QColor("#7aa2ff")
            if status == "changed":
                return QColor("#c792ea")
            return QColor("#a8b4d8")

        def badge_for(status):
            if status == "added":
                return "+"
            if status == "removed":
                return "-"
            if status == "modified":
                return "~"
            if status == "type_changed":
                return "T"
            if status == "changed":
                return "Δ"
            return ""

        def pretty(v):
            if v is None:
                return ""
            try:
                import json as _json
                return _json.dumps(v, ensure_ascii=False, sort_keys=True)
            except Exception:
                return str(v)

        def should_keep(node):
            st = node.get("status", "unchanged")
            if not self._only_diff:
                return True
            if st != "unchanged":
                return True
            ch = node.get("children")
            if isinstance(ch, dict):
                for c in ch.values():
                    if should_keep(c):
                        return True
            return False

        def add_items(parent_item, key, node, path_str):
            if not should_keep(node):
                return
            st = node.get("status", "unchanged")
            base_v = node.get("base")
            other_v = node.get("other")
            ch = node.get("children")

            k_item = QStandardItem(str(key))
            badge_item = QStandardItem(badge_for(st))
            s_item = QStandardItem(st)
            b_item = QStandardItem(pretty(base_v))
            o_item = QStandardItem(pretty(other_v))

            c = color_for(st)
            k_item.setData(path_str, PATH_ROLE)
            badge_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            badge_item.setBackground(QBrush(QColor(c.red(), c.green(), c.blue(), 26)))
            for it in (k_item, badge_item, s_item, b_item, o_item):
                it.setEditable(False)
                it.setForeground(c)
                it.setData(st, Qt.ItemDataRole.UserRole)

            row = [k_item, badge_item, s_item, b_item, o_item]
            if parent_item is None:
                self._model.appendRow(row)
            else:
                parent_item.appendRow(row)

            if isinstance(ch, dict) and len(ch) > 0:
                for ck in sorted(ch.keys(), key=lambda x: str(x)):
                    child_path = path_str + ("[%s]" % ck)
                    add_items(k_item, ck, ch[ck], child_path)

        root_children = diff_tree.get("children") if isinstance(diff_tree.get("children"), dict) else {}
        for k in sorted(root_children.keys(), key=lambda x: str(x)):
            add_items(None, k, root_children[k], "[%s]" % k)

        self._tree.expandToDepth(2)
        self._update_search()

    def expand_all(self):
        self._tree.expandAll()

    def collapse_all(self):
        self._tree.collapseAll()

    def _toast(self, text, kind="info"):
        if self._toast_fn:
            self._toast_fn(text, kind=kind)

    def _on_double_click(self, index):
        if not index.isValid():
            return
        key_index = index.siblingAtColumn(0)
        item = self._model.itemFromIndex(key_index)
        if item is None:
            return
        path = item.data(PATH_ROLE)
        if not path:
            return
        QApplication.clipboard().setText(str(path))
        self._toast("已复制路径：%s" % path, kind="ok")

    def _on_search_text_changed(self, _):
        self._search_timer.start(220)

    def _update_search(self):
        q = self._search.text().strip()
        self._search_matches = []
        self._search_pos = -1
        if not q:
            self._match_info.setText("")
            return
        ql = q.lower()

        def walk(parent_index):
            rows = self._model.rowCount(parent_index)
            for r in range(rows):
                idx = self._model.index(r, 0, parent_index)
                item = self._model.itemFromIndex(idx)
                if item is None:
                    continue
                key = item.text()
                path = item.data(PATH_ROLE) or ""
                if (ql in key.lower()) or (ql in str(path).lower()):
                    self._search_matches.append(idx)
                walk(idx)

        walk(self._model.invisibleRootItem().index())
        if not self._search_matches:
            self._match_info.setText("0/0")
            return
        self._search_pos = 0
        self._match_info.setText("%d/%d" % (self._search_pos + 1, len(self._search_matches)))
        self._goto_match(self._search_pos)

    def _goto_match(self, pos):
        if not self._search_matches:
            return
        if pos < 0 or pos >= len(self._search_matches):
            return
        idx = self._search_matches[pos]
        p = idx.parent()
        while p.isValid():
            self._tree.expand(p)
            p = p.parent()
        self._tree.scrollTo(idx, QTreeView.ScrollHint.PositionAtCenter)
        sel = self._tree.selectionModel()
        sel.clearSelection()
        sel.select(idx, sel.SelectionFlag.Select | sel.SelectionFlag.Rows)
        self._tree.setCurrentIndex(idx)

    def find_next(self):
        if not self._search_matches:
            self._update_search()
            return
        self._search_pos = (self._search_pos + 1) % len(self._search_matches)
        self._match_info.setText("%d/%d" % (self._search_pos + 1, len(self._search_matches)))
        self._goto_match(self._search_pos)

    def find_prev(self):
        if not self._search_matches:
            self._update_search()
            return
        self._search_pos = (self._search_pos - 1) % len(self._search_matches)
        self._match_info.setText("%d/%d" % (self._search_pos + 1, len(self._search_matches)))
        self._goto_match(self._search_pos)

    def export_payload(self):
        return self._diff_tree, self._base_title, self._other_title


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1180, 780)

        self._thread_pool = QThreadPool.globalInstance()
        self._toast = Toast(self)
        self._workers = set()

        self.folder_path = None
        self.base_path = None
        self.base_data = None
        self.base_title = None
        self.valid_files = {}
        self.invalid_files = {}
        self.diff_cache = {}

        self._only_diff = True
        self._ignore_default = True
        self._ignore_file = _resource_path("default_ignore_configs.txt")
        self._ignore_paths = load_ignore_paths(self._ignore_file)
        self._build_ui()
        self._apply_theme()

    def _apply_theme(self):
        p = self.palette()
        p.setColor(QPalette.ColorRole.Window, QColor("#0b0e14"))
        p.setColor(QPalette.ColorRole.Base, QColor("#0f1420"))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor("#10192b"))
        p.setColor(QPalette.ColorRole.Text, QColor("#e9eefc"))
        p.setColor(QPalette.ColorRole.WindowText, QColor("#e9eefc"))
        p.setColor(QPalette.ColorRole.Button, QColor("#0f1420"))
        p.setColor(QPalette.ColorRole.ButtonText, QColor("#e9eefc"))
        self.setPalette(p)

        self.setStyleSheet(
            "QMainWindow{background:#0b0e14;}"
            "QLabel{color:#e9eefc;}"
            "QPushButton{background:#0f1420;border:1px solid #202a3e;border-radius:10px;padding:8px 12px;}"
            "QPushButton:hover{border-color:#2f3b56;}"
            "QPushButton:pressed{background:#0c111b;}"
            "QCheckBox{color:#e9eefc;}"
            "QTabWidget::pane{border:1px solid #202a3e;border-radius:12px;}"
            "QTabBar::tab{background:#0f1420;border:1px solid #202a3e;border-bottom:none;border-top-left-radius:10px;border-top-right-radius:10px;padding:8px 12px;margin-right:6px;color:#a8b4d8;}"
            "QTabBar::tab:selected{color:#e9eefc;border-color:#2f3b56;background:#10192b;}"
            "QHeaderView::section{background:#0b0e14;color:#a8b4d8;border:1px solid #202a3e;padding:6px;}"
            "QTableWidget{background:#0f1420;border:1px solid #202a3e;border-radius:12px;gridline-color:#202a3e;}"
            "QTreeView{background:#0f1420;border:1px solid #202a3e;border-radius:12px;alternate-background-color:#10192b;}"
        )

    def _build_ui(self):
        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        select_folder_act = QAction("选择JSON文件夹", self)
        select_folder_act.triggered.connect(self.select_folder)
        toolbar.addAction(select_folder_act)

        select_base_act = QAction("选择基准JSON文件", self)
        select_base_act.triggered.connect(self.select_base)
        toolbar.addAction(select_base_act)

        toolbar.addSeparator()

        self.only_diff_box = QCheckBox("仅显示差异")
        self.only_diff_box.setChecked(True)
        self.only_diff_box.stateChanged.connect(self._toggle_only_diff)
        toolbar.addWidget(self.only_diff_box)

        self.recursive_box = QCheckBox("递归扫描")
        self.recursive_box.setChecked(True)
        toolbar.addWidget(self.recursive_box)

        self.ignore_box = QCheckBox("忽略默认参数")
        self.ignore_box.setChecked(True)
        self.ignore_box.stateChanged.connect(self._toggle_ignore_default)
        toolbar.addWidget(self.ignore_box)

        toolbar.addSeparator()

        self.open_act = QAction("打开", self)
        self.open_act.setEnabled(False)
        self.open_act.triggered.connect(self.open_selected_in_vim)
        toolbar.addAction(self.open_act)

        export_cur_act = QAction("导出当前HTML", self)
        export_cur_act.triggered.connect(self.export_current_html)
        toolbar.addAction(export_cur_act)

        export_all_act = QAction("导出全部HTML", self)
        export_all_act.triggered.connect(self.export_all_html)
        toolbar.addAction(export_all_act)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        info = QFrame()
        info.setStyleSheet("QFrame{background:#0f1420;border:1px solid #202a3e;border-radius:12px;}")
        info_lay = QVBoxLayout(info)
        info_lay.setContentsMargins(12, 10, 12, 10)
        info_lay.setSpacing(12)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        row1.addWidget(QLabel("文件夹："))
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("输入文件夹路径，回车加载")
        self.folder_input.returnPressed.connect(self.load_folder_from_input)
        row1.addWidget(self.folder_input, 1)
        self.folder_browse_btn = QPushButton("浏览…")
        self.folder_browse_btn.clicked.connect(self.select_folder)
        row1.addWidget(self.folder_browse_btn)
        info_lay.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        row2.addWidget(QLabel("基准："))
        self.base_input = QLineEdit()
        self.base_input.setPlaceholderText("输入基准 JSON 文件路径，回车加载")
        self.base_input.returnPressed.connect(self.load_base_from_input)
        row2.addWidget(self.base_input, 1)
        self.base_browse_btn = QPushButton("浏览…")
        self.base_browse_btn.clicked.connect(self.select_base)
        row2.addWidget(self.base_browse_btn)
        info_lay.addLayout(row2)
        layout.addWidget(info)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        self.files_table = QTableWidget(0, 7)
        self.files_table.setHorizontalHeaderLabels(["文件", "状态", "基准", "name", "uvin", "文件路径", "说明"])
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.files_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.files_table.setSortingEnabled(False)
        self.files_table.horizontalHeader().setStretchLastSection(True)
        self.files_table.setColumnWidth(0, 260)
        self.files_table.setColumnWidth(1, 90)
        self.files_table.setColumnWidth(2, 70)
        self.files_table.setColumnWidth(3, 120)
        self.files_table.setColumnWidth(4, 240)
        self.files_table.setColumnWidth(5, 360)
        splitter.addWidget(self.files_table)
        self.files_table.itemSelectionChanged.connect(self._on_table_selection_changed)

        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideNone)
        self._tabbar_wheel_filter = _TabBarWheelScrollFilter(self.tabs)
        self.tabs.tabBar().installEventFilter(self._tabbar_wheel_filter)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self._rebuild_tabs()

    def toast(self, text, kind="info"):
        self._toast.show_message(text, kind=kind)

    def _tab_title_for_file(self, fp):
        parsed = self.valid_files.get(fp)
        uvin = _vehicle_name(parsed) if parsed is not None else ""
        name = UVIN_TO_NAME.get(uvin, "")
        if name:
            return name
        return _rel_from_base(fp, self.folder_path).replace("\\", "/")

    def _on_table_selection_changed(self):
        try:
            has_sel = self.files_table.currentRow() >= 0
        except Exception:
            has_sel = False
        self.open_act.setEnabled(bool(has_sel))

    def open_selected_in_vim(self):
        row = self.files_table.currentRow()
        if row < 0:
            self.toast("请先选择一个文件", kind="warn")
            return
        self._open_row_in_vim(row)

    def _open_row_in_vim(self, row):
        path_item = self.files_table.item(row, 5)
        fp = path_item.text().strip() if path_item else ""
        if not fp:
            self.toast("无法获取文件路径", kind="err")
            return
        fp = os.path.abspath(fp)
        if not os.path.isfile(fp):
            self.toast("文件不存在：%s" % _short_path(fp), kind="err")
            return
        if self._open_in_terminal_vim(fp):
            self.toast("已在终端打开：%s" % _short_path(fp), kind="ok")
        else:
            self.toast("无法启动终端，请手动执行：vim %s" % _short_path(fp), kind="err")

    def _open_in_terminal_vim(self, path):
        cmd = "vim %s" % shlex.quote(path)
        try:
            if sys.platform == "darwin":
                subprocess.Popen(
                    ["osascript", "-e", 'tell application "Terminal" to do script "%s"' % cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            terminals = [
                ["x-terminal-emulator", "-e"],
                ["gnome-terminal", "--"],
                ["konsole", "-e"],
                ["xfce4-terminal", "-e"],
                ["xterm", "-e"],
            ]
            for base in terminals:
                try:
                    subprocess.Popen(base + ["bash", "-lc", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    return True
                except FileNotFoundError:
                    continue
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _with_progress(self, label):
        dlg = QDialog(self)
        dlg.setModal(True)
        dlg.setWindowTitle("")
        dlg.setFixedSize(360, 110)
        dlg.setStyleSheet("QDialog{background:#0f1420;border:1px solid #202a3e;border-radius:12px;}")
        v = QVBoxLayout(dlg)
        v.setContentsMargins(14, 14, 14, 14)
        msg = QLabel(label)
        msg.setStyleSheet("color:#e9eefc;")
        v.addWidget(msg)
        sub = QLabel("请稍候…")
        sub.setStyleSheet("color:#a8b4d8;font-size:12px;")
        v.addWidget(sub)
        dlg.show()
        return dlg

    def _run_async(self, label, fn, on_ok):
        prog = self._with_progress(label)

        def ok(res):
            prog.close()
            try:
                self._workers.discard(w)
            except Exception:
                pass
            on_ok(res)

        def err(e):
            prog.close()
            try:
                self._workers.discard(w)
            except Exception:
                pass
            self._handle_error(e)

        w = Worker(fn)
        w.signals.finished.connect(ok)
        w.signals.error.connect(err)
        self._workers.add(w)
        self._thread_pool.start(w)

    def _handle_error(self, e):
        if isinstance(e, ParseError):
            msg = str(e)
            if getattr(e, "line", None):
                msg = "line %s: %s" % (e.line, msg)
            if getattr(e, "context", None):
                msg = msg + "\n" + e.context
            self.toast("解析失败：%s\n%s" % (_safe_basename(e.path), msg), kind="err")
            return
        self.toast("发生异常：%s" % e, kind="err")

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含待对比JSON的文件夹")
        if not folder:
            self.toast("已取消选择文件夹", kind="warn")
            return
        self.folder_input.setText(os.path.abspath(folder))
        self.load_folder_from_input()

    def load_folder_from_input(self):
        folder = self.folder_input.text().strip()
        if not folder:
            self.toast("请输入文件夹路径", kind="warn")
            return
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            self.toast("无效文件夹：%s" % _short_path(folder), kind="err")
            return
        self.folder_path = folder

        recursive = bool(self.recursive_box.isChecked())

        def job():
            valid = {}
            invalid = {}
            files = _json_files_in_folder(folder, recursive)
            for fp in files:
                try:
                    data = parse_json_file(fp)
                    valid[fp] = data
                except ParseError as pe:
                    invalid[fp] = pe
                except Exception as ex:
                    invalid[fp] = ParseError(str(ex), path=fp)
            return valid, invalid

        def done(res):
            valid, invalid = res
            self.valid_files = valid
            self.invalid_files = invalid
            self._render_validation_table()
            self._rebuild_tabs()
            if invalid:
                self.toast("发现 %d 个无效JSON（已标红）" % len(invalid), kind="warn")
            else:
                self.toast("文件夹内JSON全部合法", kind="ok")
            if self.base_data is not None:
                self._compute_all_diffs()

        self._run_async("正在校验JSON文件…", job, done)

    def select_base(self):
        fp, _ = QFileDialog.getOpenFileName(self, "选择基准JSON文件", "", "JSON (*.json);;All Files (*)")
        if not fp:
            self.toast("已取消选择基准文件", kind="warn")
            return
        self.base_input.setText(os.path.abspath(fp))
        self.load_base_from_input()

    def load_base_from_input(self):
        fp = self.base_input.text().strip()
        if not fp:
            self.toast("请输入基准文件路径", kind="warn")
            return
        fp = os.path.abspath(fp)
        if not os.path.isfile(fp):
            self.toast("无效文件：%s" % _short_path(fp), kind="err")
            return
        if not fp.lower().endswith(".json"):
            self.toast("请选择 .json 文件", kind="warn")
            return

        def job():
            data = parse_json_file(fp)
            return fp, data

        def done(res):
            base_fp, data = res
            self.base_path = base_fp
            self.base_data = data
            self.base_title = _safe_basename(base_fp)
            self.toast("基准文件已加载", kind="ok")
            if self.valid_files or self.invalid_files:
                self._render_validation_table()
            self._rebuild_tabs()
            if self.valid_files:
                self._compute_all_diffs()

        self._run_async("正在解析基准JSON…", job, done)

    def _render_validation_table(self):
        files = set(list(self.valid_files.keys()) + list(self.invalid_files.keys()))
        if self.base_path:
            files.add(os.path.abspath(self.base_path))

        def sort_key(x):
            is_base = bool(self.base_path and os.path.abspath(x) == os.path.abspath(self.base_path))
            return (0 if is_base else 1, _rel_from_base(x, self.folder_path).lower())

        files = sorted(files, key=sort_key)
        self.files_table.setRowCount(len(files))
        base_row = -1
        for r, fp in enumerate(files):
            name = _rel_from_base(fp, self.folder_path)
            is_ok = fp in self.valid_files
            status = "合法" if is_ok else "无效"
            is_base = bool(self.base_path and os.path.abspath(fp) == os.path.abspath(self.base_path))
            base_mark = "是" if is_base else ""
            if is_base and base_row == -1:
                base_row = r
            car_name = ""
            uvin = ""
            desc = ""
            if not is_ok:
                pe = self.invalid_files.get(fp)
                desc = str(pe) if pe is not None else "parse error"
                if getattr(pe, "line", None):
                    desc = "line %s: %s" % (pe.line, desc)
            else:
                uvin = _vehicle_name(self.valid_files.get(fp))
                car_name = UVIN_TO_NAME.get(uvin, "")

            items = [
                QTableWidgetItem(name),
                QTableWidgetItem(status),
                QTableWidgetItem(base_mark),
                QTableWidgetItem(car_name),
                QTableWidgetItem(uvin),
                QTableWidgetItem(os.path.abspath(fp)),
                QTableWidgetItem(desc),
            ]
            for it in items:
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if is_ok:
                c = QColor("#2bdc7c")
            else:
                c = QColor("#ff5a68")
            items[0].setForeground(c)
            items[1].setForeground(c)
            self.files_table.setItem(r, 0, items[0])
            self.files_table.setItem(r, 1, items[1])
            self.files_table.setItem(r, 2, items[2])
            self.files_table.setItem(r, 3, items[3])
            self.files_table.setItem(r, 4, items[4])
            self.files_table.setItem(r, 5, items[5])
            self.files_table.setItem(r, 6, items[6])

        if base_row >= 0:
            try:
                self.files_table.setCurrentCell(base_row, 0)
                self.files_table.scrollToItem(self.files_table.item(base_row, 0))
            except Exception:
                pass

    def _rebuild_tabs(self):
        while self.tabs.count() > 0:
            self.tabs.removeTab(0)
        self.diff_cache = {}

        if not self.valid_files:
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(14, 14, 14, 14)
            tip = QLabel("请选择包含待对比JSON的文件夹")
            tip.setStyleSheet("color:#a8b4d8;")
            l.addWidget(tip)
            l.addStretch(1)
            self.tabs.addTab(w, "提示")
            return

        files = sorted(self.valid_files.keys(), key=lambda x: _rel_from_base(x, self.folder_path).lower())
        used_titles = {}
        for fp in files:
            if self.base_path and os.path.abspath(fp) == os.path.abspath(self.base_path):
                continue
            view = DiffView()
            view.set_toast(self.toast)
            view.set_only_diff(self._only_diff)
            if self.base_data is None:
                view.clear("请选择基准JSON文件后开始对比")
            else:
                view.clear("等待对比…")
            view._file_path = fp
            title = self._tab_title_for_file(fp)
            n = used_titles.get(title, 0) + 1
            used_titles[title] = n
            if n > 1:
                title = "%s (%d)" % (title, n)
            view._display_name = title
            self.tabs.addTab(view, title)

        if self.tabs.count() == 0:
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(14, 14, 14, 14)
            tip = QLabel("待对比文件为空（可能文件夹内只有基准文件）")
            tip.setStyleSheet("color:#a8b4d8;")
            l.addWidget(tip)
            l.addStretch(1)
            self.tabs.addTab(w, "提示")

    def _compute_all_diffs(self):
        if self.base_data is None:
            return
        targets = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, DiffView) and hasattr(w, "_file_path"):
                targets.append(w._file_path)
        if not targets:
            return

        base_data = self.base_data
        base_title = self.base_title or "base"
        ignore_paths = self._ignore_paths if self._ignore_default else None

        def job():
            out = {}
            for fp in targets:
                other = self.valid_files.get(fp)
                if other is None:
                    continue
                out[fp] = build_diff_tree(base_data, other, ignore_paths=ignore_paths)
            return out

        def done(res):
            self.diff_cache = res
            for i in range(self.tabs.count()):
                w = self.tabs.widget(i)
                if isinstance(w, DiffView) and hasattr(w, "_file_path"):
                    fp = w._file_path
                    tree = self.diff_cache.get(fp)
                    if tree is None:
                        w.clear("无法对比")
                        continue
                    other_title = getattr(w, "_display_name", None) or self._tab_title_for_file(fp)
                    w.render(tree, base_title, other_title)
            self.toast("对比完成", kind="ok")

        self._run_async("正在生成diff…", job, done)

    def _toggle_only_diff(self, state):
        self._only_diff = bool(state == Qt.CheckState.Checked.value)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, DiffView):
                w.set_only_diff(self._only_diff)

    def _toggle_ignore_default(self, state):
        self._ignore_default = bool(state == Qt.CheckState.Checked.value)
        if self._ignore_default and not self._ignore_paths:
            self._ignore_paths = load_ignore_paths(self._ignore_file)
        if self.base_data is None:
            return
        self.diff_cache = {}
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, DiffView):
                w.clear("等待对比…")
        self._compute_all_diffs()

    def export_current_html(self):
        w = self.tabs.currentWidget()
        if not isinstance(w, DiffView):
            self.toast("当前无可导出的对比结果", kind="warn")
            return
        diff_tree, base_title, other_title = w.export_payload()
        if diff_tree is None:
            self.toast("当前选项卡尚未生成diff", kind="warn")
            return
        rel = _rel_from_base(getattr(w, "_file_path", None), self.folder_path).replace("\\", "/")
        default_name = "%s__vs__%s.html" % (_safe_filename(rel), _safe_filename(base_title))
        save_path, _ = QFileDialog.getSaveFileName(self, "导出HTML diff报告", default_name, "HTML (*.html)")
        if not save_path:
            self.toast("已取消导出", kind="warn")
            return
        meta = {
            "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "base_path": self.base_path,
            "other_path": getattr(w, "_file_path", None),
        }
        html = html_report(diff_tree, base_title, other_title, meta=meta)
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception as e:
            self.toast("写入失败：%s" % e, kind="err")
            return
        self.toast("已导出：%s" % _short_path(save_path, 90), kind="ok")

    def export_all_html(self):
        if not self.diff_cache:
            self.toast("暂无可导出的对比结果", kind="warn")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择导出目录（将写入多个HTML）")
        if not out_dir:
            self.toast("已取消导出", kind="warn")
            return
        base_title = self.base_title or "base"
        exported_at = time.strftime("%Y-%m-%d %H:%M:%S")
        ok = 0
        entries = []
        for fp, tree in self.diff_cache.items():
            rel = _rel_from_base(fp, self.folder_path).replace("\\", "/")
            rel_dir = os.path.dirname(rel)
            safe_name = "%s__vs__%s.html" % (_safe_filename(os.path.basename(rel)), _safe_filename(base_title))
            save_path = os.path.join(out_dir, rel_dir, safe_name)
            _ensure_dir(os.path.dirname(save_path))
            meta = {
                "exported_at": exported_at,
                "base_path": self.base_path,
                "other_path": fp,
            }
            html = html_report(tree, base_title, rel, meta=meta)
            try:
                with open(save_path, "w", encoding="utf-8") as f:
                    f.write(html)
                ok += 1
                entries.append(
                    {
                        "rel_path": rel,
                        "report_rel": os.path.relpath(save_path, out_dir).replace("\\", "/"),
                        "summary": diff_summary(tree),
                    }
                )
            except Exception:
                continue
        try:
            index_html = _build_index_html(entries, base_title, self.base_path, exported_at)
            with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
                f.write(index_html)
        except Exception:
            pass
        self.toast("已导出 %d 个HTML到：%s（含 index.html）" % (ok, _short_path(out_dir, 90)), kind="ok" if ok else "warn")


def main():
    _linux_qt_platform_preflight()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

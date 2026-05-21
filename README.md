# UOS JSON Diff（桌面端）

基于 PyQt6 的跨平台（macOS / Linux）JSON 对比工具：

- 选择包含多个 JSON 的文件夹（默认递归扫描），自动校验 JSON 合法性（支持 `//` 与 `/*...*/` 注释、禁止重复 key）
- 选择基准 JSON 后，对每个合法 JSON 生成一个车辆选项卡，展示可折叠树形 diff（新增/删除/修改/类型变化）
- 支持搜索字段名/路径、双击复制路径、导出单个/全部 HTML 报告（含 `index.html` 汇总页）

## 本地运行（开发）

```bash
python3 uos_json_diff_desktop_qt.py
```

## 安装依赖（源码运行）

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -r requirements.txt
python3 uos_json_diff_desktop_qt.py
```

## 以命令行入口安装（可选）

安装后可以直接运行 `uos-json-diff`：

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install .
uos-json-diff
```

## 打包发布（PyInstaller）

产物默认输出到 `dist/`。

### macOS

```bash
bash scripts/build_mac.sh
```

### Linux

```bash
bash scripts/build_linux.sh
```

## 目录结构

- `uos_json_diff_desktop_qt.py`：PyQt6 桌面端入口
- `jsondiff_engine.py`：解析/差异引擎（注释剥离、重复 key 校验、树形 diff、HTML 报告）
- `diff_uos_common_v4.py`：保留的命令行脚本（终端 diff）

## 版本发布

- v1.1 实现多json参数对比，未来加入入库参数对比


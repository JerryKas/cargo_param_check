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

打包完成后：
- 应用位置：`dist/uos-json-diff.app`
- 启动方式：
  - Finder 双击 `uos-json-diff.app`
  - 或命令行启动：

```bash
open dist/uos-json-diff.app
```

若首次打开被 Gatekeeper 拦截：
- 系统设置 → 隐私与安全性 → 仍要打开
- 或（仅对本地测试）移除隔离属性：

```bash
xattr -dr com.apple.quarantine dist/uos-json-diff.app
open dist/uos-json-diff.app
```

### Linux

```bash
bash scripts/build_linux.sh
```

打包完成后：
- 可执行文件：`dist/uos-json-diff/uos-json-diff`
- 启动方式：

```bash
./dist/uos-json-diff/uos-json-diff
```

若提示无执行权限：

```bash
chmod +x dist/uos-json-diff/uos-json-diff
./dist/uos-json-diff/uos-json-diff
```

## Linux 运行依赖（常见）

Qt6 在 Linux 上通常依赖系统的图形/平台库。若运行可执行文件时报：

`Could not load the Qt platform plugin "xcb"` / `libxcb-cursor0 is needed`

请在目标机器安装对应依赖：

- Debian/Ubuntu：
  - `sudo apt-get update && sudo apt-get install -y libxcb-cursor0`
- Fedora/RHEL：
  - `sudo dnf install -y xcb-util-cursor`
- Arch：
  - `sudo pacman -S xcb-util-cursor`
- openSUSE：
  - `sudo zypper install -y libxcb-cursor0`

## 目录结构

- `uos_json_diff_desktop_qt.py`：PyQt6 桌面端入口
- `jsondiff_engine.py`：解析/差异引擎（注释剥离、重复 key 校验、树形 diff、HTML 报告）
- `diff_uos_common_v4.py`：保留的命令行脚本（终端 diff）

## 版本发布

- v1.1 实现多json参数对比，未来加入入库参数对比

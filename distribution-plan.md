# 拾遗工坊 · 三系统安装分发方案

> 基于 PyInstaller 打包 + 平台原生安装包格式 + GitHub Actions CI/CD

---

## 目录

1. [现状概览](#1-现状概览)
2. [Windows](#2-windows)
3. [macOS](#3-macos)
4. [Linux](#4-linux)
5. [发布渠道与版本规范](#5-发布渠道与版本规范)
6. [CI/CD 流水线](#6-cicd-流水线)
7. [推荐实施顺序](#7-推荐实施顺序)

---

## 1. 现状概览

**应用性质**：Python FastAPI Web 应用（带静态前端）
**进程模型**：PyInstaller 打包后启动一个子进程运行 uvicorn 服务器，打开浏览器访问 localhost 端口
**依赖清单**：fastapi, uvicorn, httpx, cryptography, pyyaml, python-multipart, aiofiles
**数据存储**：本地文件系统（data/ 目录下 SQLite + 章节 .md 文件）
**现有构建**：`build.py`（跨平台 Python 脚本）+ `build.sh`（Linux/macOS Shell 脚本），均使用 PyInstaller --onefile

---

## 2. Windows

### 2.1 目标产物

| 类型 | 格式 | 用途 |
|------|------|------|
| 安装包 | `拾遗工坊-Setup-x.x.x.exe` | 一键安装，开始菜单快捷方式 |
| 便携版 | `拾遗工坊-x.x.x-win64.zip` | 解压即用，无需管理员权限 |

### 2.2 PyInstaller 构建

在现有 `build.py` 基础上加固：

```python
# build.py 需要调整的关键点

# 1. 指定 --onedir 而非 --onefile
#    原因：--onefile 启动慢（自解压），且 --onedir 便于附带资源文件
cmd = [
    sys.executable, "-m", "PyInstaller",
    "--onedir",                     # 改为 onedir，启动更快
    "--name", APP_NAME,
    "--distpath", str(DIST_DIR),
    "--workpath", str(BUILD_DIR),
    "--specpath", str(BUILD_DIR),
    "--noconsole",                  # GUI 应用不显示控制台
    "--add-data", "static;static",  # 附带静态资源
    "--add-data", "templates;templates",
    "--add-data", ".env.example;.",
    "--icon", "assets/icon.ico",    # 应用图标
]
ENTRY
```

**图标文件**需准备：
- `assets/icon.ico`（Windows 用，256x256 多尺寸）
- `assets/icon.icns`（macOS 用）
- `assets/icon.png`（Linux 用，512x512）

### 2.3 Inno Setup 安装包

推荐使用 Inno Setup（免费、成熟、社区广泛）。配置文件 `installer/windows/setup.iss`：

```iss
; installer/windows/setup.iss
#define MyAppName "拾遗工坊"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "拾遗工坊"
#define MyAppURL "https://github.com/your-org/writing-app"
#define MyAppExeName "拾遗工坊.exe"

[Setup]
AppId={{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=拾遗工坊-Setup-{#MyAppVersion}
PrivilegesRequired=lowest         ; 普通用户权限即可安装

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "..\..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs
Source: "..\..\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载拾遗工坊"; Filename: "{uninstallexe}"
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动拾遗工坊"; Flags: postinstall nowait skipifsilent

[UninstallRun]
; 卸载时清理用户数据目录（可选，默认保留用户数据）
; Filename: "{cmd}"; Parameters: "/c rmdir /s /q ""{userappdata}\拾遗工坊"""; Flags: runhidden
```

**构建命令**（CI 中使用）：

```bash
# 1. PyInstaller 打包
python build.py

# 2. 复制 Inno Setup 编译器（预装或下载）
ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
"$ISCC" installer/windows/setup.iss
```

**自动检测 Python / 引导安装依赖**：

Inno Setup 本身不涉及 Python 检测——PyInstaller 已将 Python 解释器和依赖全部打包进 exe，用户无需安装 Python。运行环境是自包含的。

如果你希望保留"有 Python 则用 venv 启动，否则用 exe"的双模式，可以在启动器层面做判断，但多一层复杂度。建议：

> **策略**：默认分发 PyInstaller 打包的独立 exe（不依赖系统 Python）。为开发者保留 `run.bat` + `venv` 方式。

### 2.4 便携版（ZIP）

```bash
# 便携版打包脚本（installer/windows/package-portable.sh 或 build.py 的 zip 命令）
cd dist
mkdir 拾遗工坊
cp -r 拾遗工坊/* 拾遗工坊/   # onedir 输出
# 或直接用 --onefile 产出单个 exe
zip -r ../拾遗工坊-1.0.0-win64.zip 拾遗工坊/
```

便携版 = PyInstaller 输出目录直接打包，用户解压后运行 `拾遗工坊.exe`。所有数据（SQLite 数据库、章节文件）默认保存在用户目录下 `%APPDATA%/拾遗工坊/`。

### 2.5 静默安装 / 企业部署

如有需要，Inno Setup 支持 `/VERYSILENT` 参数：

```bash
拾遗工坊-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR="D:\Tools\拾遗工坊"
```

---

## 3. macOS

### 3.1 目标产物

| 类型 | 格式 | 用途 |
|------|------|------|
| DMG 镜像 | `拾遗工坊-x.x.x-macos.dmg` | 拖拽安装到 Applications |
| 纯 .app 包 | `拾遗工坊.app` | 直接运行 |

### 3.2 PyInstaller 构建

```bash
# macOS 构建命令 (build.sh 增强版)
python -m PyInstaller \
    --onedir \
    --name "拾遗工坊" \
    --windowed \
    --icon assets/icon.icns \
    --add-data "static:static" \
    --add-data "templates:templates" \
    --add-data ".env.example:." \
    --osx-bundle-identifier "com.shiyigongfang.app" \
    --target-architecture "arm64" \
    main.py
```

**注意事项**：
- 使用 `--windowed` 而非 `--console`，否则会附带 Terminal 窗口
- `--onedir` 模式在 macOS 下就是 .app 包结构
- 建议在 macOS 12+ (Monterey) 上构建以保证向后兼容
- 如需 Universal Binary (Intel + Apple Silicon)，用 `--target-architecture "universal2"`，或分别在 x86_64 和 arm64 机器上构建后用 `lipo` 合并

### 3.3 制作 DMG

使用 [create-dmg](https://github.com/sindresorhus/create-dmg) 工具：

```bash
# 安装 create-dmg（CI 环境中预装）
npm install -g create-dmg
# 或 brew install create-dmg

# 制作 DMG
create-dmg \
  --volname "拾遗工坊" \
  --volicon "assets/icon.icns" \
  --background "assets/dmg-background.png" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "拾遗工坊.app" 175 190 \
  --hide-extension "拾遗工坊.app" \
  --app-drop-link 425 190 \
  "dist/拾遗工坊-1.0.0-macos.dmg" \
  "dist/拾遗工坊.app"
```

### 3.4 签名与公证

macOS Gatekeeper 要求签名 + 公证才能在没有安全警告的情况下运行。

**步骤一：代码签名**

```bash
# 签名 .app 包（需 Apple Developer 证书）
codesign --force --options runtime \
  --sign "Developer ID Application: 你的名字 (TEAMID)" \
  --entitlements "installer/macos/entitlements.plist" \
  --deep "dist/拾遗工坊.app"

# 验证签名
codesign --verify --deep --strict "dist/拾遗工坊.app"
spctl --assess --verbose "dist/拾遗工坊.app"
```

**entitlements.plist** 文件：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
</dict>
</plist>
```

**步骤二：公证（Notarization）**

```bash
# 压缩 .app 为 .zip for 公证
ditto -c -k --keepParent "dist/拾遗工坊.app" "dist/拾遗工坊.zip"

# 提交公证
xcrun notarytool submit "dist/拾遗工坊.zip" \
  --apple-id "your@email.com" \
  --team-id "TEAMID" \
  --password "@keychain:AC_PASSWORD" \
  --wait

# 在 DMG 上打 stapler
xcrun stapler staple "dist/拾遗工坊-1.0.0-macos.dmg"
```

**CI 中的密钥管理**：将 Apple ID 和 App-Specific Password 存入 GitHub Actions Secrets。

---

## 4. Linux

### 4.1 目标产物

| 类型 | 格式 | 用途 |
|------|------|------|
| AppImage | `拾遗工坊-x.x.x-x86_64.AppImage` | 通用 Linux 分发，解压即用 |
| deb 包 | `拾遗工坊_x.x.x_amd64.deb` | Debian/Ubuntu 专用安装 |
| Flatpak | `拾遗工坊.flatpak` | 容器化沙箱运行 |

### 4.2 PyInstaller 构建

```bash
# Linux 构建命令
python -m PyInstaller \
    --onedir \
    --name "拾遗工坊" \
    --console \
    --add-data "static:static" \
    --add-data "templates:templates" \
    --add-data ".env.example:." \
    --icon assets/icon.png \
    main.py
```

**架构策略**：
- 在 Ubuntu 20.04 LTS (GLIBC 2.31) 上构建以获最大兼容性
- 使用 `manylinux` Docker 镜像构建以确保 GLIBC 版本兼容
- 默认 x86_64 架构；ARM 版可用树莓派或 ARM CI runner 构建

### 4.3 AppImage（推荐）

AppImage 是 Linux 上最接近"双击即用"的方案，适合桌面用户。

使用 [appimagetool](https://github.com/AppImage/AppImageKit)：

```bash
# 1. 准备 AppDir 结构
mkdir -p AppDir/usr/bin
mkdir -p AppDir/usr/share/applications
mkdir -p AppDir/usr/share/icons/hicolor/512x512/apps

# 2. 复制 PyInstaller 产物
cp -r dist/拾遗工坊/* AppDir/usr/bin/

# 3. 创建 .desktop 文件
cat > AppDir/usr/share/applications/拾遗工坊.desktop << EOF
[Desktop Entry]
Name=拾遗工坊
Comment=泰拉拾遗录写作辅助工具
Exec=拾遗工坊
Icon=拾遗工坊
Terminal=false
Type=Application
Categories=Office;TextEditor;
EOF

# 4. 复制图标
cp assets/icon.png AppDir/usr/share/icons/hicolor/512x512/apps/拾遗工坊.png

# 5. 创建 AppRun 入口
cat > AppDir/AppRun << 'EOF'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
exec "${HERE}/usr/bin/拾遗工坊" "$@"
EOF
chmod +x AppDir/AppRun

# 6. 用 appimagetool 打包
ARCH=x86_64 appimagetool AppDir dist/拾遗工坊-x.x.x-x86_64.AppImage
```

**注意事项**：
- AppImage 需要 FUSE 支持（AppImageLauncher 可解决）
- 应用的数据目录自动定位到 `~/.config/拾遗工坊/` 或 `~/.local/share/拾遗工坊/`
- 可提供 `--no-sandbox` 模式备选

### 4.4 deb 包

对于 Debian/Ubuntu 用户，deb 包提供更原生的安装体验：

```bash
# 构建 deb 包结构
mkdir -p deb-pkg/DEBIAN
mkdir -p deb-pkg/usr/local/bin/拾遗工坊
mkdir -p deb-pkg/usr/share/applications
mkdir -p deb-pkg/usr/share/icons/hicolor/512x512/apps

# 复制产物
cp -r dist/拾遗工坊/* deb-pkg/usr/local/bin/拾遗工坊/

# 创建控制文件
cat > deb-pkg/DEBIAN/control << EOF
Package: shiyigongfang
Version: 1.0.0
Section: editors
Priority: optional
Architecture: amd64
Maintainer: 拾遗工坊 <your-email@example.com>
Description: 泰拉拾遗录专属写作辅助工具
 一个基于 FastAPI 的本地写作工作台，支持
 Markdown编辑、AI聊天辅助、自动审查等功能。
EOF

# 创建快捷方式
cat > deb-pkg/usr/share/applications/拾遗工坊.desktop << EOF
[Desktop Entry]
Name=拾遗工坊
Comment=泰拉拾遗录写作辅助工具
Exec=/usr/local/bin/拾遗工坊/拾遗工坊
Icon=拾遗工坊
Terminal=false
Type=Application
Categories=Office;TextEditor;
EOF

cp assets/icon.png deb-pkg/usr/share/icons/hicolor/512x512/apps/拾遗工坊.png

# 打包
dpkg-deb --build deb-pkg dist/拾遗工坊_1.0.0_amd64.deb
```

也可使用 [fpm](https://github.com/jordansissel/fpm) 工具简化：

```bash
gem install fpm
fpm -s dir -t deb \
  -n 拾遗工坊 \
  -v 1.0.0 \
  -a amd64 \
  --description "泰拉拾遗录写作辅助工具" \
  --url "https://github.com/your-org/writing-app" \
  --license MIT \
  --vendor "拾遗工坊" \
  dist/拾遗工坊/=/usr/local/bin/拾遗工坊 \
  assets/icon.png=/usr/share/icons/hicolor/512x512/apps/拾遗工坊.png
```

### 4.5 Flatpak（进阶选项）

Flatpak 提供沙箱隔离 + 跨发行版兼容。适合高级用户，但构建复杂度更高。

关键文件：
- `installer/linux/flatpak/io.github.shiyigongfang.yml` — Flatpak manifest
- 需要将应用打包为 Flatpak 的 SDK 运行时（如 `org.freedesktop.Sdk`）

Flatpak 构建流程：

```bash
flatpak-builder --repo=repo build-dir installer/linux/flatpak/io.github.shiyigongfang.yml
flatpak build-bundle repo 拾遗工坊.flatpak io.github.shiyigongfang
```

**推荐优先级**：AppImage > deb > Flatpak
- 日常分发用 AppImage（最广覆盖）
- deb 为 Ubuntu/Debian 原生用户准备
- Flatpak 作为社区维护选项

---

## 5. 发布渠道与版本规范

### 5.1 版本号规范

严格遵循 [Semantic Versioning 2.0](https://semver.org/)：

```
MAJOR.MINOR.PATCH[-prerelease]
```

| 版本 | 含义 | 示例 |
|------|------|------|
| MAJOR | 不兼容的 API/数据结构变更 | 1.0.0 → 2.0.0 |
| MINOR | 向下兼容的功能新增 | 1.0.0 → 1.1.0 |
| PATCH | 向下兼容的 bug 修复 | 1.0.0 → 1.0.1 |
| prerelease | 预发布版本 | 1.0.0-beta.1, 1.0.0-rc.1 |

**文件命名规则**：

```
拾遗工坊-{MAJOR}.{MINOR}.{PATCH}-{platform}.{ext}
拾遗工坊-Setup-{MAJOR}.{MINOR}.{PATCH}.exe         # Windows 安装包
拾遗工坊-{MAJOR}.{MINOR}.{PATCH}-win64.zip         # Windows 便携版
拾遗工坊-{MAJOR}.{MINOR}.{PATCH}-macos.dmg         # macOS DMG
拾遗工坊-{MAJOR}.{MINOR}.{PATCH}-x86_64.AppImage   # Linux AppImage
拾遗工坊_{MAJOR}.{MINOR}.{PATCH}_amd64.deb         # Linux deb
```

### 5.2 GitHub Releases

每次发布流程：

1. **创建 Tag**（触发 CI 构建）

```bash
git tag v1.0.0
git push origin v1.0.0
```

2. **CI 自动构建**并上传构建产物到 Release

3. **发布说明**结构：

```markdown
# 拾遗工坊 v1.0.0

## 新增
- xxx

## 修复
- xxx

## 变更
- xxx

## 下载
| 平台 | 安装包 | 便携版 |
|------|--------|--------|
| Windows | 拾遗工坊-Setup-1.0.0.exe | 拾遗工坊-1.0.0-win64.zip |
| macOS | 拾遗工坊-1.0.0-macos.dmg | — |
| Linux | 拾遗工坊-1.0.0-x86_64.AppImage | 拾遗工坊-1.0.0-x86_64.AppImage |
```

### 5.3 更新检查机制

提供轻量自动更新，无需后端服务器：

**方案一：GitHub API 查询版本**

在应用中（启动时后台静默检查）：

```python
import httpx

def check_update():
    try:
        resp = httpx.get(
            "https://api.github.com/repos/your-org/writing-app/releases/latest",
            timeout=5
        )
        latest = resp.json()
        latest_tag = latest["tag_name"].lstrip("v")
        current = "1.0.0"

        if compare_versions(latest_tag, current) > 0:
            return {
                "has_update": True,
                "version": latest_tag,
                "url": latest["html_url"],
                "assets": latest["assets"]
            }
    except Exception:
        return {"has_update": False}
    return {"has_update": False}
```

**方案二：嵌入 release.json**

在 Release 中附带 `release.json` 文件：

```json
{
  "version": "1.0.0",
  "url": "https://github.com/your-org/writing-app/releases/tag/v1.0.0",
  "notes": "更新内容摘要",
  "downloads": {
    "windows": "https://github.com/.../拾遗工坊-Setup-1.0.0.exe",
    "macos": "https://github.com/.../拾遗工坊-1.0.0-macos.dmg",
    "linux": "https://github.com/.../拾遗工坊-1.0.0-x86_64.AppImage"
  }
}
```

应用从 `https://raw.githubusercontent.com/your-org/writing-app/main/release.json` 获取最新版本号。

**版本比较函数**：

```python
def compare_versions(v1: str, v2: str) -> int:
    """return 1 if v1 > v2, -1 if v1 < v2, 0 if equal"""
    parts1 = [int(x) for x in v1.split(".")]
    parts2 = [int(x) for x in v2.split(".")]
    for a, b in zip(parts1, parts2):
        if a > b: return 1
        if a < b: return -1
    return len(parts1) - len(parts2)
```

**更新检查 UI 流程**：

```
应用启动 → 后台检查更新
  ├─ 无更新 → 静默，不进日志
  └─ 有更新 → 底部状态栏显示 "📦 新版本 v1.0.1 可用"
               点击 → 弹出对话框
               ├─ "下载更新" → 打开浏览器到 Release 页面
               └─ "忽略此版本" → 写入本地忽略列表，不再次提醒
```

---

## 6. CI/CD 流水线

### 6.1 GitHub Actions 工作流

文件：`.github/workflows/release.yml`

```yaml
name: Build and Release

on:
  push:
    tags:
      - 'v*'          # 推送版本标签时触发
  workflow_dispatch:  # 手动触发
    inputs:
      version:
        description: '版本号 (如 1.0.0)'
        required: true

jobs:
  # ── 1. 配置检测 ──
  check-config:
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.get-version.outputs.version }}
    steps:
      - uses: actions/checkout@v4
      - id: get-version
        run: |
          # 从 tag 或手动输入获取版本
          echo "version=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT

  # ── 2. Windows 构建 ──
  build-windows:
    needs: check-config
    runs-on: windows-latest
    env:
      VERSION: ${{ needs.check-config.outputs.version }}
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt pyinstaller

      - name: PyInstaller build
        run: python build.py --clean

      - name: Install Inno Setup
        shell: pwsh
        run: |
          # 下载 Inno Setup 便携版
          # 或用 choco install innosetup
          choco install innosetup --no-progress

      - name: Build installer
        run: |
          # 用 ISCC 编译安装包
          & "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer/windows/setup.iss
        shell: pwsh

      - name: Package portable zip
        run: |
          Compress-Archive -Path dist/拾遗工坊/* -DestinationPath dist/拾遗工坊-${{ env.VERSION }}-win64.zip
        shell: pwsh

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: windows-artifacts
          path: |
            dist/installer/*.exe
            dist/*.zip

  # ── 3. macOS 构建 ──
  build-macos:
    needs: check-config
    runs-on: macos-latest
    env:
      VERSION: ${{ needs.check-config.outputs.version }}
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt pyinstaller
          npm install -g create-dmg || brew install create-dmg

      - name: PyInstaller build
        run: |
          python -m PyInstaller \
            --onedir --windowed \
            --name "拾遗工坊" \
            --icon assets/icon.icns \
            --add-data "static:static" \
            --add-data "templates:templates" \
            --add-data ".env.example:." \
            --osx-bundle-identifier "com.shiyigongfang.app" \
            main.py

      - name: Build DMG
        run: |
          create-dmg \
            --volname "拾遗工坊" \
            --volicon "assets/icon.icns" \
            --window-pos 200 120 --window-size 600 400 \
            --icon-size 100 --icon "拾遗工坊.app" 175 190 \
            --hide-extension "拾遗工坊.app" \
            --app-drop-link 425 190 \
            "dist/拾遗工坊-${{ env.VERSION }}-macos.dmg" \
            "dist/拾遗工坊.app"

      # 签名与公证（可选，需配置 secrets）
      # - name: Sign and notarize
      #   env:
      #     APPLE_ID: ${{ secrets.APPLE_ID }}
      #     APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
      #     APPLE_APP_PASSWORD: ${{ secrets.APPLE_APP_PASSWORD }}
      #   run: |
      #     # codesign + notarize 逻辑

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: macos-artifacts
          path: dist/*.dmg

  # ── 4. Linux 构建 ──
  build-linux:
    needs: check-config
    runs-on: ubuntu-latest
    env:
      VERSION: ${{ needs.check-config.outputs.version }}
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt pyinstaller
          # 安装 appimagetool
          sudo wget -O /usr/local/bin/appimagetool \
            https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
          sudo chmod +x /usr/local/bin/appimagetool
          # 安装 fpm（用于 deb）
          sudo gem install fpm

      - name: PyInstaller build
        run: |
          python -m PyInstaller \
            --onedir --console \
            --name "拾遗工坊" \
            --add-data "static:static" \
            --add-data "templates:templates" \
            --add-data ".env.example:." \
            main.py

      - name: Build AppImage
        run: |
          mkdir -p AppDir/usr/bin AppDir/usr/share/applications
          mkdir -p AppDir/usr/share/icons/hicolor/512x512/apps

          cp -r dist/拾遗工坊/* AppDir/usr/bin/
          cp assets/icon.png AppDir/usr/share/icons/hicolor/512x512/apps/拾遗工坊.png

          cat > AppDir/usr/share/applications/拾遗工坊.desktop << EOD
          [Desktop Entry]
          Name=拾遗工坊
          Comment=泰拉拾遗录写作辅助工具
          Exec=拾遗工坊
          Icon=拾遗工坊
          Terminal=false
          Type=Application
          Categories=Office;TextEditor;
          EOD

          cat > AppDir/AppRun << 'EOD'
          #!/bin/bash
          SELF=\$(readlink -f "\$0")
          HERE=\${SELF%/*}
          exec "\${HERE}/usr/bin/拾遗工坊" "\$@"
          EOD
          chmod +x AppDir/AppRun

          ARCH=x86_64 appimagetool AppDir dist/拾遗工坊-${{ env.VERSION }}-x86_64.AppImage

      - name: Build deb
        run: |
          fpm -s dir -t deb \
            -n 拾遗工坊 \
            -v ${{ env.VERSION }} \
            -a amd64 \
            --description "泰拉拾遗录写作辅助工具" \
            --license MIT \
            --vendor "拾遗工坊" \
            dist/拾遗工坊/=/usr/local/bin/拾遗工坊 \
            assets/icon.png=/usr/share/icons/hicolor/512x512/apps/拾遗工坊.png

          mv 拾遗工坊_*.deb dist/

      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: linux-artifacts
          path: dist/*.AppImage

  # ── 5. 发布 Release ──
  release:
    needs: [build-windows, build-macos, build-linux]
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - name: Download all artifacts
        uses: actions/download-artifact@v4

      - name: Generate release notes
        run: |
          # 从 CHANGELOG.md 提取当前版本的 release notes
          VERSION="${{ needs.check-config.outputs.version }}"
          cat > release-notes.md << 'EOF'
          # 拾遗工坊 v$VERSION

          请查看 CHANGELOG.md 获取详细信息。

          ## 下载
          - [Windows 安装包](./windows-artifacts/拾遗工坊-Setup-$VERSION.exe)
          - [Windows 便携版](./windows-artifacts/拾遗工坊-$VERSION-win64.zip)
          - [macOS DMG](./macos-artifacts/拾遗工坊-$VERSION-macos.dmg)
          - [Linux AppImage](./linux-artifacts/拾遗工坊-$VERSION-x86_64.AppImage)
          EOF

      - name: Create Release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: v${{ needs.check-config.outputs.version }}
          name: 拾遗工坊 v${{ needs.check-config.outputs.version }}
          body_path: release-notes.md
          files: |
            windows-artifacts/**
            macos-artifacts/**
            linux-artifacts/**
          draft: false
          prerelease: false
          generate_release_notes: false
```

### 6.2 日常构建（非发布）

对于 `dev` 分支的每次推送，可配置仅运行测试 + PyInstaller 构建验证（不上传 Release）：

```yaml
# .github/workflows/build-check.yml
name: Build Check

on:
  push:
    branches: [dev, main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: python -m py_compile main.py

  build-check:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt pyinstaller
      - run: python build.py
```

### 6.3 Secret 配置清单

GitHub Repo Secrets 需配置：

| Secret 名称 | 用途 | 必需 |
|-------------|------|:----:|
| `APPLE_ID` | Apple 开发者账号邮箱 | macOS 公证 |
| `APPLE_TEAM_ID` | Apple Team ID | macOS 签名 |
| `APPLE_APP_PASSWORD` | App-Specific Password | macOS 公证 |
| 无 | Windows Authenticode 证书（可选） | Windows 代码签名 |

---

## 7. 推荐实施顺序

```
Phase 1 ─── Windows MVP ─────────────────────────────
  [x] PyInstaller 构建（已有 build.py）
  [ ] 改为 --onedir 模式 + 附带静态资源
  [ ] 准备 assets/icon.ico
  [ ] 编写 installer/windows/setup.iss
  [ ] 便携版 zip 打包脚本
  [ ] 本地测试：安装 → 卸载 → 便携版解压运行

Phase 2 ─── GitHub Actions 基础 ──────────────────────
  [ ] 编写 .github/workflows/build-check.yml
  [ ] Windows 自动构建上 CI
  [ ] 配置 pre-release 测试发布

Phase 3 ─── Linux ────────────────────────────────────
  [ ] 编写 AppDir 构建脚本
  [ ] AppImage 构建 + 测试
  [ ] deb 包构建脚本
  [ ] Linux CI 集成

Phase 4 ─── macOS ────────────────────────────────────
  [ ] 准备 assets/icon.icns
  [ ] DMG 构建脚本
  [ ] 签名 + 公证流程
  [ ] macOS CI 集成

Phase 5 ─── 发布流水线 ───────────────────────────────
  [ ] 编写完整 release.yml
  [ ] 更新检查机制实现
  [ ] 首次正式 Release
  [ ] changelog + release note 模板
```

---

## 附录 A：文件结构总览

```
writing-app/
├── .github/
│   └── workflows/
│       ├── build-check.yml        # 日常构建验证
│       └── release.yml            # 发布流水线
├── assets/
│   ├── icon.ico                   # Windows 图标 (256x256)
│   ├── icon.icns                  # macOS 图标
│   ├── icon.png                   # Linux 图标 (512x512)
│   └── dmg-background.png         # DMG 背景图 (可选)
├── installer/
│   ├── windows/
│   │   ├── setup.iss              # Inno Setup 配置
│   │   └── package-portable.sh    # 便携版打包
│   ├── macos/
│   │   ├── entitlements.plist     # 签名权限声明
│   │   └── build-dmg.sh           # DMG 构建脚本
│   └── linux/
│       ├── build-appimage.sh      # AppImage 构建
│       └── build-deb.sh           # deb 包构建
├── build.py                       # PyInstaller 构建（增强版）
├── build.sh                       # Linux/macOS 备用
├── release.json                   # 更新检查用版本信息
├── CHANGELOG.md                   # 变更日志
└── distribution-plan.md           # 本文件
```

## 附录 B：PyInstaller 常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `FileNotFoundError: [Errno 2] No such file or directory: 'static/...'` | 资源路径在打包后变了 | 使用 `sys._MEIPASS` 获取运行时路径，参考附录 C |
| 启动很慢（--onefile） | 每次运行自解压 | 改用 `--onedir` |
| 杀毒软件报毒 | PyInstaller 打包特征 | 代码签名 + 提交给厂商白名单 |
| macOS: "已损坏，无法打开" | 未签名 / Gatekeeper | 签名 + 公证 |

## 附录 C：运行时路径适配

在应用代码中处理打包前后的路径差异：

```python
# core/paths.py
import sys, os
from pathlib import Path

def app_root() -> Path:
    """应用根目录（打包时为解压后的临时目录，未打包时为项目根目录）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包模式
        return Path(sys._MEIPASS)
    else:
        # 开发模式
        return Path(__file__).parent.parent

def data_dir() -> Path:
    """用户数据目录（数据库 + 章节文件）"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", "~"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "拾遗工坊"
```

---

> 拾遗工坊 · 分发方案 v1.0
> 最后更新：2026-05-20

---
name: tune-ui
description: 微调 Qoder IDE 外观细节（界面颜色、边框、diff 背景、语法高亮），保留当前主题与全部既有配置。用于用户要求调整颜色、边界、对比度、透明度等外观细节；不更换主题、不改无关设置、不修改主题扩展文件。
---

# 界面微调

保留用户当前主题，把外观调整收敛为用户设置中最小、可逆的颜色覆盖。成功标准：覆盖命中用户指出的区域；无关配置逐字保留；回读与结构校验通过；视觉效果由用户确认。

## 取证与定位键名

1. 读取 `~/Library/Application Support/Qoder/User/settings.json` 的 `workbench.colorTheme` 取得当前主题名。覆盖写在 `workbench.colorCustomizations` 的 `"[<主题名>]"` 作用域下，换主题不受影响。
2. 界面颜色用 `workbench.colorCustomizations`，代码语法高亮用 `editor.tokenColorCustomizations`。颜色值支持 `#RRGGBBAA` 透明度后缀。
3. 键名或现值不明时按以下顺序取证：读 `~/.qoder/extensions/<扩展>/package.json` 的 `contributes.themes`，把显示名映射到主题文件，再读该文件的颜色键与值；或请用户在命令面板运行“开发人员: 检查编辑器令牌和作用域”“开发人员: 从当前设置生成颜色主题”获取当前值与 scope。
4. Qoder 自有视图（如 Agent 变更 diff）可能不使用标准 `diffEditor.*` 键。覆盖未命中时，在安装包 `out/vs/workbench/workbench.desktop.main.js` 中 grep 颜色注册，确认该视图实际使用的键；不重复猜测标准键。安装包路径用进程命令行（`ps aux`）定位，应用名可能带空格或后缀（如 `Qoder IDE.app`），不要猜目录。已知私有键：变更视图整行插入/删除底色为 `aicoding.diffWholeLineInsertedTextBackground` / `aicoding.diffWholeLineRemovedTextBackground`。
5. 主题入口文件可能通过 `include` 引用同目录兄弟文件，tokenColors 高亮规则常在被 include 的文件里；顶层查不到规则时跟随 include 再查。
6. 整行 diff 底色是多键叠加渲染：`diffEditor.insertedLineBackground` + `diffEditor.insertedTextBackground` + 私有整行键同时作用。只改一层会出现“改了没生效”或色相被其余层拽回旧色；正确做法是把参与叠加的所有层统一为同一色相、各给低透明度，后续微调只改最上层 alpha。
7. 标签页标题色会被 Git 装饰色覆盖（优先级高于 `tab.activeForeground`）；只去标签页染色而不动文件树/diff，用顶层开关 `workbench.editor.decorations.colors: false`。`focusBorder` 设 `#00000000` 可去掉控件聚焦描边。

## 修改

- 前提：会话“文件编辑工具”开关允许编辑工作区外文件。被拒绝时说明原因，提供最小片段供用户手动粘贴，或建议用户开启开关后继续；不得用终端写入绕过。
- 先读后改，最小编辑合并进既有覆盖对象；保留所有其他键、注释与尾随逗号（文件为 IDE 支持的 JSONC）。
- 只改用户指出的区域。用户未指定色值时，选贴近主题现有配色的中性值，并说明调整方向（更亮、更暗、更透明）与备选值。
- 不修改主题扩展文件，不切换 `workbench.colorTheme`，不触碰无关设置。
- textMateRules 特异性：带语言前缀的 scope（如 `source.go keyword.function`）压过通用 scope（如 `keyword`）；用户规则追加在主题规则之后，同特异性后者胜。用“全局基色 + 语言专属色”分层覆盖。
- 按色值 replace_all 前确认该十六进制值只出现在目标区块（同一值可能同时在 token 规则与 gitDecoration 键中）；整档链式位移（新值等于另一组旧值）时按旧值从大到小顺序替换，避免连锁误伤；带透明度的 8 位串与 6 位主调色同前缀时，只替换更长的 8 位串以保护主调。
- 迭代节奏：一次只移一档（亮度约 3–6 灰阶、饱和度一档）；被否时取两个被否版本的通道中点作新值；每轮回复保留“层→旧值→新值”历史表，使用户说“调回之前某状态”时能精确复原。
- 批量改动前备份：把 `workbench.colorCustomizations`、`editor.tokenColorCustomizations` 与相关顶层开关（`workbench.colorTheme`、`workbench.editor.decorations.colors`）抽取为 settings.json 同目录的 `settings-colors.backup-<YYYY-MM-DD>.json`；恢复时按区块合并回，不整文件覆盖。

## 验证与完成

- 写入后回读，用容忍尾随逗号的解析校验整体结构（JSONC 先正则去除尾随逗号再解析），核对请求的键值正确、无关内容未变。
- 批量改色后按 background / gitDecoration.* / textMateRules 三个区块分别打印键值，并比对覆盖键总数与顶层键总数，确认无跨区块误伤。
- 设置由 IDE 自动加载；视觉效果以用户观察为准。用户反馈未命中或不满意时，回到键名定位或色值调整，不宣称完成。
- 报告变更的键、值与恢复方式（删除对应覆盖即恢复主题原样）。用户确认满意或明确结束时停止。
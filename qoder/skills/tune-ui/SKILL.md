---
name: tune-ui
description: 微调 Qoder IDE 外观细节（界面颜色、边框、diff 背景、语法高亮），保留当前主题与全部既有配置。用于用户要求调整颜色、边界、对比度、透明度等外观细节；不更换主题、不改无关设置、不修改主题扩展文件。
---

# 界面微调

保留用户当前主题，把外观调整收敛为用户设置中最小、可逆的颜色覆盖。成功标准：覆盖命中用户指出的区域；无关配置逐字保留；回读与结构校验通过；视觉效果由用户确认。

## 取证与定位键名

1. 确认当前生效的用户设置文件和主题。macOS 默认设置文件为 `~/Library/Application Support/Qoder/User/settings.json`。使用配置档案或主题被覆盖时，以当前实例实际生效的设置为准。主题专属覆盖写在对应设置的 `"[<主题名>]"` 作用域下。
2. 界面颜色用 `workbench.colorCustomizations`，代码语法高亮用 `editor.tokenColorCustomizations`。颜色值支持 `#RRGGBBAA` 透明度后缀。
3. 键名或现值不明时按以下顺序取证：读 `~/.qoder/extensions/<扩展>/package.json` 的 `contributes.themes`，把显示名映射到主题文件，再读该文件的颜色键与值；或请用户在命令面板运行“开发人员: 检查编辑器令牌和作用域”“开发人员: 从当前设置生成颜色主题”获取当前值与 scope。
4. Qoder 自有视图（如 Agent 变更 diff）可能不使用标准 `diffEditor.*` 键。覆盖未命中时，在安装包 `out/vs/workbench/workbench.desktop.main.js` 中 grep 颜色注册，确认该视图实际使用的键；不重复猜测标准键。安装包路径用进程命令行（`ps aux`）定位，应用名可能带空格或后缀（如 `Qoder IDE.app`），不要猜目录。已知私有键：变更视图整行插入/删除底色为 `aicoding.diffWholeLineInsertedTextBackground` / `aicoding.diffWholeLineRemovedTextBackground`。
5. 主题入口文件可能通过 `include` 引用同目录兄弟文件，tokenColors 高亮规则常在被 include 的文件里；顶层查不到规则时跟随 include 再查。
6. 整行 diff 底色是多键叠加渲染：`diffEditor.insertedLineBackground` + `diffEditor.insertedTextBackground` + 私有整行键同时作用。只改一层会出现“改了没生效”或色相被其余层拽回旧色；正确做法是把参与叠加的所有层统一为同一色相、各给低透明度，后续微调只改最上层 alpha。
7. 标签页标题色会被 Git 装饰色覆盖（优先级高于 `tab.activeForeground`）。要关闭标签页染色且保留文件树和 diff 装饰，可用顶层开关 `workbench.editor.decorations.colors: false`。调整焦点描边时保留可见的键盘焦点状态。

## 修改

- 按当前工具的实际权限读取和编辑设置文件。写入被拒绝时，按会话支持的方式取得授权，或提供最小片段及插入位置供用户应用。
- 用支持 JSONC 的解析或编辑工具定位设置路径、主题作用域和 TextMate scope。在内存中从同一原始版本计算所有改动，再对目标键做一次最小编辑。保留其他设置项、注释与格式。会话期间文件已更新时，先读取并合并最新内容。
- 只改用户指出的区域。用户未指定色值时，选贴近主题现有配色的中性值，并说明调整方向（更亮、更暗、更透明）与备选值。
- 不修改主题扩展文件，不切换 `workbench.colorTheme`，不触碰无关设置。
- textMateRules 特异性：带语言前缀的 scope（如 `source.go keyword.function`）压过通用 scope（如 `keyword`）；用户规则追加在主题规则之后，同特异性后者胜。用“全局基色 + 语言专属色”分层覆盖。
- 迭代时一次调整一档，亮度约 3–6 灰阶，饱和度一档。两次调整均被否定时，取两个版本的颜色通道中点继续试调。
- 每轮记录修改的设置路径及旧值、新值。区分原来无此键、原来有覆盖和本次新建的作用域。批量调整前将这份恢复记录另存为唯一命名的备份文件。恢复时对照当前值，只还原仍属于本轮修改的目标键，已被用户再次修改的键保留并指出冲突。

## 验证与完成

- 写入前用真正支持注释和尾随逗号的 JSONC 解析器验证候选内容。写入后回读并比较完整文本差异，确认所有改动都命中预定键和作用域。
- 设置由 IDE 自动加载；视觉效果以用户观察为准。用户反馈未命中或不满意时，回到键名定位或色值调整，不宣称完成。
- 每轮向用户报告修改的作用域、设置键和旧值、新值，以及如何恢复旧覆盖或移除本轮新增的覆盖。用户确认满意或明确结束时停止。

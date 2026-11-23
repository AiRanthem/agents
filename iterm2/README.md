# 莫兰迪配色

将 `莫兰迪配色.json` 复制到 `~/Library/Application Support/iTerm2/DynamicProfiles/`，从 iTerm2 的 Profiles 菜单打开「莫兰迪配色」。字体使用 MesloLGS NF 13，背景透明度约为 12.47%。新机器需要安装 MesloLGS NF 才能还原字体和提示符图标。

如果使用相同的 Powerlevel10k 配置，在本目录执行以下命令恢复提示符配色。先检查补丁是否适用，检查通过后再应用。

```sh
patch -d "$HOME" -p1 --dry-run < powerlevel10k.patch &&
  patch -d "$HOME" -p1 < powerlevel10k.patch
```

新开的「莫兰迪配色」会话会使用蓝色路径、金色当前目录和绿色 Git 分支。

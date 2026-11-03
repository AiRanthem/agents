# 项目位置与保留资产

项目记录仓库为 `git@github.com:AiRanthem/agents.git`，分支 `projects/e2b-compatibility`。读取项目根 `AGENTS.md`、当前配置和受影响工作项文件，直接维护记录并提交、普通推送该分支。

主工作区位置记录在 `.project/main-workspace.json`，源码主检出映射记录在 `.project/repositories.yaml`。开发分支、基线及工作树以 `.project/state/<id>.yaml` 和实际 Git 工作树为准；本次说明升级保持源码位置不变。

现有 `.project-local/` 内的旧草稿、发布记录和本地数据继续留在 Git 外，仅作为保留资料，不作为编辑或发布项目文件的前置条件。未经逐项确认用途和保存位置，不删除这些资料；秘密文件和凭据继续留在 Git 外。

Git 推送失败时保留本地修改与提交，依据实际错误处理普通 Git 同步；未确认的外部操作结果单独记录。克隆项目记录不能替代未推送源码或本地数据的保存。

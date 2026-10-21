# Windows 客户端配置工具

访客打开 `/agents/setup` 或看板「智能体配置」，下载 `WorkBuddy-Setup.exe`，在自己的 Windows 10 / 11 x64 电脑上双击执行。工具包含所需运行时，无需安装 Python 或以管理员身份运行。API Key 由网关管理员单独提供，在工具中输入。

源码入口是 `wb_agent_setup.py`，客户端配置读写、备份、还原直接复用 `wb_agents.py`。网页只提供静态说明、下载链接和当前访问地址；不会调用服务器的 `/agents/apply` 或 `/agents/restore`。下载文件不携带用户 Key。

## 本地构建（仅开发者需要 Python）

在 Windows x64 上使用 Python 3.9+ 的独立构建环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements-agent-build.txt
.\.venv\Scripts\python.exe scripts/build_agent_setup.py
.\.venv\Scripts\python.exe tests/_test_agent_setup.py --exe dist/agent-setup/WorkBuddy-Setup.exe
```

输出为 `dist/agent-setup/WorkBuddy-Setup.exe` 和 `SHA256SUMS`。PyInstaller 仅是构建依赖，网关仍然只依赖 Python 标准库。EXE 的 `--license` 参数显示随包附带的项目许可证。

## 自动构建与下载地址

每个 PR 会构建 EXE，在移除 Python PATH 的子进程中验证六种客户端配置与原字节还原，并上传 `windows-client` 构建产物。合并到本 fork 的 main 后，完整测试矩阵与 EXE 检查均通过，才会发布或更新独立的 `windows-client` 预发布。

- EXE：`https://github.com/whysmx/workbuddy2api-hub/releases/download/windows-client/WorkBuddy-Setup.exe`
- 校验值：同一发布中的 `SHA256SUMS`。
- 发布说明记录构建源码提交；标记为 prerelease 且 latest=false，网关正式版自更新不受影响。
- 第一次合并前下载地址尚无资产；可先从 PR 检查的构建产物或本地构建目录验证 EXE。

## 本机数据

备份与状态保存在当前用户的 `.wb-agent-config/`。所有修改在本机进行；只向用户填写的网关请求模型列表。还原会恢复首次配置前的内容，请保留该目录。ZCode 会在运行中保存配置，配置或还原前应退出 ZCode。

## 兼容命令行

EXE 也接受原有 CLI 子命令，例如 `WorkBuddy-Setup.exe list`、`WorkBuddy-Setup.exe apply --client opencode --base-url https://example.test/v1`、`WorkBuddy-Setup.exe restore --client opencode`。无参数启动中文交互向导。

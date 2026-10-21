"""Windows console wizard, also bundled as a self-contained executable.

Configuration, detection and restoration use wb_agents unchanged. The wizard
only collects input on the client computer; no panel credentials are needed.
"""

import argparse
import getpass
import os
import sys
from urllib.parse import urlsplit, urlunsplit

import wb_agents


def normalize_gateway(value):
    value = str(value or "").strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or any(c.isspace() or ord(c) < 32 for c in value)):
            raise ValueError()
        parsed.port  # Reject malformed/out-of-range ports before requesting.
    except ValueError:
        raise wb_agents.AgentConfigError(
            "请输入完整的 http:// 或 https:// 网关地址，不要包含密码、查询参数或 #。")
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        path += "/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def choose(prompt, count, default=None):
    while True:
        raw = input(prompt).strip()
        if not raw and default is not None:
            return default
        if raw.isdigit() and 0 <= int(raw) <= count:
            return int(raw)
        print("请输入 0 到 %d 之间的数字。" % count)


def confirm(prompt):
    return input(prompt + " [y/N]: ").strip().lower() in ("y", "yes")


def configure(client_id, entry, state_dir, home, gateway):
    if client_id == "zcode":
        print("请先退出 ZCode，避免它覆盖刚写入的配置。")
    if not entry["installed"]:
        print("未检测到该客户端；如果尚未安装，请先安装客户端。")
    if (entry.get("applied") or {}).get("external_change"):
        print("检测到配置文件被手动修改；重新配置会更新网关相关设置。")
    address = input("网关地址%s: " % (" [" + gateway + "]" if gateway else "")).strip()
    address = normalize_gateway(address or gateway)
    key = getpass.getpass("API Key（输入内容不显示）: ").strip()
    if not key:
        raise wb_agents.AgentConfigError("API Key 不能为空。")
    try:
        print("正在验证 API Key 并获取模型列表……")
        models = wb_agents.fetch_models_from_gateway(address, key)
        if not models:
            raise wb_agents.AgentConfigError("网关没有返回可用模型，请联系提供 API 的管理员。")
        for number, model in enumerate(models, 1):
            print("  %d. %s" % (number, model["id"]))
        picked = choose("选择默认模型 [1，0 取消]: ", len(models), 1)
        if not picked:
            return gateway
        model_id = models[picked - 1]["id"]
        print("\n客户端：%s\n网关：%s\n模型：%s" % (entry["label"], address, model_id))
        print("将修改以下本机文件（原文件会自动备份）：")
        for path in entry["config_paths"]:
            print("  " + path)
        if not confirm("确认配置"):
            print("已取消。")
            return gateway
        result = wb_agents.integrate(state_dir, client_id, address, key,
                                     model=model_id, models=models, home=home)
        print("配置成功，已写入 %d 个文件。请重新启动 %s。" % (
            len(result["files"]), entry["label"]))
        return address
    except Exception as exc:
        # Never echo a key even if a network error includes user input.
        raise wb_agents.AgentConfigError(str(exc).replace(key, "***")) from None


def wizard(home=None, state_dir=None, gateway=""):
    home = os.path.abspath(home or os.path.expanduser("~"))
    state_dir = state_dir or os.path.join(home, ".wb-agent-config")
    print("WorkBuddy · Windows 客户端配置工具")
    print("配置当前用户的客户端。API Key 由网关管理员提供。")
    print("备份目录：%s\n" % state_dir)
    while True:
        clients = wb_agents.overview(state_dir, home)
        ids = list(clients)
        for number, client_id in enumerate(ids, 1):
            entry = clients[client_id]
            status = "已配置" if entry["configured"] else (
                "已检测到" if entry["installed"] else "未检测到")
            print("  %d. %-20s %s" % (number, entry["label"], status))
        picked = choose("\n选择客户端 [0 退出]: ", len(ids))
        if not picked:
            return 0
        client_id = ids[picked - 1]
        entry = clients[client_id]
        action = choose("1 配置客户端 / 2 还原原始配置 / 0 返回: ", 2)
        try:
            if action == 1:
                gateway = configure(client_id, entry, state_dir, home, gateway)
            elif action == 2:
                if not entry["configured"]:
                    print("这台电脑没有该客户端的备份记录。")
                elif confirm("还原 %s 至首次配置前的状态？后续手动修改也会被覆盖" % entry["label"]):
                    wb_agents.restore(state_dir, client_id, home=home)
                    print("还原成功，请重新启动客户端。")
        except (wb_agents.AgentConfigError, OSError, ValueError) as exc:
            print("操作失败：%s" % exc)
        print()


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    # Keep the complete existing CLI for automation and packaged smoke tests.
    if any(arg in ("list", "status", "apply", "restore") for arg in args):
        return wb_agents.main(args)
    parser = argparse.ArgumentParser(description="WorkBuddy Windows 客户端配置工具")
    parser.add_argument("--gateway", default="", help="预填网关地址")
    parser.add_argument("--license", action="store_true", help="查看许可证")
    opts = parser.parse_args(args)
    if opts.license:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "LICENSE"),
                  encoding="utf-8") as source:
            print(source.read())
        return 0
    if os.name != "nt":
        parser.error("交互配置工具仅支持 Windows；命令行请使用 wb_agents.py。")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("请双击 EXE 或在终端中运行；自动化可使用 list / apply / restore 子命令。")
    try:
        return wizard(gateway=normalize_gateway(opts.gateway) if opts.gateway else "")
    except (EOFError, KeyboardInterrupt):
        print("\n已退出。")
        return 0
    except Exception as exc:
        print("无法启动配置工具：%s" % exc)
        input("按回车键关闭窗口……")
        return 1


if __name__ == "__main__":
    sys.exit(main())

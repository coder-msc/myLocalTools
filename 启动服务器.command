#!/bin/bash
# ============================================================
#   接口调试工具箱 DevToolbox - 启动服务器 (macOS 版)
#   对应 Windows 版的 启动服务器.bat
#
#   用法（首次使用需赋一次执行权限，之后双击即可启动）:
#     chmod +x 启动服务器.command
#
#   说明: .command 是 macOS 的"可双击脚本"格式，Finder 里双击
#         会自动打开终端执行，等价于 Windows 双击 .bat。
# ============================================================

PORT=6868
# 脚本所在目录（等价 bat 的 cd /d "%~dp0"，保证相对路径的资源都能找到）
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "============================================"
echo "   接口调试工具箱 DevToolbox"
echo "============================================"
echo

# [1/4] 检查 python3（macOS 默认没有 python 命令，只有 python3）
if ! command -v python3 >/dev/null 2>&1; then
    echo "[错误] 未检测到 python3，请先安装 Python 3"
    echo "下载地址: https://www.python.org/downloads/"
    echo "或执行:   xcode-select --install"
    echo
    exit 1
fi

# [1/4] 结束占用端口的旧服务
# lsof -ti tcp:端口 输出占用该端口的 PID 列表，kill -9 强杀（等价 taskkill /F）
OLD_PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null)
if [ -n "$OLD_PIDS" ]; then
    echo "[1/4] 端口 $PORT 被占用 (PID: $(echo $OLD_PIDS | tr '\n' ' '))，正在结束..."
    echo "$OLD_PIDS" | xargs kill -9 2>/dev/null
    sleep 1
    echo "       旧服务已清理"
else
    echo "[1/4] 端口 $PORT 空闲"
fi

# [2/4] 启动服务器
# 优先方案: 让 Terminal 新开一个窗口运行 server.py（等价 Windows 的 start cmd /k，
#           服务器日志显示在该窗口里，关闭窗口即停止服务器）
# 兜底方案: osascript 受限（如自动化权限被拒）时，退回 nohup 后台运行，日志写文件
cd "$DIR" || exit 1
LAUNCHED_WINDOW=0
if command -v osascript >/dev/null 2>&1; then
    osascript -e "tell application \"Terminal\" to do script \"cd '$DIR' && python3 server.py\"" >/dev/null 2>&1 \
        && LAUNCHED_WINDOW=1
fi
if [ "$LAUNCHED_WINDOW" -eq 0 ]; then
    echo "[2/4] 新终端窗口启动受限，改为后台运行（日志: server.log）"
    nohup python3 server.py > "$DIR/server.log" 2>&1 &
else
    echo "[2/4] 服务器已在新的终端窗口启动"
fi

# [3/4] 等待服务器就绪（最多 15 秒，逐秒探测首页 HTTP 状态码）
echo "[3/4] 等待服务器就绪（最长 15 秒）..."
READY=0
for i in $(seq 1 15); do
    # curl -s 静默 -o /dev/null 丢弃响应体 -w 只输出状态码 --max-time 单次探测限时 2 秒
    CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "http://localhost:$PORT/" 2>/dev/null)
    if [ "$CODE" = "200" ]; then
        READY=1
        break
    fi
    sleep 1
done

# [4/4] 结果提示 + 打开浏览器
if [ "$READY" -eq 1 ]; then
    echo
    echo "============================================"
    echo "  启动成功！"
    echo "  本机访问:   http://localhost:$PORT/"
    echo "  局域网访问: 用本机 IP 替换 localhost"
    echo "============================================"
    # 用系统默认浏览器打开（等价 Windows 的 start "" "http://..."）
    open "http://localhost:$PORT/"
    if [ "$LAUNCHED_WINDOW" -eq 0 ]; then
        echo
        echo "服务器在后台运行，停止方法:  kill \$(lsof -ti tcp:$PORT)"
        echo "运行日志见 server.log"
    else
        echo
        echo "关闭服务器的终端窗口即可停止服务，本窗口可关闭。"
    fi
    # 停留片刻让用户看清提示后自动退出（等价 bat 的 ping -n 5 延时）
    sleep 3
    exit 0
else
    echo
    echo "[错误] 等待 15 秒后仍未响应 HTTP 请求"
    echo "请查看服务器终端窗口（或 server.log）中的报错信息。"
    exit 1
fi

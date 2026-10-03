# 首次推送到 GitHub（需要走本地代理）

## 本机实测结论

| 检查项 | 实测结果 |
|---|---|
| 系统代理配置 | `127.0.0.1:7897`（Clash Verge 默认端口） |
| 代理客户端 | **正在运行**（7897 有大量活跃连接） |
| git 代理配置 | **未配置** |
| 直连 `github.com:443` | **失败**（`Connection was reset`） |

**根因**：git **不读取 Windows 系统代理**。浏览器能上 GitHub 是因为浏览器走系统代理，
而 `git push` 走的是直连，于是被重置。

**结论：只要把代理显式告诉 git 即可。代理本身没问题，不用换平台。**

> 说明：最初误判为"代理没运行"，是因为排查命令被 DSH 沙箱限制了端口/进程查询，
> 给出了错误结论。以 `netstat` 的结果为准。

---

## 最省事：双击 `push-to-github.bat`

脚本会依次完成：

1. 自动找到 git（GitHub Desktop 自带的那个，不需要 PATH）
2. **检查 7897 端口是否有监听**；没有就停下来提示你启动代理
3. 把 `http.proxy` / `https.proxy` 写入 git 全局配置
4. 配好 `origin`
5. 执行 `git push -u origin main`

成功会打印 `[OK] Pushed to GitHub successfully.`

---

## 手动版（等价操作）

在 **cmd** 里逐行执行：

```cmd
D:
cd \FPGA
set PATH=%LOCALAPPDATA%\GitHubDesktop\app-3.5.2\resources\app\git\cmd;%PATH%

rem 1) 确认代理在监听（有输出即可）
netstat -ano | findstr ":7897 " | findstr LISTENING

rem 2) 让 git 走代理
git config --global http.proxy  http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
git config --global core.pager cat

rem 3) 推送
git push -u origin main
```

`core.pager cat` 只是顺手修掉 `cannot spawn less`——GitHub Desktop 自带的 git
没有打包分页器，那条报错本身无害。

---

## 验证成功

```cmd
git branch -vv
```

应显示 `main ... [origin/main]`。刷新仓库页面应看到 55 个文件、8 个提交。

---

## 排查顺序

| 现象 | 处理 |
|---|---|
| `Nothing is listening on port 7897` | 启动代理客户端并开启系统代理；若端口不同，改 `push-to-github.bat` 顶部的 `PROXY_PORT` |
| 仍是 `Connection was reset` | 代理可能只暴露 SOCKS 端口 → 把 `PROXY_SCHEME` 改成 `socks5` 并填对应端口 |
| 卡住不动超过 1 分钟 | 按 `Ctrl+C` 中断，多半是认证被卡；改用 Personal Access Token |
| 提示 `non-fast-forward` | 远程仓库不是空的（建仓时勾了 README）→ 需要先 `git fetch` 再决定合并或强推 |
| 问用户名/密码 | 用户名填 GitHub 用户名，**密码填 Personal Access Token**，不是登录密码 |

**Personal Access Token 生成**：GitHub 头像 → Settings → Developer settings →
Personal access tokens → Tokens (classic) → Generate new token → 勾选 `repo`。

---

## 用完想清掉代理配置

```cmd
git config --global --unset http.proxy
git config --global --unset https.proxy
```

换到不需要代理的网络时执行即可，不影响已完成的推送。

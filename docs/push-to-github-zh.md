# 首次推送到 GitHub（网络受限环境）

本机实测情况：

- `github.com:443` **直连失败**（`Connection was reset`）
- 系统代理已配置为 `127.0.0.1:7897`，但**代理客户端没有运行**（该端口无监听）
- git **没有配置代理**，所以 `git push` 走的是直连，必然失败

结论：**先启动代理客户端，再让 git 走代理**。

---

## 步骤 1：启动代理客户端

打开你的代理软件（Clash Verge / v2rayN / 其它），开启系统代理。

确认端口在监听（在 PowerShell 里执行，能看到"在监听"即可）：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 7897 -ErrorAction SilentlyContinue
```

> 如果你的客户端端口不是 7897，请在后面的命令里换成实际端口。
> 常见端口：Clash 7890 / 7897，v2rayN 10809，其它 1080、2080。

**验证代理确实能到 GitHub**（这条通过再往下做）：

```powershell
curl.exe -sS -o NUL -w "%{http_code}\n" --max-time 20 https://github.com
```

期望输出 `200` 或 `301`。若仍是失败，说明代理没生效，先解决代理再继续。

---

## 步骤 2：让 git 走代理

在 **cmd** 里执行（把 `7897` 换成你的实际端口）：

```cmd
D:
cd \FPGA
set PATH=%LOCALAPPDATA%\GitHubDesktop\app-3.5.2\resources\app\git\cmd;%PATH%

git config --global http.proxy http://127.0.0.1:7897
git config --global https.proxy http://127.0.0.1:7897
git config --global core.pager cat
```

- 前两条让 git 走代理（`https.proxy` 在你的 git 版本里是关键的那条）。
- 第三条顺手修掉截图里的 `cannot spawn less`：GitHub Desktop 自带的 git 没打包分页器。
  这条报错**无害**，只影响 `git log` 的翻页显示。

---

## 步骤 3：重新推送

远程已经配好了（上次已显示 `Added remote origin.`），所以直接推：

```cmd
git push -u origin main
```

看到类似下面的输出就是成功了：

```
Writing objects: 100% ...
To https://github.com/LSXZCD/LogicLens.git
 * [new branch]      main -> main
branch 'main' set up to track 'origin/main'.
```

---

## 验证

```cmd
git log --oneline -1
git branch -vv
```

`git branch -vv` 应显示 `main ... [origin/main]`。
浏览器刷新仓库页面，应看到 53 个文件、7 个提交。

---

## 如果代理方案走不通

### 方案 B：改用 Gitee（国内，无需代理）

1. 在 https://gitee.com 建一个空仓库（同样**不要**勾选初始化 README/.gitignore）
2. 改远程地址并推送：

```cmd
git remote set-url origin https://gitee.com/<你的Gitee用户名>/LogicLens.git
git push -u origin main
```

之后队友从 Gitee 克隆。**代价**：CI 不能用了（`.github/workflows/` 是 GitHub 专用），
需要改成 Gitee Go 或本地跑测试；其它功能不受影响。

### 方案 C：SSH 方式

若代理只支持 SOCKS5，可以给 git 单独指定：

```cmd
git config --global http.proxy socks5://127.0.0.1:7897
git config --global https.proxy socks5://127.0.0.1:7897
```

---

## 出问题时的排查顺序

1. 代理客户端在运行，且系统代理已开启？
2. `curl.exe` 能拿到 github.com 的 200/301 吗？
3. `git config --global --get https.proxy` 有输出吗？
4. 三条都正常仍失败 → 把 `git push` 的完整输出发出来。

排查完不需要时，可以清掉代理配置：

```cmd
git config --global --unset http.proxy
git config --global --unset https.proxy
```

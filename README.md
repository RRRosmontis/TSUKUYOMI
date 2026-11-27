# live.rrrosmontis.icu —— 全栈源码汇总仓库

把 live.rrrosmontis.icu 直播链路的三侧代码（前端 / 弹幕端 / 后端）收进一个仓库，便于统一版本管理与后续迁移。

建立时间：2026-11-27（Asia/Shanghai）
当前状态：已推送至 **GitHub `RRRosmontis/TSUKUYOMI`**（分支 `main`），公开仓库。

## 目录结构

```
.
├── frontend/          live 站点前端（ESA Pages 静态站点 + 部署脚本）
├── danmaku/           弹幕客户端（Windows 侧 Python 程序 / PyInstaller 工程）
└── backends/
    ├── linux/         Linux 侧后端（SRS 源码树 + danmaku 服务 + nginx/haproxy 配置）
    └── windows/       Windows 侧后端（SRS 安装目录配置 + live 业务后端）
        ├── SRS/       C:\call\SRS 的配置与启动脚本（不含 objs/ 与安装器）
        └── live/      C:\call\backends\live 的业务后端（8000 服务 + live-api + 弹幕后端）
```

## 各目录来源

| 目录 | 来源 | 版本 / 校验 |
|---|---|---|
| `frontend/` | 本机 `/root/deliverables/live-rrrosmontis-icu-web-20261127.zip`（2026-11-27 13:58 打包，解压后原样纳入） | zip sha256 `37c8ec05…86a139`；包内 `manifest.sha256` 全部校验通过 |
| `danmaku/` | `https://git.rrrosmontis.icu/RoyirinRosmontis/tsukuyomi-danmaku` | `9258dce`（2026-08-18） |
| `backends/linux/` | `https://git.rrrosmontis.icu/RoyirinRosmontis/srs-and-danmaku-linux` | `cb14347`（2026-09-06） |
| `backends/windows/` | bj（39.97.55.150）上的 `C:\call\SRS` 与 `C:\call\backends\live`，按规则筛选后打包回传 | 收集包 md5 `2dee9a9552fc1bc01eab6ab4fa82a477`（402,574 B，114 个文件） |

`frontend/` 内部保留打包时的原始层次：`live-rrrosmontis-icu-web/`（站点源码）、`deployment/`（ESA 边缘入口 + 部署脚本）、`README.md`、`manifest.sha256`。

## 收集时的排除规则

按“只收源码与配置”处理，以下内容**不在仓库内**：

- 二进制：`SRS/objs/srs.exe`（35 MB）、`SRS/uninst.exe`（`danmaku/dist/danmaku.exe` 例外，见下）
- 运行日志：`*.log`（含 SRS 侧约 330 MB 的 nssm 日志、danmaku/live2d/live-api 日志）
- 运行时产物：`__pycache__/`、`*.pyc`、`*.db`（`live.db`、`live-api/live.db`）
- 备份文件：`*.bak`、`*.bak.*`、`*.before-*`（`srs.conf.bak.202610102145`、`live_api.py.bak.20260927174500`、`run-8000backend.bat.bak`、`config.before-secondary-20261007-1840.bak`、`config.json.before-443-20261007-201756` 共 5 个，已从仓库删除并写入 `.gitignore`）
- 构建目录：`SRS/objs/`（Cygwin 运行库与编译输出）
- 两个上游仓库的 `.git/`（本仓库是全新历史）

## 刻意保留的二进制：`danmaku/dist/danmaku.exe`

| 项 | 值 |
|---|---|
| 大小 | 48,642,775 B（约 46.4 MiB） |
| 类型 | PE32+ GUI x86-64（PyInstaller 打包产物） |
| 来源 | `tsukuyomi-danmaku@9258dce:dist/danmaku.exe` |
| blob sha1 | `f1c983388e29308f95908b62e11f0f3022d6970d`（与上游 blob 逐字节一致） |
| sha256 | `9146457bf9f95d725463e41c1a73e7c2c4416d7a1f7f9e3179f507ff01f5cf4c` |

这是**唯一入库的 exe**：`.gitignore` 的 `*.exe` 规则仍拦截其他可执行文件，本文件通过 `!danmaku/dist/danmaku.exe` 例外规则显式放行。重新打包可用同目录的 `danmaku.spec`；若产物有变化，记得同步更新上表的校验值。

## 已清空的敏感文件（保留空文件占位）

以下文件**保留文件名但内容为空（0 字节）**，原内容仍在原服务器上，本仓库不携带凭据：

| 文件 | 原位置 |
|---|---|
| `backends/windows/live/live-api/secrets.json` | bj `C:\call\backends\live\live-api` |
| `backends/windows/live/live-api/live_svc_token.txt` | 同上 |
| `backends/windows/live/live-api/config.json` | 同上 |
| `backends/linux/danmaku/danmaku_auth.json` | `srs-and-danmaku-linux` 仓库 |

> 注意：Windows 侧的 `SRS/conf/srs.conf` 是线上实际在用的 SRS 配置，其中包含 http_hooks 回调地址等部署参数，本仓库**原样保留**。若日后要公开或共享此仓库，请先复核该文件。

## 远程仓库

| 项 | 内容 |
|---|---|
| 远程 | `https://github.com/RRRosmontis/TSUKUYOMI`（公开） |
| 分支 | `main` |
| 推送方式 | HTTPS + 账号级 PAT（存放于操作机 `~/.git-credentials`，`credential.helper=store`） |

日常同步：

```bash
cd /tmp/live-stack
git add -A && git commit -m "..." && git push
```

维护提醒：

1. 本仓库为**公开**仓库，提交前务必确认没有把凭据带回来（上表中的占位文件保持 0 字节）。
2. `backends/windows/SRS/conf/srs.conf` 是线上在用的 SRS 配置，含 http_hooks 回调地址等部署参数，公开可见，修改前请复核是否含敏感值。
3. `.gitignore` 已拦截 `*.log`、`*.db`、`*.pyc`、`*.exe`（`danmaku/dist/danmaku.exe` 为例外）、`objs/`、`*.bak`、`*.bak.*`、`*.before-*`。

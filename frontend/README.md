# live.rrrosmontis.icu 前端源码包

打包时间：2026-11-27  
来源仓库：`html-backups` Gitea，提交 `c77d619`，路径 `rrrosmontis.icu/live-rrrosmontis-icu-web/`

## 内容

```
live-rrrosmontis-icu-web/      站点源码（静态，无构建步骤）
deployment/
  esa-pages/live/index.js      ESA 边缘入口脚本（仅处理静态资产做不到的路由）
  deploy-esa-pages.sh          ESA 五前端部署脚本（本包为 live 单目标）
manifest.sha256                全部文件校验值
```

源码共 24 个文件，约 3.0 MB，包含：

- `anchor/index.html` — 主播控制台入口
- `players/player.html`、`players/8000.html`、`players/whep.html` — 播放器页面（含 clean URL 兼容）
- `players/` 下的播放器资源
- `js/live-common.js` — 公共逻辑
- `startLive.html` — 开播入口
- `_redirects` — Pages 重定向规则（由 Cloudflare Pages 消费，不作为静态文件对外提供）
- `BingSiteAuth.xml`

## 线上链路

| 线路 | 项目 |
|---|---|
| 默认线路（ESA） | `rrrosmontis-live`（ESA Functions & Pages，静态资产随入口脚本一起部署） |
| 海外线路 / 备份（Cloudflare Pages） | `live-rrrosmontis-icu-web`，域名 `live-rrrosmontis-icu-web.pages.dev` |

访问入口：`https://live.rrrosmontis.icu/`

## 路由行为

- `/` → 302 到 `https://www.rrrosmontis.icu/services/slm/`（Pages `_redirects` 与 ESA 入口脚本两处一致）
- `/players/player.html` → clean URL 重定向到 `/players/player`，再正常提供播放器
- 其余路径由静态资产直接提供；ESA 入口脚本对未命中资产返回 404

## 一致性校验

打包前已把本地源码与线上 Cloudflare Pages 逐文件比对（2026-11-27）：

| 文件 | 本地 / 线上 |
|---|---|
| `js/live-common.js` | `128752de3bde` ✅ |
| `players/player.html` | `68ce9f0c3ae1` ✅ |
| `anchor/index.html` | `d2a0dd9dd100` ✅ |
| `players/whep.html` | `efd42fede91a` ✅ |
| `startLive.html` | `1f7824498a5c` ✅ |
| `_redirects` | 本地有、线上不提供（Pages 规则文件，正常） |

## 部署方式

静态站点，无需构建。

Cloudflare Pages：

```bash
wrangler pages deploy live-rrrosmontis-icu-web --project-name=live-rrrosmontis-icu-web --branch main
```

ESA：

```bash
./deployment/deploy-esa-pages.sh live
```

脚本默认读取 `/root/esa-cli/node_modules/.bin/esa` 和迁移凭据文件；在别的机器上运行时通过 `ESA_CLI`、`ESA_CRED_FILE` 覆盖路径。也可以用 `ALIBABA_CLOUD_ACCESS_KEY_ID` / `ALIBABA_CLOUD_ACCESS_KEY_SECRET` 环境变量。

## 重定向更新（2026-11-27）

- 根路径 `/` 已从 `https://rosmanka.rrrosmontis.icu/` 改为 `https://www.rrrosmontis.icu/services/slm/`（302）。
- 同步修改两处：`live-rrrosmontis-icu-web/_redirects`（Cloudflare Pages）与 `deployment/esa-pages/live/index.js`（ESA 边缘入口）。
- 已部署：Pages 项目 `live-rrrosmontis-icu-web`；ESA 项目 `rrrosmontis-live`。
- 线上验证：`https://live.rrrosmontis.icu/` 返回 302 → 新地址；`/anchor/` 200；`/players/player.html` 正常 clean URL 重定向；目标页 200。

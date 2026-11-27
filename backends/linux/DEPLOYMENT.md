# 部署记忆文档 — srs-and-danmaku-linux

> 部署位置：**cf 服务器**（Celestial-Fulcrum，Ubuntu 24.04，本仓库即部署目录 `/home/srs`）
> 部署日期：2026-09-01 ~ 09-03
> 上游：https://git.rrrosmontis.icu/RoyirinRosmontis/srs-and-danmaku-linux（本仓库）

## 1. 总体架构

```
外网 443（Sakura Frp HTTPS 隧道 ×2，TLS 透传到本机）
  ├── srs_oversea: tsk.aeolianchi.me  (frp-age 节点)  ──┐
  └── srs_cn:      tsk.rrrosmontis.icu (frp-hip 节点) ─┴→ 本机 :18443
                                                        │
                                            HAProxy [TLS终结 + 按SNI选证 + 首字节嗅探]
                                            ├── 解密后 0x03 (RTMPS 推流) → 127.0.0.1:1935 (SRS)
                                            └── HTTP (拉流/弹幕)         → 127.0.0.1:8445 (nginx)
                                                                              ├── /live/   → 127.0.0.1:8080 (SRS HTTP-FLV/HLS)
                                                                              └── /danmaku → 127.0.0.1:55556 (弹幕 WebSocket)
```

- **推流**：`rtmps://tsk.aeolianchi.me:443/live/room_<房间号>` 或 `rtmps://tsk.rrrosmontis.icu:443/live/room_<房间号>`（OBS / ffmpeg 均可）
- **拉流**：`https://tsk.rrrosmontis.icu/live/room_<房间号>.flv`（或 `.m3u8`，me 域名同）
- **弹幕**：`wss://tsk.rrrosmontis.icu/danmaku`
- 设计要点：全部业务共用 443 对外端口；推流用 **RTMPS**（裸 RTMP 无 SNI 无法过 HTTPS 隧道）；nginx stream ssl_preread 分不开「同 SNI 的 RTMPS/HTTPS」，故用 **HAProxy 先终结 TLS 再嗅探首字节**（RTMP 握手恒为 0x03，HTTP 以方法字符开头）。

## 2. 本机组件与路径

| 组件 | 路径 | 说明 |
|---|---|---|
| SRS 源码+编译产物 | `/home/srs/trunk/` | SRS 6.0.172（上游 tag v6.0-b0），二进制 `trunk/objs/srs` |
| 弹幕后端 | `/home/srs/danmaku/danmaku_backend.py` | FastAPI + uvicorn，端口 55556，venv 在 `danmaku/venv/`（gitignore） |
| HAProxy 配置 | `conf/haproxy/haproxy.cfg` | 软链 → `/etc/haproxy/haproxy.cfg` |
| nginx 8445 口 | `conf/nginx/srs-https-8445.conf` | 软链 → `/etc/nginx/sites-enabled/srs-https-8445.conf`（明文 HTTP，TLS 已在 HAProxy 终结） |
| 证书 pem 构建脚本 | `conf/certs/build-pems.sh` | 生成 `/etc/haproxy/certs/*.pem`（cert+key 合一；**私钥不入库**，pem 只在 /etc 下） |
| 主配置 | `trunk/conf/srs.conf` | RTMP 1935 / API 1985 / HTTP 8080 / WebRTC 8000(UDP) |

### systemd 服务（均 enabled 开机自启）

| 服务 | 启动 | 日志 |
|---|---|---|
| `srs-server.service` | `trunk/run.sh`（`./objs/srs -c ./conf/srs.conf`，WorkingDirectory=/home/srs/trunk） | `journalctl -u srs-server -f` |
| `srs-danmaku.service` | `danmaku/venv/bin/python danmaku_backend.py` | `journalctl -u srs-danmaku -f` |
| `haproxy.service` | `/etc/haproxy/haproxy.cfg`（软链至 conf/） | `journalctl -u haproxy -f` |

## 3. 证书与续期

- `tsk.aeolianchi.me`：acme.sh（阿里云 DNS API，ecc），装于 `/etc/nginx/cert/tsk.aeolianchi.me/`
- `tsk.rrrosmontis.icu`：复用 acme.sh 泛域名证书 `*.rrrosmontis.icu`（`/home/server/cert/extra/rrrosmontis.icu/`）
- **续期钩子**：两张证书的 `--reloadcmd` 均为 `conf/certs/build-pems.sh && systemctl reload nginx && systemctl reload haproxy`，续期后自动重拼 pem 并重载，无需人工干预

## 4. 开播通知链路（http_hooks）

```
SRS on_publish/on_unpublish
  → https://api.rrrosmontis.icu/v1/live/publish/local/on_publish   (bj nginx 公网入口)
  → bj:1986 /remote_srs/local/on_publish                            (live_monitor.py, napcat 伴生 Flask)
  → 按 record.json 关注列表发 QQ 通知；返回 {"code":0} 放行推流
```

- SRS 6.0 的 http_hooks 原生支持 https 回调（源码 http client 带 TLS）
- **流名必须为 `room_<房间号>`** 才会被识别为房间；hook 失败 SRS 会拒绝推流
- 主站（aliyun）走 `/remote_srs/on_publish`（site=1），本机为副站（`/remote_srs/local/...`，site=2）

## 5. 前端页面（已弃用）

- `lfr.aeolianchi.me`（hk 托管）已于 2026-09-03 弃用：域名解析删除，hk 上 nginx 配置 / `/home/srs-frontend` / 证书及 acme.sh 条目均已清除
- 历史备份：cf `/home/.AgentsEditBackups/2026-9-3/hk/`（nginx conf、index.html、证书）
- 页面源码副本仍存于 cf `/root/lfr-static/`，如需恢复可重新部署

## 6. 从零重建步骤（换机/重装备忘）

1. `git clone` 本仓库到部署目录（如 `/home/srs`）
2. 补编译依赖：`apt install -y automake autoconf libtool pkg-config tclsh cmake`（另需 gcc/g++/make）
3. **补齐 `trunk/3rdparty/`**（仓库 .gitignore 排除了它，裸仓库无法编译）：从官方 `ossrs/srs` tag `v6.0-b0` 稀疏克隆 `trunk/3rdparty` 拷入——版本号必须与本仓库 `trunk/src/core/srs_core_version6.hpp` 的 `VERSION_REVISION` 一致（当前 172）
4. 编译：`cd trunk && ./configure && make -j$(nproc)`（大任务放 tmux）
5. 弹幕后端：`python3 -m venv danmaku/venv && danmaku/venv/bin/pip install fastapi 'uvicorn[standard]'`
6. 软链配置：`conf/haproxy/haproxy.cfg → /etc/haproxy/haproxy.cfg`、`conf/nginx/srs-https-8445.conf → /etc/nginx/sites-enabled/`
7. 证书签发（acme.sh dns_ali）+ `build-pems.sh` + 续期钩子（见第 3 节）
8. systemd：创建 `srs-server.service` / `srs-danmaku.service`（见第 2 节），`daemon-reload && enable --now`
9. Sakura Frp：两条 HTTPS 隧道绑定各自域名，本地目标 `127.0.0.1:18443`

## 7. 已知行为与坑

- **SRS 对不在线流的 .flv 请求会挂住连接等流出现**（不是 404）——拉流方需自行设置超时；测试时推流建立延迟会造成"拉到 0 字节"的假象
- `srs.conf` 中 `rtc_server.candidate = 39.97.55.150`（bj 公网 IP）：WebRTC 播放需 UDP 8000 能路由到该地址，当前未配转发，WebRTC 播放未打通（HTTP-FLV/HLS 不受影响）
- `daemon off` + 控制台日志是配合 systemd 的刻意配置，非调试残留
- 免费版 Sakura 节点偶发新连接抖动，客户端重试即可
- `run.sh` 依赖 systemd 的 `WorkingDirectory=/home/srs/trunk`（内用相对路径），改路径两处同步

## 8. 本仓库相对上游的变更

| 文件 | 变更 |
|---|---|
| `trunk/run.sh` | 修正旧绝对路径（srs-server-6.0-b0 → 当前部署路径），改为相对路径 |
| `trunk/conf/srs.conf` | http_hooks 指向 api.rrrosmontis.icu 公网入口（bj live_monitor） |
| `conf/` | 新增：HAProxy 分流配置、nginx 8445 拉流/弹幕口、pem 构建脚本 |
| `.gitignore` | 追加 `danmaku/venv/`、`*.log` |
| `DEPLOYMENT.md` | 本文档 |

## 9. 快速运维

```bash
systemctl restart srs-server srs-danmaku   # 重启业务
journalctl -u srs-server -f                # 看 SRS 日志（含 hook 回调记录）
/home/srs/conf/certs/build-pems.sh         # 手动重建 HAProxy pem
tmux attach -t <会话>                       # 编译类长任务用 tmux（单字母命名惯例）
```

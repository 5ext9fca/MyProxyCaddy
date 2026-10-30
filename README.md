# MyCaddy

服务器唯一公网 HTTP/HTTPS 入口。公共 Caddy 管理 80/443、TLS 证书及业务路由，
不构建业务镜像、不挂载业务静态文件或数据库。默认同一公网 IPv4（也可使用域名）：

- `/sub`、`/sub/*` → `clash-subscription:8080`，路径不裁剪。
- 其余路径 → `mycollab-web:80`，由 MyCollab 内部 Web 提供 API、静态文件和 SPA。

三个 Compose 项目均使用外部网络 `caddy-public`，生命周期独立。
MyCollab 只有 Web 加入公共网络，backend 与 db 留在其默认网络。
该共享网络只接入可信业务容器；内部 Web 信任私有地址代理的转发头，
保留公共入口传来的 HTTPS 信息供 Django 判断安全请求。

## 首次部署

需要 Docker Engine 与 Compose。将本目录放到服务器（例如 `/opt/MyCaddy`）：

```sh
cd /opt/MyCaddy
cp .env.example .env
# 编辑 PUBLIC_HOST 为实际公网 IPv4；示例 IP 不能申请证书。
python3 scripts/configure.py
docker network create caddy-public
docker volume create mycaddy_data
docker volume create mycaddy_config
docker compose config --quiet
docker compose run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
```

已有网络或卷时使用 `docker network inspect` / `docker volume inspect` 核对，
无需重复创建。自定义名称时同步三个项目的 `CADDY_NETWORK` 与本项目卷变量。
分别按 MyCollab `deploy/README.md` 与 Clash `server/README.md` 启动业务，再运行：

```sh
docker compose up -d
docker compose logs --tail=100 caddy
```

TCP 80/443 必须从公网可达，UDP 443 用于 HTTP/3。只允许本入口发布这些端口。
默认使用 Let's Encrypt `shortlived` 配置，支持公网 IP 证书并自动续期；
确保 ACME 出站网络和验证端口持续可达。不要用 `tls internal` 替代公网信任证书。
配置说明：[Caddy](https://caddyserver.com/docs/caddyfile/directives/tls#issuers)、
[Let's Encrypt IP 证书](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability/)。

## 根据环境变量生成公网 IP 配置

脚本需要 Python 3.9 或更新版本。填写 `.env` 的 `PUBLIC_HOST`（真实公网 IPv4）及
网络、卷名称后运行，支持从任何工作目录调用：

```sh
python3 scripts/configure.py --dry-run
python3 scripts/configure.py
```

也可指定文件 `--env-file /path/server.env`；已导出的同名进程环境变量优先于文件。
脚本只解析普通 `KEY=value`、引号和注释，不执行 shell 命令，也不展开 `$VAR`。
生成结果：

- `conf/Caddyfile`：填入实际 IP 的站点与 `default_sni`，使用现有路由目录。
- `generated/mycaddy.env`：本次解析后的入口环境变量快照（含网络与证书卷名）。
- `generated/mycollab.env`：网络名、Django allowed hosts 与 HTTPS CSRF origin。
- `generated/clash.env`：订阅服务网络名。

将两个业务片段的同名变量合并到业务 `.env`，保留数据库密码、Django 密钥等原配置，
再分别执行业务 `docker compose up -d`。**不要用片段覆盖整个业务 `.env`。**
如需保留额外的 Django host/origin，合并时保留原列表中的有效地址。
脚本不修改其他仓库、不创建网络或卷、不申请证书、不启动服务。
`--output-dir /tmp/mycaddy-preview` 可将生成文件写入临时目录供检查；该目录仅含生成结果，
不包含 Compose 和路由文件，不能直接部署。

修改站点结构请编辑 `templates/Caddyfile.template`，自定义路径路由放在 `conf/routes/`。
重新生成不会改动路由文件；内容相同时不重写，内容改变时先保存带时间戳的 `.bak` 备份。
已有直接修改的 Caddyfile 应先将定制内容迁入模板，再运行生成脚本。
脚本针对公网 IPv4；域名部署仍可使用原先的环境变量模板手动配置。

生成后校验并应用（先按首次部署或迁移步骤准备网络与卷）：

```sh
docker compose --env-file generated/mycaddy.env config --quiet
docker compose --env-file generated/mycaddy.env run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose --env-file generated/mycaddy.env up -d
docker compose --env-file generated/mycaddy.env exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

`up -d` 应用环境变量变化；最后 reload 确保已运行容器加载新文件。
换 IP 后应同步业务环境并验证 HTTPS、登录与写入。脚本只校验地址格式和范围，
不能确认该 IP 属于当前服务器或公网端口已经可达。

## 从 MyCollab 的旧入口迁移

这一步在实际服务器执行，有短暂入口切换窗口；本仓库不会自动操作服务器。

1. 备份旧 `deploy/.env`、Caddyfile、数据库、素材与证书卷，记录当前镜像 ID。
   在更新旧配置前，用 `docker compose ps -q caddy` 得到容器 ID，
   再用 `docker inspect <容器ID> --format '{{json .Mounts}}'` 确认 `/data` 和 `/config`
   的真实卷名。常见名称为 `mycollab-prod_caddy_data`、`mycollab-prod_caddy_config`。
2. 在本项目 `.env` 中设置相同公网地址，并把 `CADDY_DATA_VOLUME`、
   `CADDY_CONFIG_VOLUME` 指向这些**现有卷**。用 `docker volume inspect <卷名>` 核对。
   外部卷缺失时 Compose 会报错，不会静默创建空证书卷。
3. 创建 `caddy-public` 网络，更新两个业务 checkout 与各自 `.env` 的网络名。
   在 MyCollab `deploy/` 执行 `docker compose up -d --build backend web`，
   在 Clash `server/` 执行 `docker compose up -d --build app`。
   此时先保留旧 Caddy 容器，**不要使用 `--remove-orphans`**。
4. 在 MyCaddy 执行上面的配置验证；将旧 Caddyfile 中其他自定义站点、路由迁入
   `conf/`，确认没有遗漏。记录旧容器 ID，然后执行 `docker stop <旧Caddy容器ID>`。
   立即在 MyCaddy 执行 `docker compose up -d`。两个 Caddy 不得同时写同一证书卷。
5. 按下节验收。失败时在 MyCaddy 执行 `docker compose stop caddy`，再
   `docker start <旧Caddy容器ID>` 恢复入口。若旧 Caddy 代理 Clash，回滚时还需
   `docker network connect --alias clash-subscription <旧网络名> <Clash容器ID>`，
   因为 Clash 已迁到新网络。成功后才移除停止的旧 Caddy 容器。

保留 MyCollab 的原项目名，避免意外创建空数据库卷。不运行 `down -v`，不删除旧证书卷。
网络与证书卷均为 external；停止任一 Compose 项目不会删除它们。

## 验收与维护

从另一台设备使用真实公网地址验证（不要使用 `curl -k`）：

```sh
curl -I https://<公网地址>/
curl -i https://<公网地址>/sub/invalid/config.yaml
```

订阅无效令牌应返回应用纯文本 404，不应返回 SPA HTML，也不会访问上游订阅。
验证登录、写入操作（CSRF）、`/api/`、`/admin/`、实际 `/static/` 文件及 SPA 深层路径刷新。
真实订阅仅在提供商授权服务器访问后验收。检查证书 SAN、颁发者、有效期及续期日志。

修改 `conf/` 后无需重建镜像：

```sh
docker compose exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
```

修改公网 IPv4 `.env` 后先重新运行 `python3 scripts/configure.py`。修改 `.env` 或镜像版本后执行 `docker compose up -d`，reload 不会更新容器环境。
整个配置目录挂载，避免单文件原子替换造成旧 inode。升级前先验证新版本。
默认不开访问日志，避免订阅令牌落盘；增加日志时必须过滤敏感路径。

新增同地址路径服务：在 `conf/routes/` 添加 `.caddy` 文件，用带匹配器的 `handle`
代理唯一网络别名；无匹配器的 MyCollab 回退仍放在主文件中。
新增独立域名：在 `conf/Caddyfile` 增加站点块。业务容器加入公共网络且不发布宿主机端口。
未启动的上游只影响对应路由（返回 502），不会阻止其他站点运行。

## 本地回归验证

已安装 Docker、Python 3 和 curl 时运行 `python3 tests/check_proxy.py`。
默认读取相邻 `../MyCollabAdvanced/deploy/Caddyfile`，可用 `MYCOLLAB_DEPLOY` 指定目录。
测试使用临时网络、模拟上游、回环地址随机端口和显式信任的本地 CA，不申请公网证书，
不读取业务密钥；结束后清理测试容器及网络。覆盖根路径、SPA 深层路径、静态文件、
API/Admin 的 HTTPS 转发头、订阅前缀和 404 分流。

生成器离线测试：`python3 tests/test_configure.py`，覆盖环境变量优先级、非法地址、幂等性与备份。

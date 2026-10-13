# 本地部署

源码安装与界面构建见 [README](../README.md)。默认服务地址为 `http://127.0.0.1:8787`，数据目录为 `~/.recallnest`。更换电脑或运行方式前，停止服务并备份整个数据目录。

## Docker Compose

在仓库目录运行：

```sh
docker compose up --build -d
```

打开 `http://127.0.0.1:8787`。Compose 只将端口发布到本机回环地址，数据保存在 `recallnest-data` 命名卷。镜像以普通用户运行，前端资源由构建阶段生成。

可以在界面中配置模型，也可以让 Compose 从环境变量或仓库根目录的本地 `.env` 读取 `.env.example` 所列的连接字段。`.env` 被 Git 与 Docker 构建上下文忽略。

未设置的连接字段继续使用数据卷中保存的界面配置。只取消注释你想交给环境管理的字段；显式设置的字段在启动时覆盖对应的已保存值，空字符串会清空它。更改 `.env` 后执行 `docker compose up -d --force-recreate`，让容器获得新环境。参见 [Compose 环境变量设置](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)。

容器中的 `127.0.0.1` 指向容器自身。Docker Desktop 上连接宿主机模型服务时，可使用 `http://host.docker.internal:11434/v1` 一类地址；供应商地址也可填写可达的远程接口。Linux 宿主机需确保模型服务可从容器的宿主机网关访问；Compose 已添加 `host-gateway` 映射。参见 [Docker Desktop 网络接入](https://docs.docker.com/desktop/features/networking/networking-how-tos/)和 [host-gateway 说明](https://docs.docker.com/reference/cli/docker/container/run)。

```sh
docker compose logs -f recallnest
docker compose stop
docker compose start
```

停止或重新构建服务不会删除命名卷。`docker compose down -v` 会删除卷及其中的数据，不是普通停止命令。

## 数据与备份

运行数据和模型连接配置属于同一个私有数据目录。完整 JSON 导出适合保留原文与派生历史；Markdown 导出适合阅读。首版尚无完整 JSON 恢复入口，恢复运行状态应使用停机后的整个数据目录备份。

SQLite 运行时可能包含数据库、WAL 和 SHM 文件。不要仅复制正在写入的主数据库文件并假定备份完整。命名卷的备份与恢复按你的 Docker 存储工具操作，备份期间保持服务停止。

## 运行范围

首版面向本地单用户，HTTP 层校验回环 Host/Origin。容器内部需要监听 `0.0.0.0`，Compose 的宿主机端口仍为 `127.0.0.1`。公开部署涉及账户、认证和网络边界，需要另行设计。

发布验证记录会区分源码运行、容器构建和容器运行的结果。

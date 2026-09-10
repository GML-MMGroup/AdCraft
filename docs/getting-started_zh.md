[English](getting-started.md)

# 从这里开始：运行 AdCraft

将 AdCraft clone 到本地，或者下载项目 ZIP 并解压后，按照下面四步操作即可。

## 1. 打开 AdCraft 文件夹

确认项目文件夹中有 `apps`、`docs`、`scripts` 和 `compose.yaml`。保留完整项目，不要只移动前端或后端文件夹。

## 2. 选择部署方式

AdCraft 可以使用 Docker，也可以不使用 Docker。两种方式都会启动同样的三个部分：Agent Runtime、API 和 Web。

### 交给桌面 Agent 部署

打开桌面 Agent，让它能够访问 AdCraft 文件夹，然后要求它按照下面其中一份文档执行，直到三个服务全部健康，并把网页地址告诉你：

- 使用 Docker：[Agent 运行手册：使用 Docker 部署 AdCraft](deployment-with-docker-agent_zh.md)
- 不使用 Docker：[Agent 运行手册：不使用 Docker 部署 AdCraft](deployment-without-docker-agent_zh.md)

例如，可以把下面这段话发给 Agent：

> 按照 `docs/deployment-with-docker-agent_zh.md` 部署这个 AdCraft 项目。持续执行到 Agent Runtime、API 和 Web 全部健康，然后把本机网页地址告诉我。只有需要管理员确认、输入密码、重启系统或修改桌面设置时才询问我。

如果希望直接在电脑上安装依赖，就把示例中的文档换成非 Docker Agent 文档。

### 自己动手部署

选择对应的用户教程，从头按照步骤操作：

- 使用 Docker：[使用 Docker 部署 AdCraft](deployment-with-docker_zh.md)
- 不使用 Docker：[不使用 Docker 部署 AdCraft](deployment-without-docker_zh.md)

Docker 会把项目依赖放在容器中；非 Docker 方式会直接在电脑上安装 Node.js、uv、FFmpeg 和项目依赖。

## 3. 安装可选的推荐资产库

打开 [AdCraft Releases 页面](https://github.com/GML-MMGroup/AdCraft/releases)，找到 `recommended-assets-v1.0.0`，下载：

- `adcraft-recommended-assets-v1.0.0.zip`
- `adcraft-recommended-assets-v1.0.0.zip.sha256`

然后按照[使用 AdCraft 推荐资产库](recommended-assets_zh.md)完成校验和解压。不需要再通过浏览器上传这些资产。

可以先部署 AdCraft，也可以先下载资产包，两者顺序没有影响。

## 4. 打开 AdCraft 并开始使用

部署完成后，打开终端中显示或 Agent 返回的本机网页地址。该地址通常以 `http://127.0.0.1:` 开头。

进入 **API Space**，填写所使用供应商要求的 API Key 并保存。如果已经安装资产包，再打开 **Recommended Assets**，等待资产库显示为就绪。

API Key 和 `.env` 文件都要保密，不要提交到 Git，也不要发送给其他人。

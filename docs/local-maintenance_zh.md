# 本地维护与恢复

AdCraft 使用现有的 SQLite 任务运行机制。单机使用不需要另行安装 Redis、消息队列或微服务。

## 更新之前

在 `apps/api` 目录下检查数据目录。原生部署默认使用 `../../runtime-data/api`；如果自定义了 `MEDIA_DATA_DIR`，请替换命令中的路径。

```sh
uv run python -m app.cli.local_maintenance check --data-dir ../../runtime-data/api --require-idle
```

命令会检查数据库完整性、版本、待处理任务和本地工具是否可用，不启动任务，也不访问模型供应商。若因为存在活动任务而返回非零退出码，请先等任务完成。报告中的记录数可能属于同一任务的不同阶段，不能相加当作任务总数。

任务完成后，使用现有部署停止命令关闭 API、Agent 和 Web。在服务停止期间创建备份：

```sh
uv run python -m app.cli.local_maintenance backup --data-dir ../../runtime-data/api
```

输出会给出数据库快照和校验清单的路径。数据库备份包含项目记录、模型默认配置和节点设置，**不包含图片、视频等媒体文件或环境变量中的密钥**。需要完整备份时，还应单独保存数据目录中的 `assets/`，并将 `.env` 和部署配置保存在私密位置。

随后通过现有部署脚本更新应用。启动时，如果需要升级数据库结构，程序会先在 `<MEDIA_DATA_DIR>/v2/migration-backups/database/` 中创建并验证快照。数据库已经是当前版本时，不会重复创建升级备份。

## 验证备份

```sh
uv run python -m app.cli.local_maintenance verify-backup \
  --database /path/to/adcraft.pre-upgrade-SNAPSHOT.sqlite3 \
  --manifest /path/to/adcraft.pre-upgrade-SNAPSHOT.manifest.json
```

这只检查 SHA-256 和 SQLite 完整性，不恢复数据、不启动生成，也不会重试付费请求。

## 升级失败后的恢复

1. 停止 API、Agent 和 Web，完整保留升级失败后的数据目录，便于排查。
2. 验证升级前的快照。查看清单中的 `source_revision`，准备对应的旧版应用。
3. 新建一个恢复数据目录，将验证后的数据库复制为 `v2/adcraft.sqlite3`，将保留的 `assets/` 复制到与 `v2/` 同级的位置，并保留匹配的环境配置。不要把失败数据库的 `-wal`、`-shm` 文件复制到快照旁边。
4. 将 `MEDIA_DATA_DIR` 指向恢复目录，通过受支持的启动器启动旧版应用。确认 `/api/v2/health` 正常，并检查已有项目和媒体可以打开，再创建新任务。

数据库恢复不会撤销供应商已经接受的请求。系统通过持久化任务标识恢复已有任务，请勿通过批量重新生成来恢复下载结果。快照创建后被删除的媒体，需要从独立的媒体备份中找回。

## 本机运行统计

API 空间中的“本机运行统计”按需加载最近 7 天内更新的执行记录，最多统计最新 5,000 条，超过时会明确提示。它显示结果数量、已观测到的成功任务耗时和错误代码统计。

这些数字代表本机的执行结果，不代表供应商计费次数或模型的整体可用性。没有观测到的耗时、没有来源的费用数据会保持未知。

## 配置与并发

安装级模型默认值、节点显式配置、已经接受的执行快照保持各自原有的作用范围。修改默认值不会改写节点的显式选择，也不会改写已经接受的执行。

以下配置共同限制使用同一数据库的所有项目：

- `V2_MAX_PARALLEL_IMAGE_JOBS`：图片生成并发数。
- `V2_MAX_PARALLEL_VIDEO_JOBS`：视频生成并发数。
- `V2_MAX_PARALLEL_AUDIO_JOBS`：音频生成并发数。
- `V2_MAX_PARALLEL_GENERATION_JOBS`：总生成并发数。

等待供应商返回的任务仍占用额度。额度用满时，新任务保留在队列中，由后续本地调度继续处理。

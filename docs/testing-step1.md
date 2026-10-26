# 第一步测试报告：fnOS 服务 + 网页端

测试日期：2026-10-26 / 测试对象：**1.0.3**（本地最新代码，独立实例 `127.0.0.1:8611`）+ **1.0.2**（fnOS 上已安装的 fpk，`192.168.5.100:8610`）

## 一、结论

| 段 | 内容 | 结果 |
| --- | --- | --- |
| A | 服务层（启停 / 健康检查 / 目录 / 局域网发现 / SPA 与缓存 / 日志 / 持久化 / 命名 / 无 ffmpeg 降级 / 并发） | **13 PASS + 2 手工 PASS** |
| B | API 层 40 项 | **40 PASS** |
| C | 网页 UI 38 项（puppeteer 真浏览器） | **38 PASS** |
| D | 三条端到端闭环 | **3 PASS** |
| 合计 | | **94 项全通过（0 FAIL）** |

测试过程中发现并修复 **5 个真 bug**（见第四节），另有 **3 个环境/安装问题需要你决定**（见第五节）。

## 二、测试环境

- 独立实例：`./.venv/bin/python -m videosorter --host 0.0.0.0 --port 8611 --data-dir /tmp/vs-qa/data --web-dir ../web/dist`（1.0.3，ffmpeg `/usr/bin/ffmpeg`）
- fnOS 实例：应用 `videosorter` 1.0.2，端口 8610，数据目录 `/vol1/@appdata/videosorter`
- 测试数据：4 个 ffmpeg 生成的样片（mp4 / 带音轨 mkv / 无音轨 avi / hevc mp4），写入隔离目录 `/tmp/vs-qa/src1`、`/tmp/vs-qa/data`
- 所有写操作可回滚：整理批次可用 `POST /api/organize/undo/{batch_id}` 撤销；测试前保存 `GET /api/videos?limit=1000` 快照

## 三、测试脚本（可复跑）

| 文件 | 覆盖 | 结果 |
| --- | --- | --- |
| `/tmp/vs-qa/api_test.py` | A/B 段 40 项：健康检查、鉴权、SPA 回退、源目录增删、扫描与增量、missing 标记与恢复、标签与目标目录优先级、直放 / HLS、Range 206、整理预览执行撤销、重命名删除封面历史、上传、错误码 | 40/40 PASS |
| `/tmp/vs-qa/ui_test.js` | C 段 38 项：登录页、播放页全部交互、标签、整理页签、管理页 7 视图、Esc 返回、主题三档、430px 窄屏、无 JS 报错、受保护请求无 401 | 38/38 PASS |
| `/tmp/vs-qa/api_test2.py` | A6–A10 + D1–D3：日志、重启持久化、特殊文件名、无 ffmpeg 降级、并发、三条闭环 | 8/8 PASS |
| `/tmp/vs-qa/run_seed.sh` | 重置数据 + 4 个样片 + 源目录 + 扫描（每条用例从干净状态开始） | — |
| `/tmp/vs-qa/run_ui.sh` | `run_seed.sh` + 直接跑 `ui_test.js` | — |

`pytest`（后端单测）：**26 passed**。

## 四、本轮修掉的 5 个真 bug

1. **文件从 missing 恢复不生效**（`server/videosorter/scanner.py`）：文件被标记 `missing` 后重新出现、但 size/mtime 未变时走「无需重新探测」早退分支，状态永远停在 `missing`。→ 该分支补 `UPDATE videos SET status='idle'`，计入 `updated` 并输出任务消息「恢复：xxx」。
2. **同标签视频不聚合**（`server/videosorter/organizer.py::resolve_tag_dir`）：优先级里「视频所在目录/标签名」高于「首个源目录/标签名」，导致同标签视频散落在各自子目录。→ 调整为「标签 dir_path → root_dir/标签名 → 首个启用源目录/标签名 → 视频所在目录/标签名」。
3. **root_dir 设置永远不生效**（`server/videosorter/api/sources_routes.py`）：新增源目录时把 `tags.dir_path` 硬写成 `<源目录>/<标签名>`。→ 删除该硬写逻辑，完全由 `resolve_tag_dir` 动态解析。
4. **空的标签选择会整理全部视频**（`server/videosorter/api/organize_routes.py`）：`tag_ids: []` 被当成「全部标签」。→ 显式空数组返回 `400 没有选中任何标签`。
5. **管理页按 Esc 不能返回播放页**（`web/src/views/Manage.vue`）：完全没有键盘监听（这是第二步需求里明确要求的功能）。→ 补 `onKeydown`（有弹层时不跳转）+ `onBeforeUnmount` 解绑。

## 五、需要你决定的问题

1. **fpk 无法用 CLI 覆盖安装（阻塞项）**：`app install-fpk <1.0.3.fpk>` 每次 `--dry-run` 都通过，但真实安装返回 `app-center request POST /app-center/v1/install/task failed: ({"code":10236,"data":null,"msg":""})`。已排除的变量：本地文件 / `--remote-path` 上传、`--volume-id 1`、`--data-volume-id 1`、`--no-start`、先 `app stop`。`skill/reference/app-center.md` 只文档化了 `20001`（存储卷不可用）与 `10500`（不支持启停），**没有 10236 的说明**。当前已把应用恢复为 running 1.0.2，**未卸载**。建议二选一：①我执行 `app uninstall videosorter --yes` 后再装 1.0.3；②你在 fnOS 应用中心里点升级/重装。
2. **已安装的 1.0.2 是旧构建**：`curl -sI http://192.168.5.100:8610/manage` 没有 `Cache-Control: no-store`（1.0.3 才加），所以升级前浏览器可能继续显示旧界面（强刷 `Ctrl/Cmd+Shift+R` 可绕过）。`.avi` 转码修复在该构建里已经生效。
3. **fnOS 实例的数据被重置了**：库里 `sources` 为空、视频只剩我上传的 2 个测试片（已在测试后删除）；此前记录的 5 个视频（`261.mp4`~`265.mp4`）记录不在库里，且在 `/vol1/@appdata/videosorter`、`/vol1/@appshare/videosorter`、`/vol1/1000`（4 层内）也没搜到对应文件。**我没有删除过这些记录或文件**，怀疑是重装 fpk 时数据目录被重建。请确认这些视频是否你自己删的/移走了；如果不是，需要进一步查（它们可能在别的存储卷上）。

## 六、手工验证项

- `fnos-cli app stop videosorter --yes` → `/api/health` 立即不可达（`000`）；`app start` → **1 秒内**恢复 200。
- 数据目录自动创建：`config.json`、`data.sqlite3`、`hls/`、`thumbs/` 结构正常。
- 局域网发现：`VS_DISCOVER` UDP 探测（38080）回包 `{"app":"VideoSorter","version":"1.0.2","name":"VideoSorter @ fnos","port":8610,"ip":"192.168.5.100","tls":false}`。

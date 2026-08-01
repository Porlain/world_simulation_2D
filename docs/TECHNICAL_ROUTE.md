# 技术路径（1.0 实现基线）

本文是当前代码的实现说明，不是概念草图。新开发者可以按“场景 → 引擎 → 存储 → 控制器 → API → 前端”的顺序运行和替换模块。

## 1. 验收目标

1. 选择一个合法场景后可以创建运行，初始状态固定为 tick 0。
2. 后端每秒推进一个 tick；速率 `0.5/1/2/4` 只改变推进间隔，不改变计算结果。
3. 每个 tick 写入一份快照，地点人数 + 在途人数保持守恒。
4. 浏览器可以启动、暂停、继续、结束，并在同一条时间轴上拖动到历史 tick。
5. 服务重启后，未正常结束的运行变为 `failed/process_interrupted`，历史快照仍可读。
6. 给定同一场景和 seed，重复运行 100 tick 的 JSON 结果完全相同。

## 2. 运行时拓扑

```text
scenarios/*.json
       │ ScenarioCatalog + Pydantic 校验
       ▼
  RunController ── asyncio scheduler ── engine.step()
       │                                  │
       │                                  └─ 纯计算 SnapshotState
       ▼
     Storage ── SQLite(WAL) ── runs / tick_snapshots
       │
       └─ FastAPI /api/*  ◄──► Vue App
                              ├─ Leaflet CRS.Simple 道路/地点
                              ├─ Canvas 流动粒子（仅视觉采样）
                              └─ 统一时间轴（实时跟随或历史 tick）
```

后端只保留一个活动运行。浏览器关闭不会停止运行；重新打开页面时从 `/api/runs` 和 `/api/runs/{id}` 恢复查看。

## 3. 场景契约

场景文件位于 `scenarios/<scenario_id>/scenario.json`，必须包含：

```json
{
  "schema_version": 1,
  "scenario_id": "demo-city",
  "name": "示例城",
  "scale": "city",
  "tick_seconds": 1,
  "coordinate_system": "local_xy",
  "axis_orientation": "x_right_y_up",
  "coordinate_unit": "scene_unit",
  "flow_types": [{"id": "citizen", "unit": "people", "label": "居民"}],
  "locations": [{
    "id": "market",
    "name": "集市",
    "position": [0, 0],
    "initial_counts": {"citizen": 1000}
  }],
  "connections": [{
    "id": "market-harbor",
    "from_location_id": "market",
    "to_location_id": "harbor",
    "path": [[0, 0], [10, 4]],
    "travel_time_ticks": 3,
    "capacity_per_tick": {"citizen": 40},
    "demand_per_tick": {"citizen": {"min": 4, "max": 12}}
  }]
}
```

实现约束：

- `id` 使用小写字母开头的 `a-z0-9_-`，场景 ID 全局唯一。
- `path` 至少两个坐标点；连接是有向的，需要反向流量时显式写另一条连接。
- `travel_time_ticks` 是离散 tick 数，不是前端动画时长。
- `capacity_per_tick` 和 `demand_per_tick` 必须为每个 `flow_types[].id` 提供值。
- 场景加载时计算 SHA-256；运行创建时把完整 JSON 和 checksum 一起写入 `runs`，以后场景文件变化不会改变旧回放。

新增场景只需要新增目录和 JSON，不需要改 Python 或 Vue 代码。目录中已有 `demo-city` 可作为最小模板。

## 4. 单 tick 算法

入口是 `backend/app/engine.py:step`，保持纯函数：

1. 深拷贝上一个 `SnapshotState`，tick 加一。
2. 对每条连接弹出最早到达的在途桶，并把到达人数加入目标地点。
3. 按连接 ID 稳定排序，为每个出发地点和流量类型生成需求。
4. 需求值由 `sha256(seed, tick, connection_id, flow_id)` 映射到配置区间，因此不依赖随机调用顺序。
5. 先按道路容量截断，再用最大余数法按比例分配地点当前可用人数。
6. 将实际出发人数放入对应连接的最后一个旅行桶，并记录 `departed/arrived`。
7. 重算 `totals`，校验 tick 连续、容量、非负和人口守恒。
8. 返回新状态；引擎不访问数据库、网络或浏览器。

这使得测试可以直接调用 `initial_state`、`step`，也使未来的世界层只需提供另一个符合场景契约的输入。

## 5. SQLite 持久化

`backend/app/storage.py` 只使用标准库 `sqlite3`：

| 表 | 关键字段 | 责任 |
| --- | --- | --- |
| `runs` | `id`, `scenario_bundle_json`, `seed`, `status`, `rate`, `current_tick` | 一次运行的身份、状态和场景快照 |
| `tick_snapshots` | `(run_id, tick)`, `state_json` | 可按运行和 tick 精确读取的状态 |

数据库启动时启用外键、WAL、5 秒 busy timeout。创建运行和 tick 提交都使用事务；`idx_runs_single_active` 部分唯一索引兜底限制活动运行数。

tick 提交的条件更新为 `status='running' AND current_tick=expected_tick`，因此重复提交或旧调度器不会覆盖新状态。应用启动时先执行 `recover_interrupted_runs()`，再启动调度器。

当前不使用 ORM、Redis 或消息队列。单进程、每秒一次写入的规模下，SQLite 文件就是最小可备份的数据边界；当出现多进程写入或明确的并发指标后，再迁移 PostgreSQL。

## 6. API 实现路线

### 创建运行

```http
POST /api/runs
Content-Type: application/json

{"scenario_id":"demo-city","seed":7}
```

响应包含 `run`、`scenario` 和 tick 0 的 `latest_snapshot`。不提供 seed 时由后端生成 53 位安全整数。

### 控制运行

```http
POST /api/runs/{run_id}/commands
{"action":"pause"}
```

`action` 为 `pause`、`resume`、`end`、`set_rate`；最后一种必须同时传 `{"rate":0.5|1|2|4}`。控制器在 `asyncio.Lock` 内检查状态，再在线程池中执行 SQLite/引擎工作，避免阻塞事件循环。

### 查询快照

`GET /api/runs/{id}?include_scenario=false` 返回当前最新快照和 tick 范围；`GET /api/runs/{id}/snapshots/{tick}` 返回指定 tick。前端拖动时间轴使用后一个接口，并做 80ms debounce 和 AbortController 取消旧请求。

错误统一为：

```json
{"error":{"code":"snapshot_not_found","message":"Snapshot not found.","details":{}}}
```

## 7. 前端状态与交互

`frontend/src/App.vue` 只有一套时间状态：

- `latestSnapshot`：后端最新状态。
- `displayedSnapshot`：地图当前显示状态。
- `followingLatest`：是否自动把前者复制给后者。
- `playbackPlaying`：结束运行后的逐 tick 读取开关。

运行中拖动时间轴会暂时离开最新位置，点击“返回最新”重新跟随；结束运行后同一条时间轴显示播放按钮，不新增“实时/回放模式”按钮。移动端仅把左右侧栏改成覆盖面板，地图和时间轴仍是同一套组件。

Leaflet 使用 `CRS.Simple` 绘制本地坐标。Canvas 粒子由快照中的 `transit_buckets` 按比例抽样，只负责视觉表达，不进入数据库，也不改变引擎结果。

## 8. 版本路线

### 1.0：当前交付

- 单机单活动运行、确定性城市流量、SQLite 快照。
- 场景 JSON 可替换，地图不绑定地铁语义。
- 统一时间轴实时查看/历史回放。
- 为世界、事件、独立身份保留稳定的场景和 API 边界，但不实现实体系统。

### 2.0：稀疏独立身份

将英雄、领袖、商队等少量重要对象作为独立轨迹记录，而不是把每个居民升级为实体。建议新增独立表：

```text
entities(id, run_id, kind, name, metadata_json)
entity_positions(entity_id, tick, location_id, connection_id, progress)
```

1.0 的 `SnapshotState` 保持不变；前端只有在选择身份图层时才请求 `/api/runs/{id}/entities`。轨迹写入频率可低于每 tick，避免把稀疏对象变成第二套人群模拟。

### 3.0：世界层、城镇钻取和可选事件提供者

世界层只负责索引和导航：

```text
world -> towns[] -> scenario_id -> existing RunController
```

点击世界地图中的城镇时切换到对应 `scenario_id`，运行 ID 和时间轴语义不变。事件提供者采用可选 HTTP 适配器，建议环境变量为 `EVENT_PROVIDER_BASE_URL`、`EVENT_PROVIDER_API_KEY`、`EVENT_PROVIDER_MODEL`；没有配置时使用本地规则，项目仍可离线运行。密钥不进场景 JSON、数据库或 Git。

## 9. 验证清单

提交前执行：

```bash
cd backend && uv run pytest
cd ../frontend && npm run typecheck && npm run build && npm run test:e2e
```

验收重点：固定 seed 的 100 tick JSON 相等；活动运行唯一；暂停期间 tick 不变；结束后快照可回放；3600 tick 在 60 秒和 100 MiB 数据预算内完成。

## 10. 有意不做的事情

1.0 不引入在线底图、WebSocket、认证、多用户协作、ORM、消息队列、完整世界生成或大模型 SDK。它们都有接口落点，但没有真实需求和容量证据前不实现；这样替换场景或升级到 2.0 时仍能沿用当前数据契约。

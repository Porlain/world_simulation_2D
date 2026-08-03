# 技术路径：从流量 Demo 到可生成城镇

> 当前状态：1.0 迁移已落地，当前主线包含可生成城镇、v2 流量快照和 deck.gl 图层
>
> 完整设计：[城镇生成、流量仿真与分层渲染架构](superpowers/specs/2026-08-02-town-rendering-engine-architecture-design.md)

本文只说明接下来如何实施。字段理由、失败语义、版本边界和外部项目评估以完整设计为准。

## 1. 当前代码与目标差异

当前 HEAD 已具备：

- FastAPI + Pydantic 的场景、run 和 command API。
- 固定步长确定性流量引擎。
- SQLite WAL、每 tick 快照和历史回放。
- Vue 地图优先工作台、左侧常驻菜单、统一时间轴和运行控制。
- deck.gl `OrthographicView` 的本地 XY 城镇、道路和流量图层。
- Watabou 风格纸张底图、城墙/城门/建筑印记、比例尺和指北针。

当前代码不是废弃原型。以下部分继续复用：状态机、HTTP 路径、事务边界、时间轴、seeded demand、最大余数分配和自动测试。只迁移限制下一阶段的边界：

| 当前实现 | 目标实现 |
| --- | --- |
| 手写 12 个地点、28 条连接 | seed + population 生成完整城镇场景包 |
| 地点圆点和道路折线 | 城墙、城门、街区、建筑、道路、地标 |
| Leaflet + 绝对定位 Canvas | 单一 deck.gl `OrthographicView` |
| 只有 citizen 圆点 | pedestrian 点、vehicle 方向图标 |
| 道路变色，没有真正热度层 | 地点 Heatmap + 道路发光热度带 |
| `SnapshotState` 同时承担引擎状态和 API 快照 | 私有 `SimulationState` + 公开 `FlowSnapshot` |
| scheduler 在全部依赖加载后启动 | `EngineHost` 先启动并 idle，必要依赖并发准备 |
| Python TOML/lock 在 `backend/` | `pyproject.toml` 和 `uv.lock` 移到仓库根目录 |

## 2. 最终运行拓扑

```text
应用启动
├── EngineHost.start() ───────────────► idle
├── SQLite initialize / recover ──────► ready
├── ScenarioCatalog.load_all() ───────► ready
└── FastAPI ──────────────────────────► readiness

生成或导入场景
seed + population / Watabou GeoJSON
                    │
                    ▼
             immutable TownSkeleton
              ├── FlowCompiler ──► SimulationPackage ─► EngineHost.activate
              ├── browser Render assembler ─► RenderPackage ─► deck.gl
              └── browser FeatureIndex ──────────────────────► selection

运行
RunInstance 顺序 tick
  └── private SimulationState
        └── public FlowSnapshot
              └── SQLite commit
                    └── HTTP polling / replay
```

引擎“提前启动”指 scheduler 已经存在并等待激活，不代表 tick 可以脱离前一个 tick 并行执行。`T+1` 始终依赖已提交的 `T`。

## 3. 场景契约

### 3.1 输入

场景生成接口接收：

```json
{
  "generation_seed": 8815907750467,
  "population": 11499,
  "name": "Alimontalle"
}
```

约束：

- `generation_seed`：`0..2^53-1`；省略时由后端生成并返回。
- `population`：`100..100000`。
- `name`：可选，1 到 64 字符。
- 几何 seed 与 run 的 `simulation_seed` 分开保存。
- `population` 只控制居民；载具初始总数由 `clamp(round(population / 80), 5, 1000)` 派生。

### 3.2 规范中间模型

```text
TownSkeleton
├── metadata: scenario_id, name, generation_seed, generator_version, population
├── boundary / bounds
├── districts[]
├── buildings[]: polygon + kind + district_id
├── junctions[]: normal | gate | plaza
├── streets[]: topology + path + width + kind
└── landmarks[]: kind + name + position
```

`TownSkeleton` 是生成器和 Watabou importer 的共同输出。其数组按稳定 ID 排序，canonical JSON 参与 checksum。

### 3.3 仿真与渲染分离

```text
SimulationPackage
├── flow_types
├── sparse locations
├── sparse directed connections
└── bindings: flow IDs -> geometry IDs

RenderPackage
├── boundary / walls
├── districts / buildings
├── streets / landmarks
└── bounds
```

数千条 street segments 只属于几何/拓扑层；流量引擎只保留城门、广场、区中心和地标形成的稀疏 FlowGraph。连接通过 `street_segment_ids` 与具体街道绑定。RenderPackage 是浏览器从 stored skeleton 派生的读模型，不写入 run bundle，因此渲染准备不会阻塞引擎激活。

### 3.4 草稿与 run

`POST /api/scenario-drafts` 在线程中生成完整 TownSkeleton 后立即返回 202：`draft_id + skeleton_checksum + town_skeleton + compile_status=compiling`。浏览器马上组装 RenderPackage；服务端后台 FlowCompiler 不阻塞画面。

前端每 250 ms 递归查询 `GET /api/scenario-drafts/{draft_id}`。ready 后取得 SimulationPackage 和最终 bundle checksum；failed 时显示编译错误。草稿只保存在进程内存中，最多保留 8 个，且不淘汰仍在 compiling 的 task；1.0 不新增场景表。

`POST /api/runs` 二选一接收：

```json
{"draft_id":"...","simulation_seed":7}
```

或兼容内置场景：

```json
{"scenario_id":"demo-city","simulation_seed":7}
```

创建 run 只接受 ready draft；compiling 返回 409，failed 返回 422。创建时把包含 source metadata、完整 TownSkeleton 和 SimulationPackage 的 `RunScenarioBundle` 写入 `runs.scenario_bundle_json`，所以服务重启和生成器升级不会破坏旧回放。renderer 缓存不入库。

## 4. `radial-v1` 生成路线

第一版使用稳定、易测试的环形扇区算法，不手写任意多边形布尔运算：

1. `target_buildings = clamp(ceil(population / 20), 40, 2000)`。
2. 使用 `ring_count=clamp(ceil(sqrt(target_buildings/8)),2,8)` 和 `sector_count=clamp(ceil(target_buildings/(ring_count*3)),8,32)`。
3. 使用 `town_radius_m=max(180,sqrt(target_buildings)*20)` 生成 16 点不规则边界，建立城墙和四个主城门。
4. 建立 8 米主路、6 米环路和 4 米扇区次级道路。
5. 相邻环与扇区形成四边形街区。
6. 使用双线性插值在街区内生成 1 到 8 个建筑 footprint，达到目标数量后停止。
7. 依据中心、城门和外圈距离分配行政、市场、宗教、军事、仓储、工坊、马厩和住宅。
8. 从城门、区中心、广场和地标构建最多 48 个节点的稀疏 FlowGraph。
9. 使用稳定 Dijkstra 计算路径，Kruskal 最小生成树保证连通，再为每个地点补两个最近邻形成环路。
10. 使用最大余数法分配居民，保证 pedestrian 初始总数严格等于输入人口；vehicle 单独守恒。

每个随机值由 `sha256(generator_version, seed, namespace, ordinal)` 派生，不读取全局 `random` 状态。

人流和车流共享 path，但分别计算旅行时间：步行按 1.4 m/s，载具按 4.0 m/s。容量由路径最窄街道宽度确定；公式和所有 clamp 上限以完整设计第 5、6 节为准。

Watabou GeoJSON 之后走同一 compiler；只增加 source normalizer，不复制 TownGeneratorOS GPL 代码。

## 5. 引擎和回放

### 5.1 内部状态

```text
SimulationState
  tick
  location_counts
  transit_queues
  connection_activity
  totals
```

内部队列不进入 API。迁移时先保持现有算法，再将 list 的 `pop(0)` 换成标准库 `deque` 或环形游标；不得同时改需求分配规则。

### 5.2 公开快照 v2

```json
{
  "schema_version": 2,
  "tick": 12,
  "location_counts": {
    "market": {"pedestrian": 900, "vehicle": 20}
  },
  "connections": {
    "market-north-gate": {
      "pedestrian": {"departed": 12, "arrived": 8, "in_transit": 42},
      "vehicle": {"departed": 2, "arrived": 1, "in_transit": 7}
    }
  },
  "totals": {"pedestrian": 11499, "vehicle": 120}
}
```

新快照不保存 `transit_buckets`。历史 v1 JSON 由后端读取适配器求和为 `in_transit`，API 始终向 Vue 返回 v2。旧场景的地点和连接由 `LegacyRenderAdapter` 转成最小 deck.gl 地标与道路，因此旧回放仍可读，但不会伪造原数据中不存在的建筑。

道路统计同时读取连接快照的 `in_transit`、`departed` 和 `arrived`：前者是当前道路存量，后两者是当前 tick 的出发/到达事件，不是累计值。生成场景必须通过 `street_segment_ids` 将共享同一物理街段的 FlowConnection 聚合到 TownStreet，不能直接拾取互相重叠的连接路径。道路视觉强度取存量占容量和当前 tick 吞吐占容量中的较大值，悬停提示分别展示三种口径。

每个 flow type 都检查：

```text
sum(location counts) + sum(connection in_transit) == total
```

### 5.3 提交屏障

```text
step internal state
  -> project public snapshot
  -> validate both
  -> INSERT snapshot + guarded UPDATE run in one transaction
  -> commit
  -> replace EngineHost memory state
  -> latest becomes visible
```

数据库失败时不得替换内存状态或发布新 tick。

## 6. deck.gl 图层

Vue 使用 standalone `Deck` 和一个 `OrthographicView`，所有图层使用本地 Cartesian `[x,y]`：

| 顺序 | 数据 | 图层 | 更新频率 |
| --- | --- | --- | --- |
| 1 | 街区底色 | PolygonLayer | 场景切换 |
| 2 | 边界、城墙 | PathLayer | 场景切换 |
| 3 | 道路底图 | PathLayer | 场景切换 |
| 4 | 人流/车流道路热度带 | PathLayer | snapshot |
| 5 | 建筑 footprint | PolygonLayer | 场景切换 |
| 6 | 地点人流热力 | HeatmapLayer | snapshot |
| 7 | 功能地标 | PolygonLayer + TextLayer | 场景切换/选择 |
| 8 | 人流采样 | ScatterplotLayer | snapshot tick |
| 9 | 车辆采样 | PolygonLayer | snapshot tick |
| 10 | 标签、选择 | Text/Polygon/Path | 选择变化 |

实现规则：

- 静态 geometry 数组在 tick 间保持同一引用。
- `HeatmapLayer` 使用固定颜色范围，图例不会随缩放改变含义。
- 道路热度复用 street path，不把车流扩散到建筑上。
- 动态 marker 最多约 1,000 个；每条 connection/type 按流量上限抽样 slot，并在前端按固定公式裁剪。
- marker 位置通过 path 累计弧长插值，和道路处于同一个 Deck 世界坐标。
- 首版不写 custom WebGL layer；只有 profile 证明 buffer 上传超预算后升级。
- WebGL 初始化失败时控制、统计和后端运行仍可用。

`CityMap.vue` 管理 Deck 生命周期，`townLayers.ts` 保存纯图层构造和路径采样。删除 Leaflet 依赖和 `@types/leaflet`，不保留双渲染路径。

## 7. EngineHost 生命周期

目标类是现有 `RunController` 的职责收敛，不增加代理层：

```text
EngineHost
├── scheduler_task
├── active_run
├── lock / wake_event
├── host status: booting|idle|running|stopping|stopped
└── run commands: activate|pause|resume|set_rate|end
```

FastAPI lifespan：

1. `EngineHost.start()` 立即创建 idle scheduler。
2. 并发执行 SQLite initialize/recover 和静态 catalog load。
3. 成功后 readiness 变为 true。
4. `activate()` 只等待合法 `SimulationPackage` 和 tick 0 提交。
5. 关闭时先停止 scheduler，再将未结束 run 标记为 failed。

`GET /api/health` 同时报告 host、storage 和 catalog readiness。当前 Python 3.10 使用 `asyncio.create_task`/`gather`，不为 `TaskGroup` 单独升级解释器。

## 8. 工具链迁移

目标根目录：

```text
world_simulation_2D/
├── pyproject.toml
├── uv.lock
├── backend/app
├── backend/tests
├── frontend
├── scenarios
└── docs
```

迁移完成后的固定命令：

```bash
uv sync --frozen
uv run pytest
uv run uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
cd frontend
npm ci
npm run typecheck
npm run build
npm run test:e2e
```

删除 `backend/pyproject.toml` 和 `backend/uv.lock` 只能发生在根目录三条 Python 命令均通过之后。

## 9. 小模块与提交边界

| 顺序 | 模块 | 最小验证 | 状态 |
| --- | --- | --- | --- |
| 0 | 文档基线 | 链接、占位符、矛盾和 diff 检查 | 已完成 |
| 1 | 根 pyproject/uv.lock | 当前后端测试全通过 | 已完成 |
| 2 | TownSkeleton + radial-v1 | 同 seed checksum、不同 seed、人口守恒 | 已完成 |
| 3 | FlowCompiler + draft API | 引用连续、API 202/status/422、bundle checksum | 已完成 |
| 4 | SimulationState/FlowSnapshot v2 | 100 tick 确定性、v1 adapter、公开守恒 | 已完成 |
| 5 | EngineHost | idle/readiness、激活、暂停、关闭测试 | 已完成 |
| 6 | 静态 deck.gl 城镇 | typecheck/build、桌面/移动 canvas 非空 | 已完成 |
| 7 | 热力和动态 marker | 分图例、缩放无漂移、reduced motion | 已完成 |
| 8 | 生成控件和时间轴整合 | Playwright 完整 run/replay 流程 | 已完成 |
| 9 | 容量与开源交付 | 2000 建筑 fixture、README、第三方声明 | 已完成 |
| 10 | 地图优先 UI | 左侧常驻菜单、纸张制图、功能建筑印记、图层开关、桌面/移动 E2E | 已完成 |

每一行单独提交并推送；检查失败时不进入下一行。不得把格式化、无关重构或生成产物混入模块提交。

## 10. 版本边界

### 10.1 1.0

完成单城镇生成、聚合人流/车流、热力、回放和可复现运行。运行时模型从第一天就兼容 importer 输出，但不创建空 importer 抽象。Watabou 风格当前通过 `radial-v1` 的可替换 skeleton 契约实现，后续导入器只需输出同一结构。

### 10.2 1.1

使用固定 Watabou GeoJSON fixture 实现 source normalizer，输出相同 `TownSkeleton` 并复用全部 1.0 模块。

### 10.3 2.0

英雄、领袖和商队使用少量独立 Actor 与轨迹；普通居民继续聚合。世界事件可来自本地规则、人工输入或 OpenAI-compatible HTTP provider，所有外部输出先经过 strict schema，回放不重新调用模型。

### 10.4 3.0

Azgaar 世界导入、世界级粗粒度 FlowGraph、城镇钻取和 Actor 跨场景移动。世界与城镇坐标独立，连续的是时间、人口、事件和身份，不承诺连续几何 LOD。

## 11. 完成判据

- 同一生成 seed、人口、规范化名称和生成器版本得到完全相同的场景 checksum。
- 指定人口与公开快照总量一致，所有 tick 守恒。
- 第一视口能识别城墙、道路网、建筑群和不同功能地标。
- 人流点、车辆图标、人流热力和车流热度具有独立图例与显隐。
- 缩放和平移时动态标记始终贴合道路，视觉偏移不超过 1 CSS px。
- EngineHost 在场景尚未生成时已经 idle；渲染失败不停止后端 tick。
- 运行控制、最近运行和统一时间轴行为不回归。
- 后端、类型检查、构建、桌面/移动 Playwright 和固定规模容量记录通过。
- 根目录包含 Python TOML/lock；Git 不包含数据库、密钥、构建产物或个人绝对路径。

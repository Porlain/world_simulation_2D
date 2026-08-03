# World Simulation 2D

一个可复现的城市流量模拟与回放工作台。1.0 使用“地点 + 有向街道”的通用网络模型，不把地铁、现代城市或经纬度写死；同一套引擎可以换成街道流量、商路流量或其他本地坐标场景。

当前版本已经完成：

- 确定性流量引擎：固定 `seed`、场景和 tick 后，结果逐拍一致。
- SQLite 单文件记录：运行元数据和每个 tick 的快照都可查询，重启会回收中断运行。
- FastAPI 控制 API：启动、暂停、继续、结束、速率调整和指定 tick 查询。
- Vue 3 + TypeScript 工作台：deck.gl 本地 XY 城镇渲染、道路热力、人流点、车辆标记和统一时间轴回看。
- 可复现城镇生成：输入 `generation_seed` 和居民数量，生成有城墙、街区、建筑和功能地标的 v2 场景；留空 seed 时由后端返回随机 seed。
- 桌面和移动端 Playwright 生命周期测试。

实现路线、数据契约、接口细节和 2.0/3.0 扩展边界见 [`docs/TECHNICAL_ROUTE.md`](docs/TECHNICAL_ROUTE.md)。

## 快速运行

需要 Python 3.10–3.13、Node.js 20+ 和 [uv](https://docs.astral.sh/uv/)。在项目根目录执行：

```bash
cd /share_data/songzun/classes/world_simulation_2D
uv sync --frozen
npm --prefix frontend ci
bash scripts/dev.sh
```

浏览器访问：

`http://10.97.128.2:5173/`

后端 OpenAPI 文档：

`http://10.97.128.2:8000/docs`

`scripts/dev.sh` 会启动一个后端和一个 Vite 前端，按 `Ctrl-C` 同时停止。默认数据库为 `data/flow.sqlite3`，可通过环境变量调整：

```bash
FLOW_DB_PATH=/absolute/path/flow.sqlite3 \
FLOW_SCENARIO_DIR=/absolute/path/scenarios \
bash scripts/dev.sh
```

停止所有属于本项目的开发服务（包括手动指定其他端口启动的实例）：

```bash
bash scripts/stop.sh --dry-run
bash scripts/stop.sh
```

生产静态文件由 FastAPI 托管：

```bash
npm --prefix frontend run build
FLOW_DB_PATH=data/flow.sqlite3 uv run uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
```

## 测试

```bash
uv run pytest
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

端到端测试使用隔离的 `18123`/`15174` 端口，后端测试数据库放在临时目录，不触碰开发中的 `8000`/`5173` 服务。容量验收测试会推进 demo 场景 3600 tick，并检查耗时和数据库体积：

```bash
uv run pytest backend/tests/test_capacity.py -q
```

## 目录

```text
pyproject.toml / uv.lock     根目录 Python 工具链与锁文件
backend/app/                 引擎、场景校验、SQLite、运行控制和 HTTP API
backend/tests/               后端单元/API/容量测试
scenarios/demo-city/         可提交到 Git 的场景 JSON
frontend/src/                Vue 工作台、deck.gl 城镇图层和生成/回放控制
frontend/e2e/                桌面/移动端生命周期测试
scripts/dev.sh               本地一键启动入口
docs/TECHNICAL_ROUTE.md      可直接照做的实现路径与扩展契约
```

## API 速查

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/scenarios` | 列出已校验场景 |
| `GET` | `/api/health` | 查看 EngineHost、SQLite 和场景目录 readiness |
| `POST` | `/api/scenario-drafts` | 异步生成城镇；body 为 `{"generation_seed":8815907750467,"population":11499}` |
| `GET` | `/api/scenario-drafts/{id}` | 查询 skeleton/FlowCompiler 状态，ready 时返回完整 bundle |
| `POST` | `/api/runs` | 创建运行；body 为 `{"scenario_id":"demo-city","simulation_seed":7}` 或 `{"draft_id":"...","simulation_seed":7}` |
| `GET` | `/api/runs?limit=20` | 历史运行 |
| `GET` | `/api/runs/{id}?include_scenario=true` | 运行状态和最新快照 |
| `POST` | `/api/runs/{id}/commands` | `pause`、`resume`、`end` 或 `set_rate` |
| `GET` | `/api/runs/{id}/snapshots/{tick}` | 精确读取某个 tick |

所有错误统一为 `{"error":{"code","message","details"}}`。同一时刻只允许一个 `running` 或 `paused` 运行。

## 版本边界

### 1.0（当前）

完成单城镇确定性生成、建筑/城墙/道路渲染、聚合人流与车流热力、数据库记录、实时查看和同一时间轴回放；保留世界、事件和独立人物的接口，但不提前实现英雄、领袖、商队或大模型调用。

### 2.0

增加少量独立身份及轨迹：英雄、领袖、商队等作为稀疏事件/轨迹记录抽取，不把它们膨胀成全量人群实体。新增身份不会改变 1.0 的地点和街道快照格式。

### 3.0

增加世界层和城镇钻取：世界场景提供城镇索引，点击城镇切换到同一运行 ID 下的小城市场景；事件提供者可选接入外部大模型 API，密钥只从环境变量读取，默认仍可离线运行。

不在当前版本引入认证、多用户协作、WebSocket、消息队列、ORM 或在线地图瓦片；这些只有在负载或产品需求证明必要时再增加。

## 开源

项目采用 MIT License，第三方依赖和字体说明见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

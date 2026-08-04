# Third-party notices

本项目没有把外部地图数据或游戏设定资源打包进仓库。运行时和开发时直接依赖的开源项目如下；各项目的完整许可证以其上游发布版本为准。

| 组件 | 用途 | 许可证 | 上游 |
| --- | --- | --- | --- |
| Vue 3 | 前端 UI | MIT | <https://github.com/vuejs/core> |
| deck.gl `@deck.gl/core`, `@deck.gl/layers` 9.3.7 | 本地 XY 城镇、道路、建筑、点标记和热力渲染 | MIT | <https://github.com/visgl/deck.gl> |
| Lucide | UI 图标 | ISC | <https://github.com/lucide-icons/lucide> |
| Noto Sans SC Variable | 中文字体 | SIL OFL 1.1 | <https://github.com/google/fonts> |
| FastAPI | HTTP API | MIT | <https://github.com/fastapi/fastapi> |
| Pydantic | 请求和场景校验 | MIT | <https://github.com/pydantic/pydantic> |
| Uvicorn | ASGI 服务 | BSD-3-Clause | <https://github.com/encode/uvicorn> |
| Vite / Vue plugin | 前端构建 | MIT | <https://github.com/vitejs/vite> |
| TypeScript / vue-tsc | 类型检查 | Apache-2.0 / MIT | <https://github.com/microsoft/TypeScript> |
| Playwright | 浏览器端到端测试 | Apache-2.0 | <https://github.com/microsoft/playwright> |

字体通过 `@fontsource-variable/noto-sans-sc` 重新分发。Noto Sans SC 的字形文件仍受 SIL Open Font License 1.1 约束；本项目未修改字形文件。

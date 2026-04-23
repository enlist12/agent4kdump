# Agent4Kdump Visual UI

## Backend

入口文件：`webapp/backend/app.py`

建议启动方式：

```bash
eval "$(micromamba shell hook --shell zsh)"
micromamba activate haha
uvicorn webapp.backend.app:app --app-dir /root/agent4kdump --reload
```

## Frontend

目录：`webapp/frontend`

建议启动方式：

```bash
cd webapp/frontend
npm install
npm run dev
```

## 设计说明

- `真实分析`：调用现有 Python 工作流，按阶段推送日志和结构化结果
- `案例回放`：读取经验库记录，回放展示根因分析过程
- `历史经验库`：浏览 `cache/rag/experience_store.jsonl` 与 Markdown 卡片
- `项目总览`：展示工作流、模块组成和目录树

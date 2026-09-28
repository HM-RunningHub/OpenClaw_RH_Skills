# workflows/

运行时目录：存放从 RunningHub 工作台「导出工作流 API」得到的原始 JSON。

- 命名：`<workflowId>.json`
- 用途：任务类型校验的真相来源（核对 nodeId / fieldName 是否存在），可很大。
- 本目录下所有 `.json` 被 .gitignore 忽略，属于私有文件；`.json.example` 模板不受影响。

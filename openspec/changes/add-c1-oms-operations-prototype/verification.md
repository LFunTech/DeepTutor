# OMS 抽屉详情与操作模态框原型验证记录

## 已覆盖

- OMS 的列表详情、对象深链、未知对象、关闭后筛选保留，以及额度详情返回租户详情，均由前端交互测试覆盖。
- 新增连接、服务配置、平台策略、服务授权、额度授予/调整和供给补充均使用独立表单模态框；表单通过 portal 脱离列表与详情布局。确认步骤暂时隐藏表单，取消后恢复原填写值；Escape 可关闭当前操作层，不误关详情抽屉。
- 平台管理员可保存服务/连接/资源策略草稿，运营可演示租户授权、额度和供给操作；审计员无写入入口。敏感操作经确认框，可取消；演示写入不请求网络，真实用量、审计与 EduPlus2 生命周期只读。
- 服务草稿使用 DeepTutor 现有解析引擎 ID 与条件字段；联网搜索独立于模型连接。草稿与发布申请不宣称运行态已生效。
- TMS 额度仍只读，共享服务组件分别通过 OMS/TMS 构建。生产 prototype 路由的代理策略返回 HTTP 404。

## 本次命令结果

- `extensions/enterprise/frontends`: `npm test` 38 项通过；`npm run lint`、`typecheck:oms`、`typecheck:tms`、`build:oms`、`build:tms` 通过。
- `tests/runtime/test_tms_oms_frontend_contract.py`: 3 项通过。
- 编译后的 `web/tests/proxy-policy.test.ts`: 15 项通过，含生产 prototype HTTP 404 断言。
- `openspec validate add-c1-oms-operations-prototype --strict` 与 `openspec validate --all --strict`: 通过，后者 26 项通过。

## 尚未验收

- 此轮再次尝试 `npm run dev:oms`，沙箱不允许 Next.js 在 `127.0.0.1:4310` 监听（`listen EPERM`），因此无法对模态框版本完成桌面/窄屏浏览器最终复核。此前版本有桌面服务详情与窄屏 Agent 抽屉截图检查，但不能替代最新版本的复核。任务 3.9 保持未完成。
- 本 change 仍是本地演示原型；真实管理 API、服务端权限、持久数据、发布执行、用量总账和企业入口禁用属于后续实施 proposal，不以此原型声称完成。
- 仓库现有完整 `web` Node 测试有 3 项与本原型无关的旧断言失败（EduPlus2 旧 localStorage/fetch 与 `/api/v1` 回调）；本次只将相关 proxy-policy 单测作为通过证据。

## 原型内部导航故障回归

- 用户报告 OMS 从列表打开详情时，Next.js 客户端 `router.push` 经 `navigateToUnknownRoute` 发起服务端请求并抛出 `Failed to fetch`。OMS/TMS 的原型详情均由同一 catch-all 页面内的本地状态呈现，不需要在每次点击时请求 RSC。
- 两端改为浏览器 History API 更新深链，保留抽屉和 `popstate` 返回行为；Next.js 16 App Router 自身会将非内部 `pushState` 纳入路由状态。未修改 DeepTutor 核心或正式管理路径。
- 新增 `tests/local-navigation.test.tsx`，先确认旧实现中 OMS/TMS 两例失败，再确认修复后两例通过；覆盖详情、URL、禁止 `router.push` 及 OMS 返回列表。
- 全量前端 `npm test`：8 文件、67 项通过；`typecheck:oms`、`typecheck:tms`、`lint`、`build:oms`、`build:tms` 均通过；两个原型 change 的 `openspec validate --strict` 均通过。
- 当前环境无法直接访问用户正在运行的 `127.0.0.1:4310` 页面，所以这次用户侧浏览器复测仍待完成；不据此宣称所有 OMS 问题均已消除。

## Skill ZIP-only 契约修订（待实现）

- 用户确认 OMS/TMS 的 Skill 创建与更新应提交完整 ZIP，所有 Skill 内容元数据均来自包内 `SKILL.md`。两个原型 change 及两个后续业务逻辑 change 的 proposal、design、delta spec、tasks 已按此修订；旧单文件/文本框路径明确标为不合规，相关原型任务重新列为未完成。
- `openspec validate --all --strict`：26 项通过；关联四个 change 的 Markdown 尾随空白检查为 0。
- 这轮仅更新规格，尚未修改 ZIP 解析器、OMS/TMS 界面或真实后端；用户审阅书面契约后才实施，不将现有前端测试结果视作新契约已通过。

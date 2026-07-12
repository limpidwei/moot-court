# moot-court 前端审计报告

- 审计范围: `frontend-next/`（Next.js App Router + TypeScript）
- 审计日期: 2026-06-26
- 审计方式: 逐文件精读 + 全仓 grep 交叉验证调用关系
- 精读文件: `app/trial/[caseId]/page.tsx`、`lib/api.ts`、`lib/auth.ts`、`app/page.tsx`、`app/case/new/page.tsx`、`app/evidence/[caseId]/page.tsx`、`components/{AuthGuard,PhaseContent,ChatBubble,ModelConfigPanel,FullReportExport,InsightCard,SkillCallPanel,UserMenu}.tsx`、`components/viz/VizExportButton.tsx`、`components/evidence/EvidenceUploader.tsx`、`app/auth/login/page.tsx`、`app/layout.tsx`

---

## 一、Critical / High 级别 Bug

### H1. 首页「可视化」按钮 404（已知 bug，确认）
- 文件:行号: `src/app/page.tsx:438`
- 严重度: High
- 类型: 未接线资源 / 路由缺失
- 问题描述: 首页展开案件后「📊 可视化」按钮 `router.push(`/viz/${c.case_id}`)`，但 `src/app/viz/[caseId]/` 目录存在却**为空**（无 `page.tsx`）。Next.js 路由段缺 page 文件 → 命中 404。后果：用户点击即跳转 404 页，且 `current_phase < 1` 才禁用，已开始的案件均可点。
- 证据:
  ```tsx
  // app/page.tsx:438
  onClick={() => router.push(`/viz/${c.case_id}`)}
  ```
  ```bash
  $ find src/app/viz -type f   # (空输出，目录存在但无文件)
  ```
- 修复建议: 补 `src/app/viz/[caseId]/page.tsx`（用现有 `components/viz/*` 组装页面），或在修复前禁用/隐藏该按钮。

### H2. `createCase` 不校验 `res.ok`，错误响应导致跳转到 `/trial/undefined`
- 文件:行号: `src/lib/api.ts:128-146`、`src/app/case/new/page.tsx:133-136`
- 严重度: High
- 类型: 空值/边界 + 错误处理缺失
- 问题描述: `createCase` 直接 `return res.json()`，对 4xx/5xx 不抛错。`case/new` 的 `handleSubmit` 仅 `try/catch` 网络异常，对 HTTP 错误响应无感知，直接读 `res.case_id`。后端返回错误 JSON（如 `{"detail":"..."}`）时 `case_id` 为 `undefined`，执行 `router.push('/trial/undefined?role=...')`，进入一个 caseId 为 `"undefined"` 的废庭审页（`getTrialState("undefined")` 静默失败 → 显示空白开始页 → 点开始后端 404）。用户看不到真实错误原因。
- 证据:
  ```ts
  // lib/api.ts:128
  export async function createCase(data: {...}) {
    const res = await fetch(`${API_BASE}/case/create`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      body: JSON.stringify(data),
    });
    return res.json();   // 不校验 res.ok
  }
  ```
  ```tsx
  // case/new/page.tsx:133
  const res = await createCase(payload);
  const caseId = res.case_id;          // 错误响应时为 undefined
  router.push(`/trial/${caseId}?role=${startRole}`);
  ```
- 系统性问题: `api.ts` 中**多数函数都不校验 `res.ok`**：`deleteCase`、`renameCase`、`createCase`、`getTrialState`、`getPhaseContent`、`exportReport`、`askJudge`、`getPhaseInsights`、`getTrialHistory`、`resetTrial`、`uploadEvidence`、`getEvidence`、`analyzeEvidence`、`importEvidenceToTrial`、`deleteEvidence`、`markNotificationRead`、`markAllNotificationsRead`、`deleteNotification`、`connectTrialStream`。仅有 `getCases`/`parseText`/`parseFile`/`selectStrategy`/用量与分享相关函数显式 `throw`。调用方（如 `evidence` 页 `handleImportToTrial` 读 `result.imported_count`）在错误时会显示「共导入 undefined 条证据」。
- 修复建议: 在 `api.ts` 统一封装「`!res.ok` → 解析 detail → throw」逻辑，所有函数走该封装；`case/new` 对 `res.case_id` 做空值守卫。

### H3. SSE 流无 AbortController，卸载/中断不取消，并发覆盖
- 文件:行号: `src/lib/api.ts:337-374`、`src/app/trial/[caseId]/page.tsx:167-335`（`handleStart`）、`338-498`（`handleConfirm`）
- 严重度: High
- 类型: 竞态 / 资源泄漏 / 卸载安全
- 问题描述: `connectTrialStream` 用裸 `fetch` + `reader.read()` 循环，**无 AbortController**。`handleStart`/`handleConfirm` 在卸载时不取消流：
  1. 用户离开庭审页（返回首页/关标签页）后，`reader` 仍在读，`onEvent` 继续对已卸载组件 `setState` → React「setState on unmounted component」告警 + 内存泄漏；
  2. 后端 LLM 仍在持续生成、烧 token，前端无法中断；
  3. `handleStart` 的「重试」按钮（`trial` 页 604）无 `disabled`，快速连点会启动多条并发 SSE，多路 `onEvent` 同时 `setState` → 流式正文相互覆盖、`phases` 错乱；
  4. `handleSelectStrategy` 选择策略后再次 `await handleStart()`（507），若上一次流未结束也会叠加。
  庭审页唯一的卸载清理是 `load` effect 的 `cancelled` 标志（163），仅保护 `getTrialState`，不覆盖流。
- 证据:
  ```ts
  // lib/api.ts:348
  const res = await fetch(`${API_BASE}/trial/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  // 无 signal / 无 AbortController；循环内 onEvent 直触外部 setState
  ```
  ```tsx
  // trial/[caseId]/page.tsx:163  仅 getTrialState 有清理
  return () => { cancelled = true; };
  // handleStart / handleConfirm 均 await connectTrialStream，无取消
  ```
- 修复建议: `connectTrialStream` 接收 `AbortSignal`，内部 `fetch(url, { signal })`；`TrialPage` 用 `useRef` 持有 controller，在 `handleStart`/`handleConfirm` 开始时 abort 旧流、卸载 effect 中 abort，并在按钮上加 `disabled={continuing}`。

### H4. SSE `token` 事件拼接 `undefined` 到流式正文
- 文件:行号: `src/app/trial/[caseId]/page.tsx:221-243`、`392-413`
- 严重度: High
- 类型: 空值/边界
- 问题描述: token 事件回调里 `const next = prev + event.content;`。`TrialStreamEvent.content` 类型为 `string | undefined`（`api.ts:328`）。一旦后端发出缺 `content` 字段（或字段名为 `text`/`delta` 等不一致）的 token 事件，`prev + undefined` 会把字符串 `"undefined"` 字面量拼进庭审正文，且会同步写入 `phases[].content` 持久预览。
- 证据:
  ```tsx
  // trial/[caseId]/page.tsx:221
  setStreamingContent((prev) => {
    const next = prev + event.content;   // event.content 可能 undefined
    ...
    setPhases((prevPhases) => { ... arr[idx] = { ...arr[idx], content: next }; ... });
    return next;
  });
  ```
- 修复建议: 改 `const next = prev + (event.content ?? "");`，并对 `event.phase`/`speaker` 等可选字段同样防空（`agent_step` 分支已用 `event.speaker!` 非空断言，缺字段时存入 `undefined`）。

---

## 二、Medium 级别 Bug

### M1. 在 `setStreamingContent` 的 updater 内部嵌套 `setPhases`（副作用入 reducer）
- 文件:行号: `src/app/trial/[caseId]/page.tsx:221-243`、`392-413`
- 严重度: Medium
- 类型: 状态/竞态
- 问题描述: 在 `setStreamingContent((prev) => {...})` 的 updater 函数体内调用了 `setPhases(...)`。React 要求 updater 纯函数；StrictMode（dev）会**双调用** updater 以检测副作用，导致 `setPhases` 在单次 token 事件中被触发两次，并可能引发「Cannot update a component while rendering a different component」告警。`arr.push`（新阶段）分支在双调用下也易错乱。
- 证据: 见 H4 代码片段，`setPhases` 直接写在 `setStreamingContent` updater 内。
- 修复建议: 把 `prev` 改成从闭包外读 `streamingContent`（或用 `useRef` 缓存），在 token 回调里**并列**调用 `setStreamingContent` 与 `setPhases`，不要嵌套进 updater。

### M2. ModelConfigPanel「API Key 不上传服务器」文案与实际不符；明文存 localStorage
- 文件:行号: `src/components/ModelConfigPanel.tsx:150`、`73-76`；`src/app/case/new/page.tsx:130-132`；`src/lib/api.ts:128-146`
- 严重度: Medium
- 类型: 鉴权/安全误导
- 问题描述: UI 文案「API Key 仅保存在浏览器本地，**不会上传到服务器持久化存储**」，但 `ModelConfigPanel` 通过 `onChange` 把含 `api_key` 的 `llmConfig` 传给 `case/new`，`handleSubmit` 在 `payload.llm_config = llmConfig`（131）后随 `createCase` POST 到后端。即 key **确实被上传**（是否持久化是后端问题，但「不上传」已属虚假陈述）。同时 `api_key` 明文 `JSON.stringify` 存 `localStorage`（73-76），任何 XSS 可窃取。
- 证据:
  ```tsx
  // ModelConfigPanel.tsx:150
  API Key 仅保存在浏览器本地，不会上传到服务器持久化存储。
  ```
  ```tsx
  // case/new/page.tsx:130
  if (llmConfig) { payload.llm_config = llmConfig; }   // 含 api_key
  const res = await createCase(payload);               // POST 到后端
  ```
- 修复建议: 更正文案为「API Key 将随本次创建请求发送至后端用于本次调用」；后端确认是否落库并加密；前端考虑 sessionStorage 或服务端代理而非 localStorage 明文。

### M3. SSE 解析对末尾残留/decoder flush/`data:` 无空格变体处理不足
- 文件:行号: `src/lib/api.ts:356-373`
- 严重度: Medium
- 类型: SSE 解析 robust
- 问题描述:
  1. 循环结束时 `buffer` 残留的最后一条（不以 `\n` 结尾的）事件**永不处理**，可能丢失末尾 `done` 事件；
  2. `TextDecoder` 全程 `{ stream: true }`，结束后**从未以空参 `decoder.decode()` flush**，跨 chunk 末尾的半个多字节字符会滞留；
  3. 仅匹配 `line.startsWith("data: ")`（带空格），SSE 规范允许 `data:`（无空格）或 `data:` 后直接跟内容，此类行被静默丢弃；
  4. 无 `[DONE]` 哨兵与连接断开的显式处理（虽被 `try/catch` 吞，但断网时 `reader.read()` 抛错会直接冒泡到 `handleStart` 的 catch 显示「启动庭审失败」，体验差）。
- 证据:
  ```ts
  // lib/api.ts:361
  const lines = buffer.split("\n");
  buffer = lines.pop() || "";          // 残留留到下次，但循环结束不再处理
  for (const line of lines) {
    if (line.startsWith("data: ")) {   // 仅匹配带空格
      try { const event = JSON.parse(line.slice(6)); onEvent(event); }
      catch { /* ignore */ }
    }
  }
  ```
- 修复建议: 循环结束后 `buffer` 若非空再尝试解析一次；`decoder.decode()` 空参 flush；用 `line.startsWith("data:")` 后 `slice(5).replace(/^ /, "")` 兼容无空格；`reader.read()` 抛错时识别 `AbortError`/网络错误并优雅收尾。

### M4. 多数 API 函数未触发 401 → logout
- 文件:行号: `src/lib/api.ts`（`handleUnauthorized` 12-17 仅被部分函数调用）
- 严重度: Medium
- 类型: token/鉴权
- 问题描述: `handleUnauthorized(res)` 只在 `getCases`、`getUsageSummary`、`getUsageRecords`、`createShare`、`listShares`、`deleteShare`、`getNotifications` 中调用。而 `createCase`、`getTrialState`、`getPhaseContent`、`exportReport`、`askJudge`、`getPhaseInsights`、`getTrialHistory`、`resetTrial`、`selectStrategy`（虽 throw 但不 logout）、`connectTrialStream`、证据上传/分析/导入/删除等**核心庭审 API 均不处理 401**。token 过期后用户在庭审页操作只会收到「提交失败/庭审流式输出出错」，不会被引导重新登录。`fetchWithTimeout` 内部调了 `handleUnauthorized`，故 `startTrial`/`continueTrial`/`analyzeEvidence` 间接生效——但这两个 SSE 替代函数已是孤儿（见 L2）。
  另：`logout()` 用 `window.location.href = "/auth/login"` 硬跳转，若多个请求并发 401，会触发多次硬跳转（非无限循环，但浪费）。
- 证据: 见 `api.ts` 各函数，多数仅 `return res.json()` 无 `handleUnauthorized(res)`。
- 修复建议: 在 `fetchWithTimeout` 与所有裸 `fetch` 调用处统一加 `handleUnauthorized(res)`，或用统一请求包装器。

### M5. `useSearchParams()` 未被 Suspense 包裹
- 文件:行号: `src/app/trial/[caseId]/page.tsx:68`
- 严重度: Medium
- 类型: Next.js App Router 兼容性
- 问题描述: App Router 中 `useSearchParams()` 在客户端组件里使用时，若上层无 `<Suspense>` 边界，Next.js 构建静态渲染时会报 `useSearchParams() should be wrapped in a suspense boundary` 并使整页 deopt 为客户端渲染（或构建失败）。该页是 `"use client"` 整页，未包 Suspense。
- 证据: `const searchParams = useSearchParams();`（68），整页无 Suspense 包裹。
- 修复建议: 将使用 `useSearchParams` 的内容抽到子组件并用 `<Suspense>` 包裹，或在该路由加 `export const dynamic = "force-dynamic"`。

### M6. `handleStart` callback 依赖 `streamingPhase` 导致闭包过期；`handleConfirm` 非记忆化
- 文件:行号: `src/app/trial/[caseId]/page.tsx:335`、`338`
- 严重度: Medium
- 类型: 状态/闭包过期
- 问题描述: `handleStart` 是 `useCallback([caseId, userRole, streamingPhase])`。流式期间 `setStreamingPhase` 不断更新，渲染生成新 `handleStart`，但**已发出的** `connectTrialStream` 的 `onEvent` 闭包仍捕获发起时的旧 `streamingPhase`。token 分支 `const sp = event.phase || streamingPhase;`（224、394）在 `event.phase` 缺失时回退到过期值。`handleConfirm` 更是普通函数（非 useCallback），每帧重建，闭包同样取数瞬间的 `streamingPhase`。
- 证据: `const sp = event.phase || streamingPhase;`（224），`streamingPhase` 取自过期渲染。
- 修复建议: `streamingPhase` 用 `useRef` 镜像并在 ref 上读，callback 依赖列表去掉 `streamingPhase`；或 token 分支强制只用 `event.phase`。

### M7. FullReportExport 卸载后 setState；fetch 无超时无 abort
- 文件:行号: `src/components/viz/FullReportExport.tsx:67-77`、`36-38`
- 严重度: Medium
- 类型: 卸载安全 / 无超时
- 问题描述: `handleExport` 的 `setTimeout(() => { setProgress(""); setExporting(false); }, 1500/3000)` 在组件卸载后仍会触发 `setState`（报「unmounted」告警）。且 PDF 生成 `fetch`（36，后端 reportlab+matplotlib 可能很慢）无超时、无 AbortController，用户离开页面后下载仍占连接。
- 证据: `setTimeout` 内 `setProgress`/`setExporting`（67-70、74-77），无清理。
- 修复建议: 用 `useRef` 跟踪 mounted，或 useEffect 管理 timer 在卸载时 `clearTimeout`；fetch 加 `AbortController` 与超时。

### M8. AuthGuard 重定向前已渲染 children；登录页也显示全局 header
- 文件:行号: `src/components/AuthGuard.tsx:15-24`、`src/app/layout.tsx:19-33`
- 严重度: Medium
- 类型: 鉴权/UX
- 问题描述: `AuthGuard` 在 `useEffect` 里判断未认证后 `router.push("/auth/login")`，但组件**无条件 `return <>{children}</>`**。未认证访问受保护页时，children 会先渲染一帧（触发该页的 API 调用、显示受保护内容）再跳转。且 `layout.tsx` 把全局 header+UserMenu 放在 `AuthGuard` 内，导致登录页/注册页顶部也显示「⚖️ 模拟法庭 + 用户菜单」头部（UserMenu 在未登录时返回 null，但 header 条仍显示）。
- 证据: `return <>{children}</>`（24）在 effect 之外。
- 修复建议: 未认证时 `return null`（或 loading 骨架），不渲染 children；header 移到受保护布局内，或 AuthGuard 内对 public 路径跳过 header。

---

## 三、Low 级别 Bug

### L1. `API_BASE` 重复定义 4 处，易发散
- 文件:行号: `src/lib/api.ts:5`、`src/app/auth/login/page.tsx:8`、`src/app/auth/register/page.tsx:8`、`src/components/viz/FullReportExport.tsx:9`
- 严重度: Low
- 类型: 重复定义
- 问题描述: 4 处各自 `const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";`。任一处改默认/加逻辑（如 trailing slash 处理）会与其他不一致。
- 修复建议: 抽到 `lib/api.ts` 导出 `API_BASE`，其他文件 import。

### L2. 大量孤儿代码（未接线的组件/函数）
- 文件:行号: 见下
- 严重度: Low
- 类型: 未接线资源 / 死代码
- 问题描述: 经全仓 grep 交叉验证，以下均无任何调用方：
  - `api.ts`: `exportReport`（218）、`getPhaseContent`（211）、`startTrial`（178）、`continueTrial`（187）——庭审已改用 `connectTrialStream`，这四个旧同步函数被废弃但保留；`listShares`（444）、`deleteShare`（453）、`deleteNotification`（502）。
  - 组件: `InsightCard.tsx`（514 行，全仓无 import）、`VizExportButton.tsx` 及整套 `components/viz/*`（AttackDefenseMap/CaseTimeline/ClaimBasisTree/DebateFlowGraph/DisputeFocusMap/EvidenceChain/LegalRelationGraph/PositionComparison/VerdictTree/WinRateRadar）——因 `/viz` 页不存在（H1），全部成了死代码。
  - `trial/[caseId]/page.tsx`: `import ReactMarkdown`/`remarkGfm`（22-23）在本文件内从未使用（markdown 渲染在 `PhaseContent`/`ChatBubble` 内）；`insightsVersion` state（88）只写不读（302/305/467/470 递增，但值从不被消费、也不传给任何组件，`insights_ready` 事件实际无效——因消费方 `InsightCard` 未被接入）；`highlightedPhase`/`setHighlightedPhase`（107）声明后 `setHighlightedPhase` **从不被调用**，`highlightedPhase` 恒为 0，导致 `highlighted={highlightedPhase === p.phase}`（711、898）恒 false，阶段高亮功能永不触发。
- 修复建议: 接入 `/viz` 页与 `InsightCard`（并把 `insightsVersion` 作为其 `refreshTrigger` 传入），或删除死代码；用 `setHighlightedPhase` 在 token 到达新阶段时触发高亮。

### L3. 文件 input 重复上传同名文件不触发 onChange
- 文件:行号: `src/app/case/new/page.tsx:72-99`、`src/components/evidence/EvidenceUploader.tsx:52-55`
- 严重度: Low
- 类型: 边界
- 问题描述: `<input type="file">` 选完文件后未重置 `e.target.value`。若用户取消再选同一文件，value 未变，`onChange` 不触发，无法重新上传。`case/new` 单文件场景尤甚。
- 修复建议: 回调末尾 `e.target.value = ""`。

### L4. `react-markdown` 未显式禁用 HTML / sanitize（当前依赖默认行为）
- 文件:行号: `src/components/PhaseContent.tsx:6-7`、`src/components/ChatBubble.tsx:5-6`
- 严重度: Low
- 类型: XSS 防御
- 问题描述: 两处 `<ReactMarkdown remarkPlugins={[remarkGfm]}>` 未加 `rehypeRaw`（故默认不渲染原始 HTML，当前安全），也未显式 `rehypeSanitize`。安全性完全依赖默认「不解析 HTML 标签」行为，一旦后续有人误加 `rehype-raw` 即引入 XSS（后端生成的 markdown 含用户输入的案情/证据）。`PhaseContent` 还对 phase 7 的 `plaintiff_final`/`defendant_final` 原文渲染。
- 修复建议: 显式引入 `rehype-sanitize` 加固，避免未来回归。

### L5. 单方对抗模式 role 初始短暂错位
- 文件:行号: `src/app/case/new/page.tsx:135`、`src/app/trial/[caseId]/page.tsx:71-73`
- 严重度: Low
- 类型: 边界/状态一致性
- 问题描述: `case/new:135` `startRole = mode === "asymmetric" ? userSide : "neutral"`，asymmetric 下若 `userSide` 为空（提交按钮 disabled 阻止了，但 URL 手敲可达）会拼出空 role。`trial` 页 `userRole` 初值取自 `searchParams.get("role")`，asymmetric 案件若直接访问 `/trial/{id}` 无 role 参数，首帧 `userRole="neutral"`，显示「中立观察」，直到 `getTrialState` 返回后（114-124）才覆盖为真实角色——首屏短暂错位。
- 修复建议: asymmetric 案件首屏以 loading 占位，待 `getTrialState` 回来再渲染模式信息。

### L6. 移动端 / 可访问性
- 文件:行号: 多处
- 严重度: Low
- 类型: a11y / 移动端
- 问题描述:
  - `page.tsx` 通知下拉（209-241）、`trial` 页历史弹窗（927-971）无 ESC 关闭、无 focus trap、无 `role="dialog"`；
  - 通知铃铛按钮（200）仅含 emoji「🔔」，无 `aria-label`；分页「上一页/下一页」按钮无 `aria-label`；
  - 全站删除/回退用原生 `confirm`/`alert`（阻断、不可样式化、移动端体验差）；
  - `trial` 页 `FullReportExport` 的进度提示用 `fixed top-4 right-4`（97）在小屏可能与 header 重叠；
  - `ModelConfigPanel`「显示/隐藏」API Key 按钮、`EvidenceUploader` 拖拽区均缺 `aria-label`。
- 修复建议: 补 `aria-label`、加 ESC/focus-trap、将 confirm/alert 换成站内 Modal。

### L7. `login` 页 `/health` 探测无 abort、无重试节流
- 文件:行号: `src/app/auth/login/page.tsx:26-41`
- 严重度: Low
- 类型: 资源/竞态
- 问题描述: mount 时 `fetch(/health)` 无 AbortController，离开登录页后仍会完成并 `setBackendStatus`（已卸载组件 setState 告警）。StrictMode dev 下 effect 双调用会发两次探测。
- 修复建议: 加 AbortController，StrictMode 下用 `useRef` 防重。

---

## 四、无问题文件说明
- `src/components/ChatBubble.tsx`：纯展示组件，逻辑无 bug（XSS 见 L4 共性）。
- `src/components/SkillCallPanel.tsx`：纯展示，`calls.length===0` 提前 return，无问题。
- `src/lib/auth.ts`：`isAuthenticated` 的 `atob(token.split(".")[1])` 对格式异常 token 已 `try/catch` 返回 false；`localStorage` 访问均守卫 `typeof window`；token 无 exp 时 `exp*1000=NaN`，`Date.now()<NaN=false` 视为过期，行为合理。无 critical bug（`atob` 解析 JWT 是客户端校验，仅作 UX 提示，最终以服务端 401 为准，可接受）。

---

## 五、前端 Bug 汇总表（按严重度排序）

| # | 严重度 | 类型 | 文件:行号 | 一句话描述 |
|---|--------|------|-----------|-----------|
| H1 | High | 路由缺失 | `app/page.tsx:438` | 「可视化」按钮指向 `/viz/[caseId]`，该路由无 `page.tsx` → 404 |
| H2 | High | 错误处理/空值 | `lib/api.ts:128`；`case/new/page.tsx:133` | `createCase` 不校验 `res.ok`，错误响应 → 跳 `/trial/undefined`；多数 API 同病 |
| H3 | High | 竞态/泄漏 | `lib/api.ts:337`；`trial/[caseId]/page.tsx:167,338` | SSE 无 AbortController，卸载/中断不取消，并发流覆盖 + 卸载 setState |
| H4 | High | 空值/边界 | `trial/[caseId]/page.tsx:221,392` | token 事件 `prev + event.content`，content 缺失时拼入字面量 `"undefined"` |
| M1 | Medium | 状态/竞态 | `trial/[caseId]/page.tsx:221-243,392-413` | `setPhases` 嵌套在 `setStreamingContent` updater 内，副作用入 reducer |
| M2 | Medium | 鉴权/安全误导 | `ModelConfigPanel.tsx:150`；`case/new/page.tsx:131` | 「API Key 不上传服务器」文案不实，key 随 createCase 发后端且明文存 localStorage |
| M3 | Medium | SSE 解析 | `lib/api.ts:356-373` | 末尾残留/decoder flush/`data:` 无空格变体处理不足，可能丢事件 |
| M4 | Medium | 鉴权 | `lib/api.ts`（多处） | 多数核心 API 不调 `handleUnauthorized`，401 不跳登录 |
| M5 | Medium | App Router | `trial/[caseId]/page.tsx:68` | `useSearchParams()` 未包 Suspense，构建告警/CSR deopt |
| M6 | Medium | 闭包过期 | `trial/[caseId]/page.tsx:335,338` | `streamingPhase` 进 callback 依赖致 onEvent 闭包取过期值 |
| M7 | Medium | 卸载安全 | `FullReportExport.tsx:67-77,36` | setTimeout 卸载后 setState；PDF fetch 无超时无 abort |
| M8 | Medium | 鉴权/UX | `AuthGuard.tsx:15-24`；`layout.tsx:19-33` | 重定向前已渲染 children；登录页也显示全局 header |
| L1 | Low | 重复定义 | `api.ts:5`/`login:8`/`register:8`/`FullReportExport:9` | `API_BASE` 4 处重复定义 |
| L2 | Low | 死代码/未接线 | 多处 | InsightCard 514 行、整套 viz 组件、api 7 函数、trial 页 ReactMarkdown/insightsVersion/highlightedPhase 均无消费方 |
| L3 | Low | 边界 | `case/new/page.tsx:72`；`EvidenceUploader.tsx:52` | file input 未重置 value，重选同名文件不触发 |
| L4 | Low | XSS 防御 | `PhaseContent.tsx:6`；`ChatBubble.tsx:5` | react-markdown 未显式 sanitize，依赖默认不渲染 HTML |
| L5 | Low | 状态一致性 | `case/new/page.tsx:135`；`trial/[caseId]/page.tsx:71` | asymmetric 模式 role 首屏短暂错位 |
| L6 | Low | a11y/移动端 | 多处 | 弹窗无 ESC/focus-trap、按钮无 aria-label、用原生 confirm/alert |
| L7 | Low | 资源 | `auth/login/page.tsx:26` | /health 探测无 abort，StrictMode 双调用 |

---

## 六、建议优先修复顺序
1. **H1** 补 `/viz/[caseId]/page.tsx`（或临时隐藏按钮）——用户可见的 404。
2. **H3 + H4** 给 `connectTrialStream` 加 AbortController 并修 `event.content ?? ""`——庭审核心链路的数据正确性与资源安全。
3. **H2 + M4** 统一 `api.ts` 的 `res.ok` 校验与 401 处理——消除系统性静默失败。
4. **M2** 修正 ModelConfigPanel 安全文案——合规与用户信任。
5. **M1 / M6** 拆除嵌套 setState、用 ref 镜像 streamingPhase——稳定性。
6. 其余 Medium/Low 按迭代清账。

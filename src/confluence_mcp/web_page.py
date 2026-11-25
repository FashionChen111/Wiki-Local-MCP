"""The single HTML page served by confluence-mcp-review web.

Operation text, titles and links come from agents or Confluence, so they are only ever
written with textContent (or as validated http(s) hrefs). The body preview is an isolated,
sandboxed frame that the server renders from /api/render, so no untrusted HTML enters this
document.
"""

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Confluence 写入审批</title>
<style>
  :root {
    color-scheme: light;
    --bg: #f5f7fa; --surface: #fff; --text: #18263e; --muted: #627086;
    --line: #dfe5ee; --accent: #2959d5; --accent-soft: #edf3ff; --accent-line: #bbcef8;
    --bad: #b23d40; --bad-soft: #fff0f0; --ok: #207548; --ok-soft: #edf8f1;
    --warn: #94600d; --warn-soft: #fff6e5;
  }
  * { box-sizing: border-box; }
  body { margin: 0; height: 100vh; height: 100svh; overflow: hidden; display: flex; flex-direction: column; background: var(--bg); color: var(--text); font: 14px/1.6 system-ui, "Microsoft YaHei", "PingFang SC", sans-serif; }
  h1, h2, p { margin: 0; }
  button, input, select { font: inherit; }
  button, select, summary, input[type="checkbox"] { cursor: pointer; }
  button, input, select { min-height: 44px; }
  button, .button { border: 1px solid var(--line); border-radius: 7px; padding: 0 13px; background: var(--surface); color: var(--text); transition: background .15s, border-color .15s; }
  button:hover:not(:disabled), .button:hover { background: var(--accent-soft); border-color: var(--accent-line); }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 600; }
  button.primary:hover:not(:disabled) { background: #2149b3; }
  button.danger { color: var(--bad); }
  button:disabled { opacity: .45; cursor: not-allowed; }
  a { color: var(--accent); }
  :focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
  .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
  .topbar { min-height: 64px; flex-shrink: 0; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 16px; padding: 9px 24px; background: var(--surface); border-bottom: 1px solid var(--line); }
  .brand, .top-tools { display: flex; align-items: center; gap: 13px; }
  .top-tools { margin-left: auto; }
  .brand-mark { width: 36px; height: 36px; display: grid; place-items: center; color: #fff; background: var(--text); border-radius: 10px; }
  .brand-mark svg { width: 21px; height: 21px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linejoin: round; }
  .brand h1 { font-size: 19px; letter-spacing: -.4px; white-space: nowrap; }
  .brand-caption { border-left: 1px solid var(--line); padding-left: 14px; color: var(--muted); font-size: 13px; white-space: nowrap; }
  #session-state, #sync-state { font-size: 12px; color: var(--muted); white-space: nowrap; }
  #session-state { display: inline-flex; align-items: center; gap: 6px; }
  #session-state::before { content: ""; width: 7px; height: 7px; flex-shrink: 0; border-radius: 50%; background: currentColor; }
  #session-state[data-state="valid"] { color: var(--ok); }
  #session-state[data-state="unavailable"] { color: var(--warn); }
  #session-state[data-state="expired"] { color: var(--bad); }
  #sync-state:empty { display: none; }
  .totals { display: flex; gap: 3px; }
  .total { display: flex; align-items: baseline; gap: 7px; padding: 4px 11px; border-color: transparent; white-space: nowrap; }
  .total[aria-pressed="true"] { background: var(--bg); border-color: var(--line); }
  .total strong { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .total span { font-size: 12px; color: var(--muted); }
  #active-total { color: var(--accent); } #success-total { color: var(--ok); } #attention-total { color: var(--bad); }
  #main { flex: 1; min-height: 0; display: flex; overflow: hidden; background: var(--surface); }
  #queue { flex: 0 0 auto; width: 30%; min-width: 260px; display: flex; flex-direction: column; min-height: 0; background: #fbfcfe; }
  .queue-tools { padding: 20px 18px 0; }
  .queue-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
  .queue-title h2 { font-size: 15px; display: flex; align-items: center; gap: 9px; }
  .queue-title > span { font-size: 11px; letter-spacing: 1.3px; color: var(--muted); }
  .count { padding: 0 7px; border-radius: 5px; font-size: 12px; font-weight: 500; background: #e9edf4; color: #56667d; }
  #search { width: 100%; border: 1px solid #ccd5e2; border-radius: 7px; background: var(--surface); padding: 9px 12px; color: var(--text); font-size: 13px; }
  #search::placeholder { color: var(--muted); }
  .filters { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0 8px; }
  .filter { padding: 0 9px; border-color: transparent; background: transparent; color: var(--muted); font-size: 12px; white-space: nowrap; }
  .filter[aria-pressed="true"] { color: var(--accent); background: var(--accent-soft); font-weight: 600; }
  .space-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
  .check-all { display: flex; align-items: center; gap: 7px; min-height: 44px; color: var(--muted); font-size: 12px; cursor: pointer; }
  input[type="checkbox"] { width: 15px; height: 15px; min-height: 15px; margin: 0; accent-color: var(--accent); flex-shrink: 0; }
  #space-filter { width: 110px; min-width: 0; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--muted); padding: 0 7px; font-size: 12px; }
  #list { flex: 1; min-height: 0; overflow-y: auto; padding: 13px 12px; display: flex; flex-direction: column; gap: 9px; scrollbar-width: thin; }
  .card { flex-shrink: 0; display: flex; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); }
  .card:hover { border-color: var(--accent-line); }
  .card.selected { background: #f0f5ff; border-color: #88a8ef; box-shadow: inset 3px 0 0 var(--accent); }
  .card-check { display: flex; align-items: flex-start; padding: 18px 5px 18px 13px; cursor: pointer; }
  .card-main { min-width: 0; flex: 1; display: block; text-align: left; padding: 12px 12px 13px 3px; border: 0; background: transparent; }
  .card-main:hover:not(:disabled) { background: transparent; }
  .card-main:focus-visible { outline-offset: -4px; }
  .card-kicker, .card-bottom { display: flex; justify-content: space-between; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; }
  .card-kicker { margin-bottom: 7px; flex-wrap: wrap; }
  .card-title { display: block; font-weight: 650; overflow-wrap: anywhere; }
  .card-meta { display: block; margin-top: 4px; font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }
  .card-bottom { margin-top: 12px; flex-wrap: wrap; }
  .tag-collection { display: inline-block; color: var(--accent); background: var(--accent-soft); font-size: 12px; padding: 0 6px; border-radius: 4px; margin-top: 7px; overflow-wrap: anywhere; }
  .status { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--muted); }
  .status::before { content: ""; width: 5px; height: 5px; flex-shrink: 0; border-radius: 50%; background: currentColor; }
  .status-pending, .status-approved { color: var(--warn); }
  .status-executing { color: var(--accent); } .status-succeeded { color: var(--ok); }
  .status-failed, .status-indeterminate { color: var(--bad); }
  .queue-bottom { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 12px 15px; background: var(--surface); border-top: 1px solid var(--line); }
  #selection-count { flex: 1; min-width: 65px; font-size: 12px; color: var(--muted); }
  .queue-bottom button { flex: 1; font-size: 12px; padding: 0 9px; white-space: nowrap; }
  .history-pages { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 6px 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; }
  .history-pages button { min-height: 36px; padding: 0 8px; white-space: nowrap; }
  #divider { flex: 0 0 8px; position: relative; cursor: col-resize; touch-action: none; background: #fbfcfe; }
  #divider::before { content: ""; position: absolute; top: 0; bottom: 0; left: 3px; width: 1px; background: var(--line); }
  #divider:hover::before { background: var(--accent); width: 2px; }
  #detail { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
  #detail-head { flex-shrink: 0; max-height: 36vh; overflow-y: auto; padding: 20px 27px 14px; }
  .detail-kicker { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  .detail-overview { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); align-items: start; gap: 10px 24px; margin-top: 10px; }
  .detail-context { display: grid; gap: 8px; overflow-wrap: anywhere; }
  .operation-type { display: flex; align-items: center; gap: 9px; color: var(--muted); font-size: 12px; }
  .type-label { padding: 3px 8px; color: var(--accent); background: var(--accent-soft); border-radius: 4px; font-size: 12px; font-weight: 600; }
  .detail-status { border: 1px solid var(--line); border-radius: 5px; padding: 3px 9px; background: var(--bg); }
  .detail-status.status-pending, .detail-status.status-approved { background: var(--warn-soft); border-color: #f1dfbc; }
  .detail-status.status-succeeded { background: var(--ok-soft); border-color: #c8e3d1; }
  .detail-status.status-failed, .detail-status.status-indeterminate { background: var(--bad-soft); border-color: #edc8c9; }
  #detail-head h2 { font-size: 23px; font-weight: 650; letter-spacing: -.4px; margin: 0 0 3px; overflow-wrap: anywhere; }
  .muted { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
  .version-message, .location { width: fit-content; max-width: 100%; padding: 5px 11px; border-radius: 14px; }
  .version-message { display: flex; align-items: baseline; gap: 8px; background: var(--accent-soft); font-size: 13px; }
  .version-message .label { flex-shrink: 0; color: var(--accent); }
  .version-message-text { min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
  .location { background: #f3f1ed; color: #574d40; font-size: 12px; }
  .location .label { margin-bottom: 3px; }
  .crumbs { overflow-wrap: anywhere; }
  .crumbs .sep { margin: 0 7px; color: var(--muted); }
  .newpage { margin-top: 3px; font-weight: 500; overflow-wrap: anywhere; }
  .metadata { margin-top: 9px; font-size: 12px; color: var(--muted); }
  .metadata > summary { width: fit-content; min-height: 30px; line-height: 30px; }
  .metadata-content { margin-top: 6px; padding: 10px 13px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); overflow-wrap: anywhere; }
  .metadata-content > div + div { margin-top: 5px; }
  .source { padding-top: 5px; }
  .label { font-size: 12px; font-weight: 600; }
  .url-text { font-size: 12px; overflow-wrap: anywhere; }
  .result { margin: 0; font: 12px/1.8 Consolas, "Microsoft YaHei", monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
  .result-details[open] { padding: 8px 12px; border-radius: 7px; background: var(--bg); }
  .result-details.status-succeeded[open] { background: var(--ok-soft); color: var(--ok); }
  .result-details[open]:is(.status-failed, .status-indeterminate) { background: var(--bad-soft); color: var(--bad); }
  #tabs { display: flex; gap: 24px; padding: 0 27px; border-top: 1px solid #edf0f5; border-bottom: 1px solid var(--line); }
  .tab { border: 0; border-bottom: 2px solid transparent; border-radius: 0; padding: 0 1px; min-height: 49px; background: transparent; font-size: 12px; color: var(--muted); white-space: nowrap; }
  .tab.selected { border-bottom-color: var(--accent); color: var(--accent); font-weight: 650; }
  #panel { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 8px; padding: 17px 25px 23px; background: #f3f5f9; }
  #panel pre { flex: 1; min-height: 0; overflow: auto; margin: 0 auto; width: 100%; max-width: 1000px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); color: var(--text); padding: 20px 24px; font: 12px/1.9 Consolas, "Microsoft YaHei", monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
  #panel pre.diff-view { padding: 10px 0; }
  .diff-line { display: block; min-height: 1lh; padding: 0 16px; }
  .diff-meta, .diff-hunk { color: var(--muted); background: #f5f7fa; }
  .diff-add { color: #185b35; background: #dff5e7; }
  .diff-remove { color: #8a2d35; background: #ffe6e8; }
  .limits { font-size: 12px; color: var(--muted); margin: 0; overflow-wrap: anywhere; }
  .limits summary { cursor: pointer; font-weight: 500; }
  .limits p { margin: 4px 0 0; }
  .frame { flex: 1 1 0; min-height: 0; width: 100%; max-width: 1000px; margin: 0 auto; border: 1px solid #e3e8ef; border-radius: 7px; background: var(--surface); }
  .detail-footer { flex-shrink: 0; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px 16px; padding: 14px 26px; border-top: 1px solid var(--line); }
  .footer-feedback { flex: 1 1 160px; min-width: 0; }
  #footer-state { font-size: 12px; color: #506079; }
  #footer-hint { margin-top: 3px; font-size: 12px; color: var(--muted); }
  #notice { font-size: 12px; overflow-wrap: anywhere; }
  #notice:not(:empty) { margin-top: 4px; }
  #notice.error { color: var(--bad); }
  .actions { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; margin-left: auto; }
  .actions button, .actions .button { white-space: nowrap; }
  .reject-action { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .rejection-reason { min-width: 0; padding: 0 10px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface); color: var(--text); font-size: 13px; }
  .rejection-reason::placeholder { color: var(--muted); }
  #rejection-reason { width: clamp(150px, 18vw, 250px); }
  #confirm-rejection { display: grid; gap: 6px; margin-top: 13px; }
  .button { display: inline-flex; align-items: center; min-height: 44px; font-size: 12px; text-decoration: none; }
  [hidden] { display: none !important; }
  dialog { width: min(490px, calc(100vw - 32px)); max-height: calc(100svh - 40px); padding: 27px; color: var(--text); border: 1px solid var(--line); border-radius: 13px; box-shadow: 0 22px 80px #172d4d30; }
  dialog::backdrop { background: #1c2e4e52; }
  dialog h2 { font-size: 20px; margin-bottom: 10px; }
  dialog p { color: var(--muted); font-size: 13px; }
  dialog ul { max-height: 220px; overflow-y: auto; padding: 12px 13px 12px 30px; margin: 17px 0; background: var(--bg); border: 1px solid var(--line); border-radius: 7px; font-size: 13px; overflow-wrap: anywhere; }
  dialog li { padding: 4px 0; }
  .dialog-actions { display: flex; justify-content: flex-end; gap: 9px; margin-top: 22px; }
  #approval-progress { width: min(320px, calc(100vw - 32px)); padding: 22px 24px; }
  #approval-progress-title { display: flex; align-items: center; gap: 10px; }
  #approval-progress-title::before { content: ""; width: 18px; height: 18px; flex-shrink: 0; border: 2px solid var(--line); border-top-color: var(--accent); border-radius: 50%; animation: approval-spin .8s linear infinite; }
  @keyframes approval-spin { to { transform: rotate(360deg); } }
  @media (max-width: 1100px) {
    .topbar { padding-inline: 18px; }
    .total { padding-inline: 10px; gap: 6px; }
    #detail-head { padding: 18px 21px 12px; } #tabs { padding: 0 21px; gap: 20px; }
    #panel { padding: 15px 17px 20px; } .detail-footer { padding: 12px 20px; }
  }
  @media (max-width: 760px) {
    body { height: auto; min-height: 100svh; overflow: auto; }
    .topbar { padding: 8px 16px; } .brand { gap: 8px; } .brand h1 { font-size: 17px; }
    .brand-mark { width: 32px; height: 32px; } .brand-caption, #sync-state { display: none; }
    .top-tools, .totals { width: 100%; }
    .total { flex: 1; justify-content: center; }
    #main { flex-direction: column; }
    #queue { width: auto !important; min-width: 0; height: 390px; border-bottom: 1px solid var(--line); }
    .queue-tools { padding: 16px 16px 0; } .queue-title { margin-bottom: 10px; } .filters { margin: 5px 0; } .space-row { padding-bottom: 5px; }
    #list { padding: 10px 12px; } #divider { display: none; }
    #detail { min-width: 0; height: 850px; }
    #detail-head { max-height: 330px; padding: 19px 17px 12px; } #detail-head h2 { font-size: 20px; }
    #tabs { gap: 20px; padding: 0 17px; } #panel { padding: 14px 12px 18px; }
    #panel pre { padding: 16px; } .detail-footer { padding: 13px 17px; } .actions { width: 100%; } .actions button { flex: 1; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { transition: none !important; }
    #approval-progress-title::before { animation: none; }
  }
</style>
</head>
<body>
<header class="topbar">
  <div class="brand">
    <div class="brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 9 5-9 5-9-5 9-5Z M3 12l9 5 9-5 M3 16l9 5 9-5"/></svg></div>
    <h1>Wiki Local</h1><span class="brand-caption">文档写入审批</span>
    <span id="session-state" data-state="checking" role="status">检查会话…</span>
  </div>
  <div class="top-tools">
    <div class="totals" role="group" aria-label="按状态查看审批记录">
      <button type="button" class="total" data-filter="active" aria-controls="list" aria-pressed="true"><strong id="active-total">—</strong><span>待处理</span></button>
      <button type="button" class="total" data-filter="succeeded" aria-controls="list" aria-pressed="false"><strong id="success-total">—</strong><span>已成功</span></button>
      <button type="button" class="total" data-filter="attention" aria-controls="list" aria-pressed="false"><strong id="attention-total">—</strong><span>需关注</span></button>
    </div>
    <span id="sync-state"></span>
  </div>
</header>
<main id="main">
  <aside id="queue" aria-label="审批队列">
    <div class="queue-tools">
      <div class="queue-title"><h2>审批队列 <span id="queue-count" class="count">0</span></h2><span>QUEUE</span></div>
      <label class="sr-only" for="search">搜索标题、操作 ID</label><input id="search" type="search" placeholder="搜索标题、操作 ID" autocomplete="off" maxlength="300">
      <div class="filters" role="group" aria-label="按操作状态筛选">
        <button type="button" class="filter" data-filter="active" aria-pressed="true">待处理 <span id="active-count">0</span></button>
        <button type="button" class="filter" data-filter="all" aria-pressed="false">全部</button>
        <button type="button" class="filter" data-filter="succeeded" aria-pressed="false">已成功</button>
        <button type="button" class="filter" data-filter="attention" aria-pressed="false">需关注</button>
        <button type="button" class="filter" data-filter="rejected" aria-pressed="false">已拒绝</button>
      </div>
      <div class="space-row">
        <label class="check-all"><input type="checkbox" id="check-all">选择当前结果</label>
        <label for="space-filter" class="sr-only">按空间筛选</label><select id="space-filter"><option value="">全部空间</option></select>
      </div>
    </div>
    <div id="list" aria-label="操作列表"></div>
    <nav id="history-pages" class="history-pages" aria-label="历史记录翻页" hidden>
      <button type="button" id="history-prev">上一页</button>
      <span id="history-position" aria-live="polite"></span>
      <button type="button" id="history-next">下一页</button>
    </nav>
    <div class="queue-bottom"><span id="selection-count">已勾选 0 条</span><button type="button" id="reject-selected" class="danger" disabled>拒绝所选</button><button type="button" id="approve-selected" class="primary" disabled>批准所选</button></div>
  </aside>
  <div id="divider" role="separator" tabindex="0" aria-orientation="vertical" aria-label="调整队列与文档宽度：拖动，或聚焦后用左右方向键" aria-valuemin="20" aria-valuemax="80" aria-valuenow="30"></div>
  <section id="detail" aria-label="操作详情">
    <div id="detail-head"></div>
    <div id="tabs" role="tablist" aria-label="文档查看方式">
      <button type="button" id="tab-preview" class="tab selected" role="tab" data-tab="preview" aria-controls="panel" aria-selected="true" tabindex="0">正文预览</button>
      <button type="button" id="tab-diff" class="tab" role="tab" data-tab="diff" aria-controls="panel" aria-selected="false" tabindex="-1">改动记录</button>
      <button type="button" id="tab-source" class="tab" role="tab" data-tab="source" aria-controls="panel" aria-selected="false" tabindex="-1">源码</button>
    </div>
    <div id="panel" role="tabpanel" aria-labelledby="tab-preview" tabindex="0"></div>
    <footer class="detail-footer">
      <div class="footer-feedback">
        <p id="footer-state">请选择一条操作</p><p id="footer-hint">核对目标位置与文档内容后审批</p>
        <p id="notice" role="status"></p>
      </div>
      <div class="actions">
        <a id="result-link" class="button" target="_blank" rel="noopener noreferrer" hidden>打开 Wiki 页面</a>
        <div class="reject-action">
          <label class="sr-only" for="rejection-reason">拒绝原因（可选）</label>
          <input id="rejection-reason" class="rejection-reason" type="text" placeholder="拒绝原因（可选）" maxlength="500" autocomplete="off" hidden>
          <button type="button" id="act-reject" class="danger" disabled>拒绝</button>
        </div>
        <button type="button" id="act-approve" class="primary" disabled>批准并写入</button>
      </div>
    </footer>
  </section>
</main>
<dialog id="confirm-dialog" aria-labelledby="confirm-title" aria-describedby="confirm-description">
  <h2 id="confirm-title">确认批准并写入</h2><p id="confirm-description"></p><ul id="confirm-items"></ul><p id="confirm-note"></p>
  <div id="confirm-rejection" hidden>
    <label for="confirm-reason">拒绝原因（可选）</label>
    <input id="confirm-reason" class="rejection-reason" type="text" maxlength="500" autocomplete="off">
  </div>
  <div class="dialog-actions"><button type="button" id="confirm-cancel" autofocus>取消</button><button type="button" id="confirm-submit" class="primary">确认写入</button></div>
</dialog>
<dialog id="approval-progress" aria-labelledby="approval-progress-title" aria-describedby="approval-progress-message">
  <h2 id="approval-progress-title">审批中</h2>
  <p id="approval-progress-message"></p>
</dialog>
<script>
"use strict";
// The split ratio is kept in a host-only, non-HttpOnly preference cookie named cmr_split. It is
// not a secret and is validated on read. Cookies ignore the port, so it survives a restart of `web`
// even though the port changes. The session cookie is HttpOnly and is never read or written here.
var $ = function (id) { return document.getElementById(id); };
var STATE_PATH = "/api/state";
var APPROVE_PATH = "/api/approve";
var REJECT_PATH = "/api/reject";
var ACTIONS = { create_page: "新建页面", add_comment: "新增评论", update_page: "整页更新", update_page_section: "章节更新", move_page: "调整位置", delete_page: "删除页面" };
var LOCATION_LABELS = { comment: "评论所在页面", move: "被移动页面的当前路径", update: "原 Wiki 页面路径（批准后修改此页）", delete: "待删除页面路径" };
var DELETE_NOTICE = "删除操作将把目标页移入回收站。子页面会保留，可能移动到上级。";
var STATUSES = { pending: "待审批", approved: "已批准·未写入", rejected: "已拒绝", executing: "写入中", succeeded: "已成功", failed: "失败", indeterminate: "结果不明" };
var LIMITS = "只还原标题、段落、列表、表格、代码块、外部图片和本次入队的图片快照。其他宏、已有附件、样式与权限以 Confluence 页面为准，未还原的宏会在预览中标出。预览在隔离沙箱中显示，不执行脚本。";
var SECTION_NOTE = "章节更新 · 下面是整页更新后的完整正文，包含本次替换的章节。";
var NARROW = "(max-width: 760px)";
var MIN_LIST = 260, MIN_DETAIL = 380, DEFAULT_SPLIT = 0.3;
var ops = [], selected = null, tab = "preview", locations = {}, locErrors = {}, locLoading = {};
var filter = "active", checked = new Set(), refreshing = null, refreshingPath = "", loadedPath = "";
var queueTotal = 0, totals = { active: 0, succeeded: 0, attention: 0 }, spaces = [];
var historyPage = 1, historyState = { page: 1, pages: 1 };
var confirmKind = "approve", confirmIds = [], busyLabel = "";
var busy = false, expired = false, timer = null, panelKey = "", headKey = "", dragging = false;
var split = readSplit();

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function notice(text, isError) {
  $("notice").textContent = text;
  $("notice").className = isError ? "error" : "";
}

function setSessionState(state, label, detail) {
  var indicator = $("session-state");
  if (indicator.dataset.state !== state) {
    indicator.dataset.state = state;
    indicator.textContent = label;
  }
  indicator.title = detail || "";
}

function locked() { return busy || expired; }

function stop() {
  expired = true;
  clearInterval(timer);
  ["confirm-dialog", "approval-progress"].forEach(function (id) {
    var dialog = $(id);
    if (dialog.open) dialog.close();
  });
  notice("会话失效，请重新打开审批页", true);
  setSessionState("expired", "会话失效");
  render();
}

function api(path, body) {
  var options = body === undefined
    ? { credentials: "same-origin" }
    : { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  return fetch(path, options).then(function (res) {
    if (res.status === 403) { stop(); throw new Error("forbidden"); }
    return res.json().catch(function () { return {}; }).then(function (data) {
      if (!res.ok) throw new Error(data.error || "HTTP " + res.status);
      return data;
    });
  });
}

function safeUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
}

function describe(op) {
  var error = op.error;
  var result = op.result;
  var text = "状态 · " + (STATUSES[op.status] || op.status);
  if (error) text += "\n错误 · " + error;
  if (result) {
    if (result.id) {
      text += "\n结果 · 页面 " + result.id;
      if (result.version != null) text += ", 版本 " + result.version;
      if (result.url) text += ", " + result.url;
    }
    if (result.rejection_reason) text += "\n拒绝原因 · " + result.rejection_reason;
    if (result.trashed) text += "\n已移入回收站";
    if (result.uploaded_attachments && result.uploaded_attachments.length) text += "\n已上传图片 · " + result.uploaded_attachments.join(", ");
    if (result.reused_attachments && result.reused_attachments.length) text += "\n已复用图片 · " + result.reused_attachments.join(", ");
    if (result.failed_attachment) text += "\n上传失败 · " + result.failed_attachment;
    if (result.uploading_attachment) text += "\n上传待核对 · " + result.uploading_attachment;
    var retries = Object.entries(result.attachment_upload_retries || {}).filter(function (item) {
      return item[1] > 0 || item[0] === result.failed_attachment || item[0] === result.uploading_attachment;
    });
    if (retries.length) text += "\n附件重试 · " + retries.map(function (item) { return item[0] + " · " + item[1] + " 次"; }).join(", ");
  }
  return text;
}

function heading(op) {
  if (op.title) return op.title;
  return op.action === "add_comment" ? "评论 · 页面 " + op.page_id : op.summary;
}

function crumbs(trail, partial) {
  var box = el("div", "crumbs");
  trail.forEach(function (item, i) {
    if (i) box.appendChild(el("span", "sep", "›"));
    var label = item.title || "(无标题)";
    var href = safeUrl(item.url);
    if (href) {
      var link = el("a", "", label);
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      box.appendChild(link);
    } else {
      box.appendChild(el("span", "", label));
    }
  });
  if (partial) box.appendChild(el("span", "muted", " （路径未完整返回）"));
  return box;
}

function locationBlock(op) {
  var box = el("div", "location");
  if (op.result && op.result.trashed) {
    box.appendChild(el("div", "label", "已移入回收站"));
    box.appendChild(el("div", "", heading(op)));
    return box;
  }
  var loc = locations[op.id];
  if (!loc) {
    var note = locErrors[op.id]
      ? "位置信息暂不可用：" + locErrors[op.id] + "。重新选择此条可再次读取。"
      : "正在读取位置…";
    box.appendChild(el("div", "muted", note));
    return box;
  }
  if (loc.mode === "create") {
    box.appendChild(el("div", "label", "Wiki 目标位置（新页面将创建于此）"));
    if (loc.trail.length) box.appendChild(crumbs(loc.trail, loc.partial));
    else box.appendChild(el("div", "", "空间 " + loc.space_key + " 根目录"));
    box.appendChild(el("div", "newpage", "新页面 · " + (loc.title || op.summary)));
  } else {
    box.appendChild(el("div", "label", LOCATION_LABELS[loc.mode] || LOCATION_LABELS.update));
    box.appendChild(crumbs(loc.trail, loc.partial));
  }
  return box;
}

// Original source named by the body's own provenance lines; it is not the Wiki destination.
function sourceBlock(op) {
  if (!op.source && !op.collection) return null;
  var box = el("div", "source");
  box.appendChild(el("div", "label", "原文来源"));
  if (op.collection) box.appendChild(el("div", "", "归档 · " + op.collection));
  if (op.source) {
    var href = safeUrl(op.source.url);
    var label = op.source.label || op.source.url;
    if (href) {
      var link = el("a", "", label);
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      box.appendChild(link);
    } else {
      box.appendChild(el("span", "", label));
    }
    box.appendChild(el("div", "url-text", op.source.url));
    if (op.source.parent) box.appendChild(el("div", "url-text", "上级目录 · " + op.source.parent));
  }
  return box;
}

function canApprove(op) {
  return op && (op.status === "pending" || op.status === "approved");
}

function visibleOps() {
  var query = $("search").value.trim().toLocaleLowerCase();
  var space = $("space-filter").value;
  return ops.filter(function (op) {
    var active = canApprove(op) || op.status === "executing";
    var matchesStatus = {
      active: active,
      all: historyPage === 1 || !active,
      succeeded: op.status === "succeeded",
      attention: op.status === "failed" || op.status === "indeterminate",
      rejected: op.status === "rejected"
    }[filter];
    return matchesStatus && (!space || op.space_key === space)
      && (!query || [heading(op), op.id, op.summary].join(" ").toLocaleLowerCase().includes(query));
  });
}

function checkedIds(kind) {
  return ops.filter(function (op) {
    return checked.has(op.id) && (kind === "reject" ? op.status === "pending" : canApprove(op));
  }).map(function (op) { return op.id; });
}

function renderSelection() {
  var eligible = visibleOps().filter(canApprove);
  var selectedCount = eligible.filter(function (op) { return checked.has(op.id); }).length;
  $("check-all").checked = eligible.length > 0 && selectedCount === eligible.length;
  $("check-all").indeterminate = selectedCount > 0 && selectedCount < eligible.length;
  $("check-all").disabled = locked() || !eligible.length;
  $("selection-count").textContent = "已勾选 " + checked.size + " 条";
  $("approve-selected").disabled = locked() || !checkedIds("approve").length;
  $("reject-selected").disabled = locked() || !checkedIds("reject").length;
}

function renderSpaces() {
  var control = $("space-filter");
  var values = Array.from(control.options).slice(1).map(function (option) { return option.value; });
  if (JSON.stringify(spaces) === JSON.stringify(values)) return;
  var previous = control.value;
  control.replaceChildren(el("option", "", "全部空间"));
  control.firstChild.value = "";
  spaces.forEach(function (space) {
    var option = el("option", "", space);
    option.value = space;
    control.appendChild(option);
  });
  control.value = spaces.includes(previous) ? previous : "";
}

function card(op) {
  var on = op.id === selected;
  var operationId = "操作 ID " + op.id;
  var box = el("div", "card" + (on ? " selected" : ""));
  var label = el("label", "card-check");
  var check = el("input");
  check.type = "checkbox";
  check.dataset.focus = "check-" + op.id;
  check.setAttribute("aria-label", "勾选 " + heading(op) + "，" + operationId);
  check.checked = checked.has(op.id);
  check.disabled = locked() || !canApprove(op);
  check.addEventListener("change", function () {
    if (check.checked) checked.add(op.id);
    else checked.delete(op.id);
    renderSelection();
  });
  label.appendChild(check);
  var button = el("button", "card-main");
  button.type = "button";
  button.dataset.focus = "open-" + op.id;
  button.setAttribute("aria-pressed", String(on));
  var kicker = el("span", "card-kicker");
  kicker.appendChild(el("span", "", (ACTIONS[op.action] || op.action) + " · " + (op.space_key || "未知空间")));
  var active = canApprove(op) || op.status === "executing";
  var timestamp = new Date(active ? op.created_at : op.updated_at);
  if (!Number.isNaN(timestamp.getTime())) {
    var time = el("span", "", active
      ? timestamp.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })
      : timestamp.toLocaleDateString("zh-CN"));
    time.title = (active ? "入队于 " : "结束于 ") + timestamp.toLocaleString("zh-CN", { hour12: false });
    kicker.appendChild(time);
  }
  button.appendChild(kicker);
  button.appendChild(el("span", "card-title", heading(op)));
  var meta = op.action === "update_page_section" ? "章节 · " + op.summary : (op.page_id ? "页面 " + op.page_id : "新页面");
  button.appendChild(el("span", "card-meta", meta + " · " + operationId));
  if (op.collection) button.appendChild(el("span", "tag-collection", op.collection));
  var bottom = el("span", "card-bottom");
  bottom.appendChild(el("span", "status status-" + op.status, STATUSES[op.status] || op.status));
  if (op.version_before) bottom.appendChild(el("span", "", "基于 v" + op.version_before));
  button.appendChild(bottom);
  button.addEventListener("click", function () { select(op.id); });
  box.appendChild(label);
  box.appendChild(button);
  return box;
}

function renderList() {
  var list = $("list");
  var active = document.activeElement;
  var focusId = active && active.dataset ? active.dataset.focus : undefined;
  var scrollTop = list.scrollTop;
  list.replaceChildren();
  var visible = visibleOps();
  if (!visible.length) list.appendChild(el("p", "muted", queueTotal ? "没有符合筛选条件的操作。" : "队列是空的。"));
  visible.forEach(function (op) { list.appendChild(card(op)); });
  list.scrollTop = scrollTop;
  if (focusId !== undefined) {
    var again = Array.from(list.querySelectorAll("[data-focus]")).find(function (node) { return node.dataset.focus === focusId; });
    if (again) again.focus({ preventScroll: true });
  }
  renderSelection();
}

function renderHead(op) {
  var head = $("detail-head");
  var previous = head.querySelector(".metadata");
  var wasOpen = previous && previous.dataset.id === op.id && previous.open;
  head.replaceChildren();
  var kicker = el("div", "detail-kicker");
  var type = el("div", "operation-type");
  type.appendChild(el("span", "type-label", ACTIONS[op.action] || op.action));
  type.appendChild(el("span", "", (op.space_key || "未知") + " 空间"));
  kicker.appendChild(type);
  kicker.appendChild(el("span", "status detail-status status-" + op.status, STATUSES[op.status] || op.status));
  head.appendChild(kicker);
  var overview = el("div", "detail-overview");
  var identity = el("div", "detail-identity");
  var title = el("h2", "", heading(op));
  title.id = "detail-title";
  identity.appendChild(title);
  var facts = ["操作 ID " + op.id];
  if (op.action === "update_page_section") facts.push("更新章节 · " + op.summary);
  if (op.version_before) facts.push("基于 v" + op.version_before);
  identity.appendChild(el("p", "muted", facts.join(" · ")));
  overview.appendChild(identity);
  var context = el("div", "detail-context");
  if (op.version_message) {
    var message = el("p", "version-message");
    message.appendChild(el("span", "label", "提交说明"));
    message.appendChild(el("span", "version-message-text", op.version_message));
    context.appendChild(message);
  }
  context.appendChild(locationBlock(op));
  overview.appendChild(context);
  head.appendChild(overview);
  var metadata = el("details", "metadata");
  metadata.dataset.id = op.id;
  metadata.open = Boolean(wasOpen);
  metadata.appendChild(el("summary", "", "来源、附件与操作信息"));
  var content = el("div", "metadata-content");
  content.appendChild(el("div", "", "入队时间 · " + op.created_at));
  if (!canApprove(op) && op.status !== "executing" && op.updated_at) {
    content.appendChild(el("div", "", "结束时间 · " + new Date(op.updated_at).toLocaleString("zh-CN", { hour12: false })));
  }
  var source = sourceBlock(op);
  if (source) content.appendChild(source);
  if (op.attachments && op.attachments.length) {
    content.appendChild(el("div", "label", "随正文上传的图片（" + op.attachments.length + "）"));
    op.attachments.forEach(function (image) {
      content.appendChild(el("div", "url-text", image.source + " → " + image.filename + " · " + image.size_bytes + " 字节"));
    });
  }
  metadata.appendChild(content);
  head.appendChild(metadata);
  if (op.result || op.error) {
    var result = el("details", "metadata result-details status-" + op.status);
    var rejected = op.status === "rejected";
    result.open = rejected || op.status === "failed" || op.status === "indeterminate";
    result.appendChild(el("summary", "", rejected ? "拒绝详情" : op.error ? "执行结果与错误详情" : "执行结果"));
    result.appendChild(el("pre", "result", describe(op)));
    head.appendChild(result);
  }
}

function buildPanel(op) {
  var panel = $("panel");
  var key = panelKey;
  panel.replaceChildren();
  if (op.action === "delete_page") {
    panel.appendChild(el("p", "limits", DELETE_NOTICE));
  } else if (op.action === "move_page") {
    panel.appendChild(el("p", "limits", "调整页面位置。下面是入队时计算的移动后顺序；批准时按 Confluence 当时的实际顺序执行。"));
    panel.appendChild(el("pre", "", op.preview || "(没有记录)"));
  } else if (tab === "preview") {
    var limits = el("details", "limits");
    limits.appendChild(el("summary", "", "本地近似预览 · 展开查看说明"));
    limits.appendChild(el("p", "", LIMITS));
    panel.appendChild(limits);
    if (op.action === "update_page_section") panel.appendChild(el("p", "limits", SECTION_NOTE));
    var frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "");
    frame.title = "正文预览";
    frame.className = "frame";
    frame.src = "/api/render?id=" + encodeURIComponent(op.id);
    panel.appendChild(frame);
  } else if (tab === "source") {
    var pre = el("pre", "", "正在加载源码…");
    panel.appendChild(el("p", "limits", "提交给 Confluence 的 storage XHTML，即批准后写入的正文。"));
    panel.appendChild(pre);
    api("/api/body?id=" + encodeURIComponent(op.id)).then(function (data) {
      if (panelKey === key) pre.textContent = data.storage || "(正文为空)";
    }, function (err) {
      if (panelKey === key) pre.textContent = "无法加载源码 · " + err.message;
    });
  } else {
    var caption = op.kind === "update"
      ? "入队时保存的统一 diff，相对入队前的版本。"
      : "入队时保存的 Markdown 原文。";
    panel.appendChild(el("p", "limits", caption));
    var diff = el("pre", op.kind === "update" ? "diff-view" : "");
    if (op.kind === "update") {
      var lines = (op.preview || "(没有记录)").split("\n");
      var hasHeaders = lines.length >= 3 && lines[0].startsWith("--- ") &&
        lines[1].startsWith("+++ ") && lines[2].startsWith("@@ ");
      lines.forEach(function (line, index) {
        var className = "diff-line";
        if (hasHeaders && index < 2) className += " diff-meta";
        else if (line.startsWith("@@ ")) className += " diff-hunk";
        else if (line.startsWith("+")) className += " diff-add";
        else if (line.startsWith("-")) className += " diff-remove";
        diff.appendChild(el("span", className, line + (index < lines.length - 1 ? "\n" : "")));
      });
    } else diff.textContent = op.preview || "(没有记录)";
    panel.appendChild(diff);
  }
}

function render() {
  renderList();
  $("queue-count").textContent = queueTotal;
  $("active-total").textContent = String(totals.active).padStart(2, "0");
  $("active-count").textContent = totals.active;
  $("success-total").textContent = String(totals.succeeded).padStart(2, "0");
  $("attention-total").textContent = String(totals.attention).padStart(2, "0");
  document.querySelectorAll("[data-filter]").forEach(function (button) { button.setAttribute("aria-pressed", String(button.dataset.filter === filter)); });
  $("history-pages").hidden = filter === "active" || historyState.pages <= 1;
  $("history-position").textContent = "历史 " + historyState.page + " / " + historyState.pages + " 页";
  $("history-prev").disabled = expired || historyState.page <= 1;
  $("history-next").disabled = expired || historyState.page >= historyState.pages;
  var op = ops.find(function (item) { return item.id === selected; });
  document.querySelectorAll(".tab").forEach(function (button) {
    var on = button.dataset.tab === tab;
    button.classList.toggle("selected", on);
    button.setAttribute("aria-selected", String(on));
    button.tabIndex = on ? 0 : -1;
  });
  $("panel").setAttribute("aria-labelledby", "tab-" + tab);
  if (!op) {
    $("detail-head").replaceChildren(el("p", "muted", queueTotal ? "选择左侧的一条操作查看正文。" : "队列是空的。"));
    $("panel").replaceChildren();
    headKey = "";
    panelKey = "";
  } else {
    var key = JSON.stringify([
      op.id, op.status, heading(op), op.summary, op.version_message, describe(op),
      op.source, op.collection, op.attachments, locations[op.id], locErrors[op.id]
    ]);
    if (key !== headKey) {
      headKey = key;
      renderHead(op);
    }
    // Keep the sandboxed frame and its scroll position across queue refreshes.
    if (op.id + "|" + tab !== panelKey) {
      panelKey = op.id + "|" + tab;
      buildPanel(op);
    }
  }
  $("act-approve").disabled = locked() || !canApprove(op);
  var canReject = op && op.status === "pending";
  $("act-reject").disabled = locked() || !canReject;
  var reasonInput = $("rejection-reason");
  var reasonFor = canReject ? op.id : "";
  if (reasonInput.dataset.operationId !== reasonFor) {
    reasonInput.dataset.operationId = reasonFor;
    reasonInput.value = "";
  }
  reasonInput.hidden = !canReject;
  reasonInput.disabled = locked();
  $("act-approve").textContent = busy ? "处理中…" : op && op.action === "delete_page" ? "批准删除" : op && op.status === "approved" ? "写入" : "批准并写入";
  var footerStates = {
    pending: "批准后立即写入 Confluence", approved: "已批准，等待写入", executing: "写入中，请等待结果",
    succeeded: "写入成功", failed: "写入失败，请核对执行结果", rejected: "已拒绝", indeterminate: "结果不明，需人工核对 Wiki"
  };
  if (op && op.result && op.result.trashed) footerStates.succeeded = "已移入回收站";
  $("footer-state").textContent = expired ? "审批会话已失效" : busy ? busyLabel : op ? footerStates[op.status] || op.status : "请选择一条操作";
  $("footer-hint").textContent = op && op.status === "indeterminate" ? "确认实际结果后再决定后续处理" : "核对目标位置、正文与版本后审批";
  var href = op && op.result && safeUrl(op.result.url);
  $("result-link").hidden = !href;
  if (href) $("result-link").href = href;
  else $("result-link").removeAttribute("href");
}

function statePath() {
  if (filter === "active") return STATE_PATH;
  return STATE_PATH + "?" + new URLSearchParams({
    history: filter, page: historyPage, space: $("space-filter").value, q: $("search").value.trim()
  });
}

function refresh(force) {
  var path = statePath();
  if (!force && refreshing && refreshingPath === path) return refreshing;
  refreshingPath = path;
  var request = api(path).then(function (data) {
    // A slow response from a previous filter must not replace the current list.
    if (expired || request !== refreshing || path !== statePath()) return;
    var changedView = path !== loadedPath;
    ops = data.operations;
    totals = data.totals;
    queueTotal = data.total;
    spaces = data.spaces;
    historyState = data.history;
    if (filter !== "active") historyPage = historyState.page;
    loadedPath = statePath();
    checked.forEach(function (id) {
      if (!canApprove(ops.find(function (op) { return op.id === id; }))) checked.delete(id);
    });
    renderSpaces();
    $("sync-state").textContent = "更新于 " + new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setSessionState("valid", "会话有效");
    if (changedView || !ops.some(function (op) { return op.id === selected; })) selectVisible();
    else render();
  }, function (err) {
    if (!expired && request === refreshing && path === statePath()) {
      setSessionState("unavailable", "刷新失败", "5 秒后重试 · " + err.message);
    }
    throw err;
  }).finally(function () { if (request === refreshing) refreshing = null; });
  refreshing = request;
  return request;
}

function loadLocation(id) {
  if (locations[id] || locLoading[id]) return;
  locLoading[id] = true;
  delete locErrors[id];
  api("/api/location?id=" + encodeURIComponent(id)).then(function (data) {
    locations[id] = data;
  }, function (err) {
    locErrors[id] = err.message;
  }).then(function () {
    locLoading[id] = false;
    if (selected === id) render();
  });
}

function select(id) {
  selected = id;
  if (id) loadLocation(id);
  render();
}

function selectVisible() {
  var visible = visibleOps();
  $("list").scrollTop = 0;
  if (!visible.some(function (op) { return op.id === selected; })) select(visible.length ? visible[0].id : null);
  else render();
}

function changeFilter() {
  historyPage = 1;
  selectVisible();
  if (statePath() !== loadedPath) refresh().catch(function () {});
}

function confirmAction(kind, ids, reason) {
  if (locked()) return;
  confirmIds = ids.filter(function (id) {
    var op = ops.find(function (item) { return item.id === id; });
    return kind === "reject" ? op && op.status === "pending" : canApprove(op);
  });
  if (!confirmIds.length) return;
  if (confirmIds.length > 200) {
    notice("单次最多处理 200 条，请减少勾选数量。", true);
    return;
  }
  confirmKind = kind;
  var approve = kind === "approve";
  var confirmed = confirmIds.map(function (id) { return ops.find(function (item) { return item.id === id; }); });
  var includesDelete = approve && confirmed.some(function (op) { return op.action === "delete_page"; });
  $("confirm-title").textContent = approve ? "确认批准并写入" : "确认拒绝操作";
  $("confirm-description").textContent = "本次将" + (approve ? "批准并写入 " : "拒绝 ") + confirmIds.length + " 条操作，请核对范围。";
  $("confirm-note").textContent = approve ? "确认后立即执行，结果将在页面中显示。" : "确认后将这些待审批操作标记为已拒绝。";
  if (includesDelete) $("confirm-note").textContent += " " + DELETE_NOTICE;
  $("confirm-rejection").hidden = approve;
  $("confirm-reason").value = reason || "";
  $("confirm-submit").textContent = approve ? (includesDelete ? "确认执行" : "确认写入") : "确认拒绝";
  $("confirm-submit").className = approve && !includesDelete ? "primary" : "danger";
  $("confirm-items").replaceChildren();
  confirmed.forEach(function (op) {
    $("confirm-items").appendChild(el("li", "", heading(op) + " · " + (op.space_key || "未知空间") + " · " + (ACTIONS[op.action] || op.action)));
  });
  $("confirm-dialog").showModal();
}

function act(kind, ids, reason) {
  if (locked()) return;
  var approve = kind === "approve";
  var progress = $("approval-progress");
  busy = true;
  busyLabel = "正在" + (approve ? "写入 " : "拒绝 ") + ids.length + " 条操作…";
  notice("", false);
  render();
  if (approve) {
    $("approval-progress-message").textContent = busyLabel;
    progress.showModal();
  }
  var body = { ids: ids };
  if (!approve && reason) body.reason = reason;
  return api(approve ? APPROVE_PATH : REJECT_PATH, body).finally(function () {
    if (progress.open) progress.close();
  }).then(function (out) {
    if (approve) {
      var executed = out.executed || [];
      executed.forEach(function (result) {
        var op = ops.find(function (item) { return item.id === result.operation_id; });
        if (op) Object.assign(op, { status: result.status, result: result.result, error: result.error });
      });
      var count = function (status) { return executed.filter(function (result) { return result.status === status; }).length; };
      var failed = count("failed"), unknown = count("indeterminate");
      var parts = ["成功 " + count("succeeded") + " 条", "失败 " + failed + " 条", "结果不明 " + unknown + " 条"];
      if ((out.not_pending || []).length) parts.push(out.not_pending.length + " 条已处理或状态已变化");
      if ((out.skipped || []).length) parts.push(out.skipped.length + " 条已跳过，请核对后继续审批");
      notice(parts.join("，"), failed > 0 || unknown > 0 || (out.skipped || []).length > 0);
    } else {
      var rejected = out.rejected || [];
      rejected.forEach(function (id) {
        var op = ops.find(function (item) { return item.id === id; });
        if (op) Object.assign(op, { status: "rejected", result: reason ? { rejection_reason: reason } : null });
      });
      var unchanged = ids.length - rejected.length;
      notice("已拒绝 " + rejected.length + " 条" + (unchanged ? "，" + unchanged + " 条状态已变化" : ""), false);
    }
    checked.forEach(function (id) {
      if (!canApprove(ops.find(function (op) { return op.id === id; }))) checked.delete(id);
    });
  }).catch(function (err) {
    if (err.message !== "forbidden") notice("请求失败，请核对队列中的执行状态。" + err.message, true);
  }).finally(function () {
    busy = false;
    render();
    if (!expired) return refresh(true).catch(function () {});
  });
}

$("search").addEventListener("input", changeFilter);
$("space-filter").addEventListener("change", changeFilter);
document.querySelectorAll("[data-filter]").forEach(function (button) {
  button.addEventListener("click", function () { filter = button.dataset.filter; changeFilter(); });
});
["history-prev", "history-next"].forEach(function (id, index) {
  $(id).addEventListener("click", function () {
    historyPage = historyState.page + (index ? 1 : -1);
    refresh().catch(function () {});
  });
});
$("check-all").addEventListener("change", function () {
  visibleOps().filter(canApprove).forEach(function (op) {
    if ($("check-all").checked) checked.add(op.id);
    else checked.delete(op.id);
  });
  renderList();
});
$("approve-selected").addEventListener("click", function () { confirmAction("approve", checkedIds("approve")); });
$("reject-selected").addEventListener("click", function () { confirmAction("reject", checkedIds("reject")); });
$("act-approve").addEventListener("click", function () { if (selected) confirmAction("approve", [selected]); });
$("act-reject").addEventListener("click", function () { if (selected) confirmAction("reject", [selected], $("rejection-reason").value); });
$("confirm-cancel").addEventListener("click", function () { $("confirm-dialog").close(); });
$("confirm-submit").addEventListener("click", function () {
  var ids = confirmIds.slice();
  var reason = $("confirm-reason").value.trim();
  $("confirm-dialog").close();
  act(confirmKind, ids, reason);
});

var tabs = Array.from(document.querySelectorAll(".tab"));
tabs.forEach(function (button, index) {
  button.addEventListener("click", function () { tab = button.dataset.tab; render(); });
  button.addEventListener("keydown", function (event) {
    var target = -1;
    if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
    if (event.key === "ArrowLeft") target = (index + tabs.length - 1) % tabs.length;
    if (event.key === "Home") target = 0;
    if (event.key === "End") target = tabs.length - 1;
    if (target < 0) return;
    event.preventDefault();
    tabs[target].click();
    tabs[target].focus();
  });
});

// Pointer and keyboard resizing share the queue and detail width limits in applySplit.
function readSplit() {
  var match = /(?:^|;\s*)cmr_split=(0\.\d{1,3})(?:;|$)/.exec(document.cookie);
  var value = match ? parseFloat(match[1]) : NaN;
  return value >= 0.1 && value <= 0.9 ? value : DEFAULT_SPLIT;
}

function saveSplit() {
  document.cookie = "cmr_split=" + split.toFixed(3) + "; Path=/; Max-Age=31536000; SameSite=Strict";
}

function applySplit() {
  var queue = $("queue"), divider = $("divider"), main = $("main");
  if (window.matchMedia(NARROW).matches) {
    queue.style.width = "";
    divider.removeAttribute("aria-valuenow");
    return;
  }
  var width = main.clientWidth - divider.offsetWidth;
  var lo = MIN_LIST / width, hi = (width - MIN_DETAIL) / width;
  split = Math.min(hi, Math.max(lo, split));
  queue.style.width = Math.round(split * width) + "px";
  divider.setAttribute("aria-valuemin", String(Math.round(lo * 100)));
  divider.setAttribute("aria-valuemax", String(Math.round(hi * 100)));
  divider.setAttribute("aria-valuenow", String(Math.round(split * 100)));
}

function setSplit(value) {
  split = value;
  applySplit();
  saveSplit();
}

var divider = $("divider");
divider.addEventListener("pointerdown", function (e) {
  dragging = true;
  divider.setPointerCapture(e.pointerId);
  e.preventDefault();
});
divider.addEventListener("pointermove", function (e) {
  if (!dragging) return;
  var main = $("main");
  var rect = main.getBoundingClientRect();
  var width = main.clientWidth - divider.offsetWidth;
  split = (e.clientX - rect.left - divider.offsetWidth / 2) / width;
  applySplit();
});
function endDrag() {
  if (dragging) { dragging = false; saveSplit(); }
}
divider.addEventListener("pointerup", endDrag);
divider.addEventListener("pointercancel", endDrag);
divider.addEventListener("keydown", function (e) {
  var step = { ArrowLeft: -0.02, ArrowRight: 0.02 }[e.key];
  if (step) setSplit(split + step);
  else if (e.key === "Home") setSplit(0);
  else if (e.key === "End") setSplit(1);
  else return;
  e.preventDefault();
});
window.addEventListener("resize", applySplit);
window.matchMedia(NARROW).addEventListener("change", applySplit);
applySplit();

refresh().catch(function () {});
timer = setInterval(function () { if (!busy) refresh().catch(function () {}); }, 5000);
</script>
</body>
</html>
"""

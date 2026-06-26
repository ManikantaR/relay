import * as vscode from 'vscode';

export interface Board {
  ready: any[];
  active: any[];
  review: any[];
}

export interface SessionDetail {
  session: any;
  timeline: any[];
  evidence: any;
  transcriptPreview: string[];
  changedFiles: Array<{ path: string; added: number; removed: number }>;
  diffAvailable: boolean;
}

function makeNonce(): string {
  const c = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let s = '';
  for (let i = 0; i < 32; i++) { s += c.charAt(Math.floor(Math.random() * c.length)); }
  return s;
}

export class Dashboard {
  static current: Dashboard | undefined;
  private panel: vscode.WebviewPanel;

  static show(
    ctx: vscode.ExtensionContext,
    onCommand: (msg: any) => void,
    onReady: () => void,
  ): void {
    if (Dashboard.current) {
      Dashboard.current.panel.reveal();
      onReady();
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      'relayDashboard',
      'Relay Mission Control',
      vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: false },
    );
    Dashboard.current = new Dashboard(panel, ctx, onCommand);
    panel.onDidDispose(() => (Dashboard.current = undefined), null, ctx.subscriptions);
    onReady();
  }

  constructor(
    panel: vscode.WebviewPanel,
    ctx: vscode.ExtensionContext,
    onCommand: (msg: any) => void,
  ) {
    this.panel = panel;
    panel.webview.html = this.html();
    panel.webview.onDidReceiveMessage((m) => onCommand(m), null, ctx.subscriptions);
  }

  update(board: Board): void {
    this.panel.webview.postMessage({ type: 'board', board });
  }

  updateDetail(detail: SessionDetail | null): void {
    this.panel.webview.postMessage({ type: 'detail', detail });
  }

  private html(): string {
    const n = makeNonce();
    const csp = `default-src 'none'; style-src 'nonce-${n}'; script-src 'nonce-${n}';`;
    return [
      '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
      `<meta http-equiv="Content-Security-Policy" content="${csp}">`,
      `<style nonce="${n}">`,
      'html,body{height:100%}',
      'body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);font-size:var(--vscode-font-size);margin:0;padding:14px;background:var(--vscode-editor-background);box-sizing:border-box;overflow:hidden}',
      '.shell{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:12px;height:calc(100vh - 28px);min-height:0}',
      '.main{min-width:0;min-height:0;display:grid;grid-template-rows:auto auto auto 1fr;gap:12px}',
      '.side{min-width:0;min-height:0;overflow:auto;padding-right:2px}',
      '.hdr{display:flex;align-items:center;gap:10px;margin-bottom:12px}',
      'h2{font-weight:500;font-size:15px;margin:0}',
      '.summary{display:flex;align-items:center;gap:8px}',
      '.badge{background:var(--vscode-badge-background);color:var(--vscode-badge-foreground);border-radius:999px;padding:3px 10px;font-size:11px}',
      '.toolbar{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}',
      '.btn{font-family:inherit;font-size:12px;border:none;border-radius:4px;padding:5px 12px;cursor:pointer;background:var(--vscode-button-background);color:var(--vscode-button-foreground)}',
      '.btn:hover{background:var(--vscode-button-hoverBackground)}',
      '.btn.sec{background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}',
      '.btn.danger{background:transparent;color:var(--vscode-errorForeground);border:1px solid color-mix(in srgb, var(--vscode-errorForeground) 45%, transparent)}',
      '.btn:focus-visible,.session-card:focus-visible,.queue-card:focus-visible,.mini-card:focus-visible{outline:1px solid var(--vscode-focusBorder);outline-offset:2px}',
      '.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px}',
      '.stat{background:var(--vscode-editorWidget-background);border:1px solid var(--vscode-widget-border,var(--vscode-panel-border));border-radius:6px;padding:8px 10px;min-width:0}',
      '.stat .k{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--vscode-descriptionForeground);margin-bottom:8px}',
      '.stat .v{font-size:20px;line-height:1;color:var(--vscode-foreground)}',
      '.stat .s{margin-top:7px;height:8px;border-radius:999px;background:linear-gradient(90deg, var(--vscode-charts-blue), transparent)}',
      '.panel{background:var(--vscode-editorWidget-background);border:1px solid var(--vscode-widget-border,var(--vscode-panel-border));border-radius:6px}',
      '.session-card{padding:12px 14px}',
      '.session-top{display:flex;align-items:flex-start;gap:10px}',
      '.session-top .grow{min-width:0;flex:1}',
      '.title{font-size:14px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.sub{font-size:11px;color:var(--vscode-descriptionForeground);margin-top:4px}',
      '.stale{font-size:11px;color:var(--vscode-descriptionForeground);white-space:nowrap}',
      '.chips,.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}',
      '.chip{font-size:10.5px;border-radius:999px;padding:2px 8px;background:var(--vscode-badge-background);color:var(--vscode-badge-foreground)}',
      '.chip.warn{background:color-mix(in srgb, var(--vscode-charts-orange) 24%, transparent);color:var(--vscode-charts-orange)}',
      '.chip.danger{background:color-mix(in srgb, var(--vscode-errorForeground) 18%, transparent);color:var(--vscode-errorForeground)}',
      '.chip.t2{background:color-mix(in srgb, var(--vscode-charts-purple) 35%, transparent);color:var(--vscode-charts-purple)}',
      '.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;min-height:0}',
      '.grid.two{grid-template-columns:1.2fr .8fr}',
      '.box{padding:12px 14px;min-width:0;min-height:0;display:flex;flex-direction:column}',
      '.box h3{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--vscode-descriptionForeground);margin:0 0 10px}',
      '.scroll{min-height:0;overflow:auto;padding-right:2px}',
      '#grid-top .box .scroll{max-height:220px}',
      '#grid-bottom .box .scroll{max-height:240px}',
      '.timeline-item,.transcript-line{font-size:12px;line-height:1.45;margin-bottom:8px}',
      '.timeline-item:last-child,.transcript-line:last-child,.file:last-child,.evidence-row:last-child,.queue-card:last-child,.mini-card:last-child{margin-bottom:0}',
      '.time{color:var(--vscode-descriptionForeground);display:inline-block;min-width:62px}',
      '.event{color:var(--vscode-foreground)}',
      '.mut{color:var(--vscode-descriptionForeground)}',
      '.link{display:inline-flex;align-items:center;gap:4px;color:var(--vscode-textLink-foreground);text-decoration:none;font-size:12px;margin-top:8px}',
      '.link:hover{text-decoration:underline}',
      '.file{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;font-size:12px;line-height:1.4;margin-bottom:8px}',
      '.path{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--vscode-editor-font-family)}',
      '.delta{display:flex;gap:10px;font-family:var(--vscode-editor-font-family)}',
      '.add{color:var(--vscode-charts-green)}',
      '.del{color:var(--vscode-charts-red)}',
      '.evidence-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;font-size:12px;line-height:1.45;margin-bottom:6px}',
      '.ok{color:var(--vscode-testing-iconPassed)}',
      '.bad{color:var(--vscode-errorForeground)}',
      '.warn{color:var(--vscode-charts-orange)}',
      '.queue-section{margin-bottom:12px}',
      '.queue-head{display:flex;align-items:center;gap:8px;margin:0 0 10px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--vscode-descriptionForeground)}',
      '.count{background:var(--vscode-badge-background);color:var(--vscode-badge-foreground);border-radius:999px;padding:0 7px;font-size:10px}',
      '.queue-card,.mini-card{padding:12px 14px}',
      '.queue-card{margin-bottom:10px}',
      '.queue-card.attn,.mini-card.attn{border:1px solid color-mix(in srgb, var(--vscode-errorForeground) 45%, transparent)}',
      '.queue-title{font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.queue-meta{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px}',
      '.queue-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}',
      '.empty{padding:12px 14px;color:var(--vscode-descriptionForeground);font-size:12px}',
      '.notice{padding:10px 12px;border-top:1px solid var(--vscode-panel-border);color:var(--vscode-descriptionForeground);font-size:11px}',
      '@media (max-width: 1180px){.shell{grid-template-columns:minmax(0,1fr) 252px}.stats{grid-template-columns:repeat(3,minmax(0,1fr))}.grid{grid-template-columns:1fr}.grid.two{grid-template-columns:1fr}}',
      '@media (max-width: 980px){body{overflow:auto}.shell{grid-template-columns:minmax(0,1fr);height:auto}.main{display:block}.side{order:-1;overflow:visible}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}#grid-top .box .scroll,#grid-bottom .box .scroll{max-height:none}}',
      '</style></head><body>',
      '<div class="hdr">',
      '<h2>Relay Mission Control</h2>',
      '<div class="summary"><span class="badge" id="summary">Loading…</span></div>',
      '<div class="toolbar" role="toolbar" aria-label="Relay actions">',
      '<button class="btn" data-cmd="pull">Dispatch…</button>',
      '<button class="btn sec" data-cmd="togglePause">Pause All</button>',
      '<button class="btn sec" data-cmd="refresh">Refresh</button>',
      '</div></div>',
      '<div class="shell">',
      '<div class="main">',
      '<div class="stats" id="stats"></div>',
      '<div class="panel session-card" id="focus"></div>',
      '<div class="grid" id="grid-top"></div>',
      '<div class="grid two" id="grid-bottom"></div>',
      '</div>',
      '<div class="side">',
      '<div class="queue-section"><div class="queue-head">Needs Decision <span class="count" id="needs-count">0</span></div><div id="needs"></div></div>',
      '<div class="queue-section"><div class="queue-head">Review Queue <span class="count" id="review-count">0</span></div><div id="review"></div></div>',
      '<div class="queue-section"><div class="queue-head">Ready Queue <span class="count" id="ready-count">0</span></div><div id="ready"></div></div>',
      '</div></div>',
      `<script nonce="${n}">`,
      'const vscode=acquireVsCodeApi();',
      'const state=vscode.getState()||{board:{ready:[],active:[],review:[]},selectedSessionId:"",detail:null};',
      'const byId=(id)=>document.getElementById(id);',
      'const esc=(s)=>String(s||"").replace(/[&<>"]/g,(c)=>({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]));',
      'const ago=(s)=>s||"";',
      'const chip=(label,cls="")=>`<span class="chip ${cls}">${esc(label)}</span>`;',
      'const preferSession=(board)=>{const rows=board.active||[];const rank={needs_decision:0,running:1,review_requested:2,paused:3,rate_limited:4,held:5,error:6,done:9,terminated:9};return rows.slice().sort((a,b)=>(rank[a.state]??8)-(rank[b.state]??8))[0]?.session_id||"";};',
      'const send=(type,payload)=>vscode.postMessage(Object.assign({type},payload||{}));',
      'function ensureSelected(){const active=(state.board.active||[]).map((r)=>r.session_id);if(!state.selectedSessionId||!active.includes(state.selectedSessionId)){state.selectedSessionId=preferSession(state.board);}if(state.selectedSessionId){send("selectSession",{sessionId:state.selectedSessionId});}}',
      'function statCard(label,value,cls){return `<div class="stat"><div class="k">${label}</div><div class="v">${value}</div><div class="s ${cls||""}"></div></div>`;}',
      'function renderStats(){const b=state.board||{ready:[],active:[],review:[]};const active=b.active||[];const waiting=active.filter((r)=>["paused","rate_limited"].includes(r.state)).length;const working=active.filter((r)=>r.state==="running").length;const needs=active.filter((r)=>r.state==="needs_decision").length;byId("summary").textContent=`${active.length} active · ${b.review.length} in review`;byId("stats").innerHTML=[statCard("Active",active.length,"active"),statCard("Working",working,"working"),statCard("Waiting",waiting,"waiting"),statCard("Review",b.review.length,"review"),statCard("Needs Decision",needs,"needs")].join("");}',
      'function renderFocus(){const d=state.detail;const focus=byId("focus");if(!d||!d.session){focus.innerHTML=`<div class="empty">Select an active session to inspect its timeline, evidence, transcript, and controls.</div>`;byId("grid-top").innerHTML="";byId("grid-bottom").innerHTML="";return;}const s=d.session;focus.innerHTML=`<div class="session-top"><div class="grow"><div class="title mono">${esc(s.task_id||s.session_id)}</div><div class="sub">${esc((s.repo||"").split("/").pop())} · ${esc(s.role||"-")} · ${esc(s.model||s.lane||"-")}</div><div class="chips">${chip(`lane: ${s.lane||"-"}`)}${chip(`tier: ${s.tier==="2"?"tier-2":"tier-1"}`,s.tier==="2"?"t2":"")}${chip(`state: ${s.state||"-"}`,["needs_decision","error"].includes(s.state)?"danger":(s.state==="rate_limited"?"warn":""))}</div><div class="actions"><button class="btn sec" data-session-cmd="peek">Peek</button><button class="btn sec" data-session-cmd="attachTerminal">Attach</button><button class="btn sec" data-session-cmd="requestCheckpoint">Checkpoint</button><button class="btn sec" data-session-cmd="refreshSession">Refresh</button><button class="btn danger" data-session-cmd="terminateSession">Terminate</button></div></div><div class="stale">${esc(s.updated_at||"")}</div></div>`;',
      'const timeline=(d.timeline||[]).slice(-5).reverse().map((e)=>`<div class="timeline-item"><span class="time">${esc(e.timestamp?e.timestamp.slice(11,16):"")}</span><span class="event">${esc(e.summary||e.type||"")}</span></div>`).join("")||`<div class="empty">No timeline events yet.</div>`;',
      'const files=(d.changedFiles||[]).slice(0,8).map((f)=>`<div class="file"><div class="path">${esc(f.path)}</div><div class="delta"><span class="add">+${f.added}</span><span class="del">-${f.removed}</span></div></div>`).join("")||`<div class="empty">No changed files yet.</div>`;',
      'const ev=d.evidence||{};',
      'const evidence=[["Summary",ev.summary_exists?"present":"missing",ev.summary_exists?"ok":"warn"],["Pytest",ev.pytest_exists?"present":"missing",ev.pytest_exists?"ok":"warn"],["Screenshots",String((ev.screenshots||[]).length),(ev.screenshots||[]).length?"ok":"mut"],["Transcript",d.transcriptPreview&&d.transcriptPreview.length?"available":"empty",d.transcriptPreview&&d.transcriptPreview.length?"ok":"warn"]].map((r)=>`<div class="evidence-row"><div>${esc(r[0])}</div><div class="${r[2]}">${esc(r[1])}</div></div>`).join("");',
      'const transcript=(d.transcriptPreview||[]).map((line)=>`<div class="transcript-line mono">${esc(line)}</div>`).join("")||`<div class="empty">No transcript output yet.</div>`;',
      'byId("grid-top").innerHTML=`<div class="panel box"><h3>Timeline</h3><div class="scroll">${timeline}</div><a class="link" href="#" data-session-cmd="viewTimeline">Open full timeline</a></div><div class="panel box"><h3>Changed Files</h3><div class="scroll">${files}</div>${d.diffAvailable?`<a class="link" href="#" data-session-cmd="viewDiff">View diff</a>`:""}</div><div class="panel box"><h3>Evidence</h3><div class="scroll">${evidence}</div><a class="link" href="#" data-session-cmd="viewEvidence">Inspect evidence</a></div>`;',
      'byId("grid-bottom").innerHTML=`<div class="panel box"><h3>Transcript (latest)</h3><div class="scroll">${transcript}</div><a class="link" href="#" data-session-cmd="peek">Open full transcript</a></div><div class="panel box"><h3>Operator Notes</h3><div class="scroll"><div class="empty">Use checkpoint requests and session refresh to steer the worker. Notes are still local-terminal driven.</div></div></div>`;',
      'Array.from(document.querySelectorAll("[data-session-cmd]")).forEach((el)=>el.addEventListener("click",(evt)=>{evt.preventDefault();send("sessionCommand",{command:el.getAttribute("data-session-cmd"),sessionId:s.session_id,taskId:s.task_id});}));}',
      'function queueCard(item,kind){const attn=kind==="needs"?" attn":"";const repo=((item.repo||"").split("/").pop())||"";const title=item.title||item.task||item.session_id||"";const meta=kind==="review"?`${repo}#${item.id}`:repo;const chips=(kind==="review"?`${item.tier==="2"?chip("tier-2","t2"):""}${item.url?chip("pr"):""}`:`${item.lane?chip(item.lane):""}${item.state?chip(item.state,["needs_decision","error"].includes(item.state)?"danger":""):""}`);let actions="";if(kind==="review"){actions=`<div class="queue-actions"><button class="btn sec" data-open-url="${esc(item.url||"")}">Review PR</button></div>`;}else if(item.session_id){actions=`<div class="queue-actions"><button class="btn sec" data-select-session="${esc(item.session_id)}">Open session</button><button class="btn sec" data-session-action="peek" data-session-id="${esc(item.session_id)}" data-task-id="${esc(item.task||item.task_id||"")}">Peek</button></div>`;}return `<div class="panel queue-card${attn}"><div class="queue-title">${esc(title)}</div><div class="queue-meta"><span class="mut">${esc(meta)}</span>${chips}</div>${item.now?`<div class="sub">${esc(item.now)}</div>`:""}${actions}</div>`;}',
      'function readyCard(item){return `<div class="panel mini-card"><div class="queue-title">${esc(item.title||"")}</div><div class="queue-meta"><span class="mut">${esc(((item.repo||"").split("/").pop())||"")}#${esc(item.id||"")}</span>${item.tier==="2"?chip("tier-2","t2"):""}${item.lane?chip(item.lane):chip("hold","warn")}</div><div class="queue-actions"><button class="btn sec" data-dispatch-id="${esc(item.id||"")}" data-repo="${esc(item.repo||"")}">Dispatch</button></div></div>`;}',
      'function bindQueueActions(){Array.from(document.querySelectorAll("[data-select-session]")).forEach((el)=>el.addEventListener("click",()=>{state.selectedSessionId=el.getAttribute("data-select-session")||"";vscode.setState(state);send("selectSession",{sessionId:state.selectedSessionId});}));Array.from(document.querySelectorAll("[data-session-action]")).forEach((el)=>el.addEventListener("click",()=>send("sessionCommand",{command:el.getAttribute("data-session-action"),sessionId:el.getAttribute("data-session-id"),taskId:el.getAttribute("data-task-id")})));Array.from(document.querySelectorAll("[data-open-url]")).forEach((el)=>el.addEventListener("click",()=>send("openUrl",{url:el.getAttribute("data-open-url")})));Array.from(document.querySelectorAll("[data-dispatch-id]")).forEach((el)=>el.addEventListener("click",()=>send("dispatchId",{id:el.getAttribute("data-dispatch-id"),repo:el.getAttribute("data-repo")})));}',
      'function renderQueues(){const b=state.board||{ready:[],active:[],review:[]};const needs=(b.active||[]).filter((r)=>r.state==="needs_decision");byId("needs-count").textContent=String(needs.length);byId("review-count").textContent=String((b.review||[]).length);byId("ready-count").textContent=String((b.ready||[]).length);byId("needs").innerHTML=needs.length?needs.map((r)=>queueCard(r,"needs")).join(""):`<div class="empty">Nothing waiting on an owner decision.</div>`;byId("review").innerHTML=(b.review||[]).length?(b.review||[]).map((r)=>queueCard(r,"review")).join(""):`<div class="empty">No PRs awaiting review.</div>`;byId("ready").innerHTML=(b.ready||[]).length?(b.ready||[]).map(readyCard).join(""):`<div class="empty">No fresh agent-ready issues.</div>`;bindQueueActions();}',
      'function renderAll(){renderStats();ensureSelected();renderQueues();renderFocus();vscode.setState(state);}',
      'window.addEventListener("message",(e)=>{if(!e.data)return;if(e.data.type==="board"){state.board=e.data.board||{ready:[],active:[],review:[]};renderAll();}if(e.data.type==="detail"){state.detail=e.data.detail||null;renderFocus();vscode.setState(state);}});',
      'Array.from(document.querySelectorAll("[data-cmd]")).forEach((b)=>b.addEventListener("click",()=>send("command",{command:b.getAttribute("data-cmd")})));',
      'renderAll();',
      '</script></body></html>',
    ].join('\n');
  }
}

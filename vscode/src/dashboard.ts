import * as vscode from 'vscode';

// Mission Control = an agent KANBAN board (the convergent pattern across Vibe Kanban,
// Nimbalyst, Cline, Conductor): columns are lifecycle states and cards sort themselves by
// the worker's real state. Fed by `relay board --json` ({ready, active, review}).
// The worker LIST stays a native TreeView; this webview earns its place as the board the
// tree can't be. Best practice kept: --vscode-* variables, CSP + nonce, getState, a11y.

export interface Board { ready: any[]; active: any[]; review: any[]; }

function makeNonce(): string {
  const c = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let s = ''; for (let i = 0; i < 32; i++) { s += c.charAt(Math.floor(Math.random() * c.length)); }
  return s;
}

export class Dashboard {
  static current: Dashboard | undefined;
  private panel: vscode.WebviewPanel;

  static show(ctx: vscode.ExtensionContext, onReady: () => void): void {
    if (Dashboard.current) { Dashboard.current.panel.reveal(); onReady(); return; }
    const panel = vscode.window.createWebviewPanel(
      'relayDashboard', 'Relay Mission Control', vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: false });
    Dashboard.current = new Dashboard(panel, ctx);
    panel.onDidDispose(() => (Dashboard.current = undefined), null, ctx.subscriptions);
    onReady();
  }

  constructor(panel: vscode.WebviewPanel, ctx: vscode.ExtensionContext) {
    this.panel = panel;
    panel.webview.html = this.html();
    panel.webview.onDidReceiveMessage((m) => {
      if (m && m.type === 'command' && typeof m.command === 'string') {
        vscode.commands.executeCommand(`relay.${m.command}`, m.args);
      }
    }, null, ctx.subscriptions);
  }

  update(board: Board): void {
    this.panel.webview.postMessage({ type: 'board', board });
  }

  private html(): string {
    const n = makeNonce();
    const csp = `default-src 'none'; style-src 'nonce-${n}'; script-src 'nonce-${n}';`;
    return [
      '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
      `<meta http-equiv="Content-Security-Policy" content="${csp}">`,
      `<style nonce="${n}">`,
      'body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);font-size:var(--vscode-font-size);margin:0;padding:14px}',
      '.hdr{display:flex;align-items:center;gap:10px;margin-bottom:14px}',
      'h2{font-weight:500;font-size:15px;margin:0}',
      '.badge{background:var(--vscode-badge-background);color:var(--vscode-badge-foreground);border-radius:10px;padding:2px 9px;font-size:11px}',
      '.toolbar{margin-left:auto;display:flex;gap:6px}',
      '.btn{font-family:inherit;font-size:12px;border:none;border-radius:2px;padding:4px 11px;cursor:pointer;background:var(--vscode-button-background);color:var(--vscode-button-foreground)}',
      '.btn:hover{background:var(--vscode-button-hoverBackground)}',
      '.btn.sec{background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}',
      '.btn:focus-visible{outline:1px solid var(--vscode-focusBorder);outline-offset:2px}',
      '.cols{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;align-items:start}',
      '.col{min-width:0}',
      '.colh{display:flex;align-items:center;gap:7px;font-size:11px;letter-spacing:.04em;color:var(--vscode-descriptionForeground);padding:0 2px 8px;text-transform:uppercase}',
      '.count{background:var(--vscode-badge-background);color:var(--vscode-badge-foreground);border-radius:9px;padding:0 6px;font-size:10px}',
      '.card{background:var(--vscode-editorWidget-background);border:1px solid var(--vscode-widget-border,var(--vscode-panel-border));border-radius:5px;padding:9px 10px;margin-bottom:8px}',
      '.card.attn{border-color:var(--vscode-charts-red)}',
      '.t1{font-size:12.5px;color:var(--vscode-foreground);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.meta{display:flex;align-items:center;gap:6px;margin-top:6px;flex-wrap:wrap}',
      '.chip{font-size:10.5px;border-radius:9px;padding:1px 7px;background:var(--vscode-badge-background);color:var(--vscode-badge-foreground)}',
      '.chip.t2{background:var(--vscode-charts-purple);color:var(--vscode-editor-background)}',
      '.mut{color:var(--vscode-descriptionForeground);font-size:11px}',
      '.now{font-family:var(--vscode-editor-font-family);font-size:11px;color:var(--vscode-foreground);margin-top:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.mono{font-family:var(--vscode-editor-font-family)}',
      '.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:middle}',
      '.d-blue{background:var(--vscode-charts-blue)}.d-yellow{background:var(--vscode-charts-yellow)}',
      '.d-red{background:var(--vscode-charts-red)}.d-purple{background:var(--vscode-charts-purple)}',
      '.cardbtn{margin-top:8px;font-size:11px;border:none;border-radius:2px;padding:3px 9px;cursor:pointer;background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}',
      '.cardbtn:hover{background:var(--vscode-button-hoverBackground);color:var(--vscode-button-foreground)}',
      '.empty{color:var(--vscode-descriptionForeground);font-size:11px;padding:6px 2px}',
      '</style></head><body>',
      '<div class="hdr"><h2>Relay — Mission Control</h2><span class="badge" id="summary">…</span>',
      '<div class="toolbar" role="toolbar" aria-label="Relay actions">',
      '<button class="btn" data-cmd="pull" aria-label="Dispatch an issue">Dispatch…</button>',
      '<button class="btn sec" data-cmd="togglePause" aria-label="Pause or resume auto-dispatch">Pause / Resume</button>',
      '<button class="btn sec" data-cmd="refresh" aria-label="Refresh board">Refresh</button>',
      '</div></div>',
      '<div class="cols" id="cols" role="list" aria-label="Workflow board"><div class="empty">Loading…</div></div>',
      `<script nonce="${n}">`,
      'const vscode=acquireVsCodeApi();',
      'const root=document.getElementById("cols"),sum=document.getElementById("summary");',
      'function esc(s){return (s||"").replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c];});}',
      'function send(command,args){vscode.postMessage({type:"command",command:command,args:args});}',
      'function t2(t){return t==="2"?"<span class=\\"chip t2\\">tier-2</span>":"";}',
      'function readyCard(r){var lane=r.lane?("<span class=\\"chip\\">"+esc(r.lane)+"</span>"):"<span class=\\"chip\\">HOLD</span>";',
      ' return "<div class=\\"card\\"><div class=\\"t1\\">"+esc(r.title)+"</div><div class=\\"meta\\"><span class=\\"mut\\">"+esc(r.repo.split("/").pop())+"#"+esc(r.id)+"</span>"+t2(r.tier)+lane+"</div>'
        + '<button class=\\"cardbtn\\" data-act=\\"dispatch\\" data-id=\\""+esc(r.id)+"\\" data-repo=\\""+esc(r.repo)+"\\">Dispatch</button></div>";}',
      'function workerCard(w,attn){var C={running:"blue",rate_limited:"yellow",error:"red",held:"purple",paused:"yellow",review_requested:"purple",needs_decision:"red"};',
      ' return "<div class=\\"card"+(attn?" attn":"")+"\\"><div class=\\"t1 mono\\">"+esc(w.task)+"</div><div class=\\"meta\\"><span class=\\"mut\\">"+esc((w.repo||"").split("/").pop())+"</span><span class=\\"chip\\">"+esc(w.lane||"-")+"</span><span class=\\"mut\\"><span class=\\"dot d-"+(C[w.state]||"blue")+"\\"></span>"+esc(w.state)+"</span></div>"+(w.now?"<div class=\\"now\\">"+esc(w.now)+"</div>":"")+"<button class=\\"cardbtn\\" data-act=\\"peek\\" data-session=\\""+esc(w.session_id||"")+"\\">Peek</button></div>";}',
      'function reviewCard(p){return "<div class=\\"card\\"><div class=\\"t1\\">"+esc(p.title)+"</div><div class=\\"meta\\"><span class=\\"mut\\">"+esc((p.repo||"").split("/").pop())+"#"+esc(p.id)+"</span>"+t2(p.tier)+"</div>'
        + '<button class=\\"cardbtn\\" data-act=\\"open\\" data-url=\\""+esc(p.url)+"\\">"+(p.tier==="2"?"Read every line":"Review PR")+"</button></div>";}',
      'function col(name,count,inner){return "<div class=\\"col\\" role=\\"listitem\\"><div class=\\"colh\\">"+name+"<span class=\\"count\\">"+count+"</span></div>"+(inner||"<div class=\\"empty\\">—</div>")+"</div>";}',
      'function render(b){b=b||{ready:[],active:[],review:[]};',
      ' var working=b.active.filter(function(w){return w.state==="running";});',
      ' var waiting=b.active.filter(function(w){return w.state==="rate_limited"||w.state==="paused";});',
      ' var attn=b.active.filter(function(w){return w.state==="error"||w.state==="held"||w.state==="needs_decision"||w.state==="review_requested";});',
      ' sum.textContent=b.active.length+" active \\u00b7 "+b.review.length+" in review";',
      ' root.innerHTML=col("Ready",b.ready.length,b.ready.map(readyCard).join(""))',
      '  +col("Working",working.length,working.map(function(w){return workerCard(w,false);}).join(""))',
      '  +col("Waiting",waiting.length,waiting.map(function(w){return workerCard(w,false);}).join(""))',
      '  +col("Review",b.review.length+attn.length,attn.map(function(w){return workerCard(w,true);}).join("")+b.review.map(reviewCard).join(""));',
      ' Array.prototype.forEach.call(root.querySelectorAll("[data-act]"),function(el){el.addEventListener("click",function(){',
      '   var a=el.getAttribute("data-act");',
      '   if(a==="dispatch")send("dispatchId",{id:el.getAttribute("data-id"),repo:el.getAttribute("data-repo")});',
      '   else if(a==="open")send("openUrl",{url:el.getAttribute("data-url")});',
      '   else if(a==="peek")send("peek",{session_id:el.getAttribute("data-session")});});});}',
      'window.addEventListener("message",function(e){if(e.data&&e.data.type==="board"){vscode.setState(e.data.board);render(e.data.board);}});',
      'Array.prototype.forEach.call(document.querySelectorAll("[data-cmd]"),function(b){b.addEventListener("click",function(){send(b.getAttribute("data-cmd"));});});',
      'render(vscode.getState());',
      '</script></body></html>',
    ].join('\n');
  }
}

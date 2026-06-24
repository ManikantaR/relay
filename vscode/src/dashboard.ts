import * as vscode from 'vscode';
import { Worker } from './workersView';

// The one justified webview: the rich, at-a-glance "mission control". The worker LIST lives
// in the native TreeView (accessible + fast, per VS Code UX guidelines); this panel earns its
// place by showing the parallel picture the tree can't, with one-click controls.
// Built per 2026 best practice: no dead UI Toolkit, --vscode-* theme variables, CSP + nonce,
// getState (not retainContextWhenHidden), command buttons post back to the extension.

function makeNonce(): string {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let s = '';
  for (let i = 0; i < 32; i++) { s += chars.charAt(Math.floor(Math.random() * chars.length)); }
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
    panel.webview.html = this.html(panel.webview);
    // in-webview buttons -> run the same commands as the tree/palette (single source of truth)
    panel.webview.onDidReceiveMessage((m) => {
      if (m && m.type === 'command' && typeof m.command === 'string') {
        vscode.commands.executeCommand(`relay.${m.command}`);
      }
    }, null, ctx.subscriptions);
  }

  update(workers: Worker[]): void {
    this.panel.webview.postMessage({ type: 'workers', workers });
  }

  private html(_webview: vscode.Webview): string {
    const n = makeNonce();
    const csp = `default-src 'none'; style-src 'nonce-${n}'; script-src 'nonce-${n}';`;
    return [
      '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
      `<meta http-equiv="Content-Security-Policy" content="${csp}">`,
      `<style nonce="${n}">`,
      ':root{color-scheme:light dark}',
      'body{font-family:var(--vscode-font-family);color:var(--vscode-foreground);',
      '  font-size:var(--vscode-font-size);margin:0;padding:16px}',
      '.hdr{display:flex;align-items:center;gap:10px;margin-bottom:14px}',
      'h2{font-weight:500;font-size:15px;margin:0}',
      '.badge{background:var(--vscode-badge-background);color:var(--vscode-badge-foreground);',
      '  border-radius:10px;padding:2px 9px;font-size:11px}',
      '.toolbar{margin-left:auto;display:flex;gap:6px}',
      '.btn{font-family:inherit;font-size:12px;border:none;border-radius:2px;padding:4px 11px;',
      '  cursor:pointer;background:var(--vscode-button-background);color:var(--vscode-button-foreground)}',
      '.btn:hover{background:var(--vscode-button-hoverBackground)}',
      '.btn.sec{background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}',
      '.btn:focus-visible{outline:1px solid var(--vscode-focusBorder);outline-offset:2px}',
      '.row{display:grid;grid-template-columns:1.4fr 1fr .8fr 1.1fr 1.6fr;gap:10px;align-items:center;',
      '  padding:8px 4px;border-bottom:1px solid var(--vscode-panel-border);',
      '  font-family:var(--vscode-editor-font-family);font-size:12.5px}',
      '.row.head{color:var(--vscode-descriptionForeground);font-size:11px;letter-spacing:.04em;',
      '  font-family:var(--vscode-font-family)}',
      '.mut{color:var(--vscode-descriptionForeground)}',
      '.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;vertical-align:middle}',
      '.d-blue{background:var(--vscode-charts-blue)}.d-green{background:var(--vscode-charts-green)}',
      '.d-yellow{background:var(--vscode-charts-yellow)}.d-red{background:var(--vscode-charts-red)}',
      '.d-purple{background:var(--vscode-charts-purple)}.d-fg{background:var(--vscode-descriptionForeground)}',
      '.empty{color:var(--vscode-descriptionForeground);padding:18px 4px}',
      '.foot{margin-top:14px;color:var(--vscode-descriptionForeground);font-size:11.5px}',
      '</style></head><body>',
      '<div class="hdr"><h2>Relay — Mission Control</h2>',
      '<span class="badge" id="summary">…</span>',
      '<div class="toolbar" role="toolbar" aria-label="Relay actions">',
      '<button class="btn" data-cmd="pull" aria-label="Dispatch an issue">Dispatch…</button>',
      '<button class="btn sec" data-cmd="togglePause" aria-label="Pause or resume auto-dispatch">Pause / Resume</button>',
      '<button class="btn sec" data-cmd="refresh" aria-label="Refresh">Refresh</button>',
      '</div></div>',
      '<div id="rows" role="table" aria-label="Active workers"><div class="empty">Loading…</div></div>',
      '<div class="foot">Workers update live · act on a worker from the Relay sidebar (right-click).</div>',
      `<script nonce="${n}">`,
      'const vscode=acquireVsCodeApi();',
      'const rows=document.getElementById("rows"),sum=document.getElementById("summary");',
      'const C={PROGRESS:"blue",RATE_LIMITED:"yellow",ERROR:"red",HELD:"purple",DONE:"green",MISSING:"fg"};',
      'function esc(s){return (s||"").replace(/[&<>]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;"}[c];});}',
      'function render(ws){ws=ws||[];',
      ' var held=ws.filter(function(w){return w.state==="HELD";}).length;',
      ' sum.textContent=ws.length+" active"+(held?(" \\u00b7 "+held+" held"):"");',
      ' if(!ws.length){rows.innerHTML="<div class=\\"empty\\">No active workers.</div>";return;}',
      ' rows.innerHTML="<div class=\\"row head\\"><div>TASK</div><div>REPO</div><div>LANE</div><div>STATE</div><div>BRANCH</div></div>"',
      '  +ws.map(function(w){var repo=(w.repo||"").split("/").pop()||"-";',
      '   return "<div class=\\"row\\" role=\\"row\\"><div>"+esc(w.task)+"</div><div>"+esc(repo)+"</div><div>"+esc(w.lane||"-")',
      '   +"</div><div><span class=\\"dot d-"+(C[w.state]||"fg")+"\\"></span>"+esc(w.state)+"</div><div class=\\"mut\\">"+esc(w.branch||"")+"</div></div>";',
      '  }).join("");}',
      'window.addEventListener("message",function(e){if(e.data&&e.data.type==="workers"){vscode.setState(e.data.workers);render(e.data.workers);}});',
      'Array.prototype.forEach.call(document.querySelectorAll("[data-cmd]"),function(b){b.addEventListener("click",function(){vscode.postMessage({type:"command",command:b.getAttribute("data-cmd")});});});',
      'render(vscode.getState());',
      '</script></body></html>',
    ].join('\n');
  }
}

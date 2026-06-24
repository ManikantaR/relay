import * as vscode from 'vscode';
import { Worker } from './workersView';

// The live "mission control" webview — workers/lanes/states/repos, fed by status --json.
export class Dashboard {
  static current: Dashboard | undefined;
  private panel: vscode.WebviewPanel;

  static show(ctx: vscode.ExtensionContext, onReady: () => void): void {
    if (Dashboard.current) { Dashboard.current.panel.reveal(); onReady(); return; }
    const panel = vscode.window.createWebviewPanel(
      'relayDashboard', 'Relay Mission Control', vscode.ViewColumn.Active,
      { enableScripts: true, retainContextWhenHidden: true });
    Dashboard.current = new Dashboard(panel);
    panel.onDidDispose(() => (Dashboard.current = undefined), null, ctx.subscriptions);
    onReady();
  }

  constructor(panel: vscode.WebviewPanel) {
    this.panel = panel;
    panel.webview.html = this.html();
  }

  update(workers: Worker[]): void {
    this.panel.webview.postMessage({ type: 'workers', workers });
  }

  private html(): string {
    return `<!DOCTYPE html><html><head><meta charset="utf-8"><style>
      body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 14px; }
      h2 { font-weight: 500; font-size: 16px; margin: 0 0 14px; }
      .row { display:grid; grid-template-columns:170px 130px 90px 1fr 160px; gap:10px;
             align-items:center; padding:8px 0; border-bottom:1px solid var(--vscode-panel-border);
             font-family: var(--vscode-editor-font-family); font-size:12.5px; }
      .h { color: var(--vscode-descriptionForeground); font-size:11px; letter-spacing:.04em; }
      .pill { padding:2px 9px; border-radius:10px; font-size:11px;
              background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); }
      .empty { color: var(--vscode-descriptionForeground); padding:18px 0; }
      code { color: var(--vscode-descriptionForeground); }
    </style></head><body>
      <h2>Relay — workers in parallel</h2>
      <div id="rows"><div class="empty">waiting for status…</div></div>
      <script>
        const el = document.getElementById('rows');
        window.addEventListener('message', e => {
          if (!e.data || e.data.type !== 'workers') return;
          const ws = e.data.workers || [];
          if (!ws.length) { el.innerHTML = '<div class="empty">(no active workers)</div>'; return; }
          const head = '<div class="row h"><div>TASK</div><div>REPO</div><div>LANE</div><div>STATE</div><div>BRANCH</div></div>';
          el.innerHTML = head + ws.map(function(w){
            const repo = (w.repo||'').split('/').pop() || '-';
            return '<div class="row"><div>'+w.task+'</div><div>'+repo+'</div><div>'+(w.lane||'-')
              +'</div><div><span class="pill">'+w.state+'</span></div><div><code>'+(w.branch||'')+'</code></div></div>';
          }).join('');
        });
      </script>
    </body></html>`;
  }
}

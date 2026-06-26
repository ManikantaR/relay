import * as vscode from 'vscode';
import { runRelayJson } from './relay';

// Click-to-watch: a per-session panel that renders the session transcript and facts from the
// v2 runtime, polling `relay session|transcript|evidence`.
interface Peek {
  session_id: string; task_id: string; lane: string; state: string; role: string;
  repo: string; model: string; effort: string; review_round?: number;
}

function makeNonce(): string {
  const c = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
  let s = ''; for (let i = 0; i < 32; i++) { s += c.charAt(Math.floor(Math.random() * c.length)); }
  return s;
}

export class PeekPanel {
  private static panels = new Map<string, PeekPanel>();
  private timer?: ReturnType<typeof setInterval>;

  static show(ctx: vscode.ExtensionContext, sessionId: string): void {
    const existing = PeekPanel.panels.get(sessionId);
    if (existing) { existing.panel.reveal(); return; }
    const panel = vscode.window.createWebviewPanel(
      'relayPeek', `Peek · ${sessionId}`, vscode.ViewColumn.Active,
      {
        enableScripts: true, retainContextWhenHidden: false,
        localResourceRoots: [vscode.Uri.joinPath(ctx.extensionUri, 'media')],
      });
    new PeekPanel(ctx, panel, sessionId);
  }

  constructor(private ctx: vscode.ExtensionContext, private panel: vscode.WebviewPanel,
              private sessionId: string) {
    PeekPanel.panels.set(sessionId, this);
    panel.webview.html = this.html(panel.webview);
    panel.webview.onDidReceiveMessage((m) => {
      if (m && m.type === 'command') { vscode.commands.executeCommand(`relay.${m.command}`, m.args); }
    }, null, ctx.subscriptions);

    const poll = async () => {
      try {
        const p = await runRelayJson<Peek>(`session ${sessionId}`);
        const t = await runRelayJson<{ session_id: string; transcript: string }>(`transcript ${sessionId}`);
        const e = await runRelayJson<any>(`evidence ${sessionId}`);
        this.panel.webview.postMessage({ type: 'peek', peek: p, transcript: t.transcript || '', evidence: e || {} });
      } catch { /* keep last frame */ }
    };
    poll();
    this.timer = setInterval(poll, 2000);
    panel.onDidDispose(() => {
      if (this.timer) { clearInterval(this.timer); }
      PeekPanel.panels.delete(sessionId);
    }, null, ctx.subscriptions);
  }

  private html(webview: vscode.Webview): string {
    const n = makeNonce();
    const uri = (p: string) =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.ctx.extensionUri, 'media', 'xterm', p));
    const csp = `default-src 'none'; style-src ${webview.cspSource} 'nonce-${n}'; ` +
                `script-src ${webview.cspSource} 'nonce-${n}';`;
    return [
      '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">',
      `<meta http-equiv="Content-Security-Policy" content="${csp}">`,
      `<link rel="stylesheet" href="${uri('xterm.css')}">`,
      `<style nonce="${n}">`,
      'html,body{height:100%;margin:0;background:var(--vscode-editor-background);color:var(--vscode-foreground);font-family:var(--vscode-font-family)}',
      '.hdr{display:flex;align-items:center;gap:8px;padding:8px 12px;flex-wrap:wrap;border-bottom:1px solid var(--vscode-panel-border)}',
      '.facts{font-size:12px;color:var(--vscode-descriptionForeground)}',
      '.facts b{color:var(--vscode-foreground);font-weight:500}',
      '.now{font-family:var(--vscode-editor-font-family);font-size:12px;color:var(--vscode-foreground);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '.btn{margin-left:auto;display:flex;gap:6px}',
      'button{font-family:inherit;font-size:12px;border:none;border-radius:2px;padding:4px 10px;cursor:pointer;background:var(--vscode-button-secondaryBackground);color:var(--vscode-button-secondaryForeground)}',
      'button:hover{background:var(--vscode-button-hoverBackground);color:var(--vscode-button-foreground)}',
      '#term{position:absolute;top:42px;left:0;right:0;bottom:0;padding:6px 10px}',
      '</style></head><body>',
      '<div class="hdr"><span class="facts" id="facts">…</span><span class="now" id="now"></span>',
      '<span class="btn"><button data-cmd="viewDiff">View Diff</button>',
      '<button data-cmd="attach">Attach Terminal</button></span></div>',
      '<div id="term"></div>',
      `<script nonce="${n}" src="${uri('xterm.js')}"></script>`,
      `<script nonce="${n}">`,
      'const vscode=acquireVsCodeApi();',
      'const SID=' + JSON.stringify(this.sessionId) + ';',
      'const term=new Terminal({convertEol:true,fontSize:12,scrollback:8000,cursorBlink:false,',
      ' theme:{background:"#1e1e1e",foreground:"#d4d4d4"}});',
      'term.open(document.getElementById("term"));',
      'let shown="";',
      'const facts=document.getElementById("facts"),now=document.getElementById("now");',
      'window.addEventListener("message",function(e){if(!e.data||e.data.type!=="peek")return;var p=e.data.peek||{};var ev=e.data.evidence||{};',
      ' facts.innerHTML="<b>"+(p.task_id||p.session_id||"")+"</b> · "+(p.role||"-")+" · "+(p.state||"-")+" · "+(p.model||"-")+" · "+(ev.screenshots?ev.screenshots.length:0)+" shots";',
      ' now.textContent=(p.repo||"") + " · " + (p.lane||"-") + " · round " + (p.review_round||0);',
      ' var log=e.data.transcript||"";if(log===shown)return;',
      ' if(log.indexOf(shown)===0){term.write(log.slice(shown.length));}else{term.clear();term.write(log);}shown=log;});',
      'function send(c,a){vscode.postMessage({type:"command",command:c,args:a});}',
      'Array.prototype.forEach.call(document.querySelectorAll("[data-cmd]"),function(b){b.addEventListener("click",function(){',
      '  var c=b.getAttribute("data-cmd");',
      '  if(c==="viewDiff")send("viewDiff",{session_id:SID}); else if(c==="attach")send("attachTerminal",{session_id:SID});});});',
      '</script></body></html>',
    ].join('\n');
  }
}

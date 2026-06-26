import * as vscode from 'vscode';
import { WorkersProvider, Worker } from './workersView';
import { runRelay, runRelayJson, execPrefix } from './relay';
import { Dashboard, Board } from './dashboard';
import { PeekPanel } from './peekPanel';

function taskOf(arg: any): string | undefined {
  return typeof arg === 'string' ? arg : arg?.task || arg?.task_id;
}

function sessionOf(arg: any): string | undefined {
  return typeof arg === 'string' ? arg : arg?.session_id;
}

export function activate(ctx: vscode.ExtensionContext): void {
  const provider = new WorkersProvider();
  ctx.subscriptions.push(vscode.window.registerTreeDataProvider('relayWorkers', provider));

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.command = 'relay.openDashboard';
  ctx.subscriptions.push(status);

  // Fast, file-cheap: the tree + status bar (relay status reads disk).
  const refresh = async (): Promise<void> => {
    const ws = await provider.load();
    const held = ws.filter(w => w.state === 'held').length;
    status.text = `$(rocket) relay: ${ws.length} active${held ? ` · ${held} held` : ''}`;
    status.tooltip = 'Relay mission control';
    status.show();
  };

  // Slower, gh-backed: the kanban board (Ready/Review hit the board API).
  const refreshBoard = async (): Promise<void> => {
    if (!Dashboard.current) { return; }
    let b: Board = { ready: [], active: [], review: [] };
    try { b = (await runRelayJson<Board>('board')) ?? b; } catch { /* keep last */ }
    Dashboard.current.update(b);
  };

  const reg = (id: string, fn: (...a: any[]) => any) =>
    ctx.subscriptions.push(vscode.commands.registerCommand(id, fn));

  reg('relay.refresh', () => { refresh(); refreshBoard(); });
  reg('relay.openDashboard', () => Dashboard.show(ctx, () => { refresh(); refreshBoard(); }));

  const dispatch = async (id?: string, repo?: string): Promise<void> => {
    if (!id) { id = await vscode.window.showInputBox({ prompt: 'Issue id to dispatch' }); }
    if (!id) { return; }
    const lane = await vscode.window.showQuickPick(
      ['(auto)', 'claude', 'agy', 'copilot', 'codex'], { placeHolder: 'Lane' });
    const laneArg = lane && lane !== '(auto)' ? ` --lane ${lane}` : '';
    const repoArg = repo ? ` --repo ${repo}` : '';
    try {
      const out = await runRelay(`dispatch ${id}${repoArg}${laneArg}`);
      vscode.window.showInformationMessage(out.trim());
      refresh(); refreshBoard();
    } catch (e: any) { vscode.window.showErrorMessage(`dispatch: ${e.message}`); }
  };
  reg('relay.dispatch', () => dispatch());
  // card actions from the kanban webview
  reg('relay.dispatchId', (a: { id: string; repo?: string }) => dispatch(a?.id, a?.repo));
  reg('relay.openUrl', (a: { url: string }) => { if (a?.url) { vscode.env.openExternal(vscode.Uri.parse(a.url)); } });

  reg('relay.pull', async () => {
    let rows: any[] = [];
    try { rows = (await runRelayJson<any[]>('pull')) ?? []; }
    catch (e: any) { vscode.window.showErrorMessage(`relay pull: ${e.message}`); return; }
    if (!rows.length) { vscode.window.showInformationMessage('No agent-ready issues.'); return; }
    const pick = await vscode.window.showQuickPick(
      rows.map(r => ({
        label: `${r.repo}#${r.id}`,
        description: `tier-${r.tier} · ${r.lane || 'HOLD'} · ${r.title}`,
        r,
      })),
      { placeHolder: 'Dispatch which issue?' });
    if (pick) { await dispatch((pick as any).r.id, (pick as any).r.repo); }
  });

  reg('relay.killWorker', async (w: Worker) => {
    const taskId = w?.task_id;
    if (!taskId) { return; }
    const ok = await vscode.window.showWarningMessage(`Kill worker ${taskId}?`, { modal: true }, 'Kill');
    if (ok !== 'Kill') { return; }
    try { await runRelay(`kill ${taskId}`); } catch (e: any) { vscode.window.showErrorMessage(e.message); }
    refresh(); refreshBoard();
  });

  reg('relay.openPR', (w: Worker) => {
    if (w?.repo) { vscode.env.openExternal(vscode.Uri.parse(`https://github.com/${w.repo}/pulls`)); }
  });

  reg('relay.peek', (arg: any) => { const s = sessionOf(arg); if (s) { PeekPanel.show(ctx, s); } });

  reg('relay.viewDiff', async (arg: any) => {
    const s = sessionOf(arg);
    if (!s) { return; }
    let patch = '';
    try { patch = await runRelay(`session-diff ${s}`); } catch (e: any) { vscode.window.showErrorMessage(e.message); return; }
    const doc = await vscode.workspace.openTextDocument({
      content: patch.trim() || '(no changes yet)', language: 'diff',
    });
    vscode.window.showTextDocument(doc, { preview: true });
  });

  let paused = false;
  reg('relay.togglePause', async () => {
    try {
      await runRelay(paused ? 'resume' : 'pause');
      paused = !paused;
      vscode.window.showInformationMessage(`Relay auto-dispatch ${paused ? 'paused' : 'resumed'}.`);
    } catch (e: any) { vscode.window.showErrorMessage(e.message); }
  });

  reg('relay.refreshBoard', refreshBoard);

  reg('relay.attachTerminal', (w: Worker) => {
    const sessionId = w?.session_id;
    const taskId = w?.task_id || '';
    if (!sessionId) { return; }
    const t = vscode.window.createTerminal(`relay ${taskId || sessionId}`);
    const pfx = execPrefix();
    // attach to the worker's tmux window (local, or through the exec prefix for the NAS)
    if (taskId) {
      t.sendText(`${pfx} tmux attach -t relay \\; select-window -t ${taskId}`.trim());
    } else {
      t.sendText(`${pfx} tmux attach -t relay`.trim());
    }
    t.show();
  });

  reg('relay.requestCheckpoint', async (w: Worker) => {
    const sessionId = w?.session_id;
    if (!sessionId) { return; }
    try {
      await runRelay(`session-checkpoint ${sessionId}`);
      vscode.window.showInformationMessage(`Checkpoint requested for ${sessionId}.`);
    } catch (e: any) { vscode.window.showErrorMessage(e.message); }
  });

  reg('relay.refreshSession', async (w: Worker) => {
    const sessionId = w?.session_id;
    if (!sessionId) { return; }
    try {
      await runRelay(`session-refresh ${sessionId}`);
      vscode.window.showInformationMessage(`Refreshed ${sessionId}.`);
    } catch (e: any) { vscode.window.showErrorMessage(e.message); }
    refresh(); refreshBoard();
  });

  reg('relay.terminateSession', async (w: Worker) => {
    const sessionId = w?.session_id;
    if (!sessionId) { return; }
    const ok = await vscode.window.showWarningMessage(`Terminate session ${sessionId}?`, { modal: true }, 'Terminate');
    if (ok !== 'Terminate') { return; }
    try {
      await runRelay(`session-terminate ${sessionId}`);
    } catch (e: any) { vscode.window.showErrorMessage(e.message); }
    refresh(); refreshBoard();
  });

  refresh().catch(() => {});
  const sec = Math.max(2, vscode.workspace.getConfiguration('relay').get<number>('pollSeconds', 5));
  const fast = setInterval(() => refresh().catch(() => {}), sec * 1000);
  // the board hits the gh API — poll it slower, only while the dashboard is open
  const slow = setInterval(() => { if (Dashboard.current) { refreshBoard().catch(() => {}); } }, Math.max(15, sec * 4) * 1000);
  ctx.subscriptions.push({ dispose: () => { clearInterval(fast); clearInterval(slow); } });
}

export function deactivate(): void { /* no-op */ }

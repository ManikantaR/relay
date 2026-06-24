import * as vscode from 'vscode';
import { WorkersProvider, Worker } from './workersView';
import { runRelay, runRelayJson, execPrefix } from './relay';
import { Dashboard } from './dashboard';

export function activate(ctx: vscode.ExtensionContext): void {
  const provider = new WorkersProvider();
  ctx.subscriptions.push(vscode.window.registerTreeDataProvider('relayWorkers', provider));

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.command = 'relay.openDashboard';
  ctx.subscriptions.push(status);

  const refresh = async (): Promise<void> => {
    const ws = await provider.load();
    const held = ws.filter(w => w.state === 'HELD').length;
    status.text = `$(rocket) relay: ${ws.length} active${held ? ` · ${held} held` : ''}`;
    status.tooltip = 'Relay mission control';
    status.show();
    Dashboard.current?.update(ws);
  };

  const reg = (id: string, fn: (...a: any[]) => any) =>
    ctx.subscriptions.push(vscode.commands.registerCommand(id, fn));

  reg('relay.refresh', refresh);
  reg('relay.openDashboard', () => Dashboard.show(ctx, refresh));

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
      refresh();
    } catch (e: any) { vscode.window.showErrorMessage(`dispatch: ${e.message}`); }
  };
  reg('relay.dispatch', () => dispatch());

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
    if (!w?.task) { return; }
    const ok = await vscode.window.showWarningMessage(`Kill worker ${w.task}?`, { modal: true }, 'Kill');
    if (ok !== 'Kill') { return; }
    try { await runRelay(`kill ${w.task}`); } catch (e: any) { vscode.window.showErrorMessage(e.message); }
    refresh();
  });

  reg('relay.openPR', (w: Worker) => {
    if (w?.repo) { vscode.env.openExternal(vscode.Uri.parse(`https://github.com/${w.repo}/pulls`)); }
  });

  let paused = false;
  reg('relay.togglePause', async () => {
    try {
      await runRelay(paused ? 'resume' : 'pause');
      paused = !paused;
      vscode.window.showInformationMessage(`Relay auto-dispatch ${paused ? 'paused' : 'resumed'}.`);
    } catch (e: any) { vscode.window.showErrorMessage(e.message); }
  });

  reg('relay.attachTerminal', (w: Worker) => {
    if (!w?.task) { return; }
    const t = vscode.window.createTerminal(`relay ${w.task}`);
    const pfx = execPrefix();
    // attach to the worker's tmux window (local, or through the exec prefix for the NAS)
    t.sendText(`${pfx} tmux attach -t relay \\; select-window -t ${w.task}`.trim());
    t.show();
  });

  refresh().catch(() => {});
  const sec = Math.max(2, vscode.workspace.getConfiguration('relay').get<number>('pollSeconds', 5));
  const timer = setInterval(() => refresh().catch(() => {}), sec * 1000);
  ctx.subscriptions.push({ dispose: () => clearInterval(timer) });
}

export function deactivate(): void { /* no-op */ }

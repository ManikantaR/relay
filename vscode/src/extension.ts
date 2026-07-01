import * as vscode from 'vscode';
import { WorkersProvider, Worker } from './workersView';
import { runRelay, runRelayJson, execPrefix } from './relay';
import { Dashboard, Board, SessionDetail } from './dashboard';
import { PeekPanel } from './peekPanel';

function taskOf(arg: any): string | undefined {
  return typeof arg === 'string' ? arg : arg?.task || arg?.task_id;
}

function sessionOf(arg: any): string | undefined {
  return typeof arg === 'string' ? arg : arg?.session_id;
}

function parseDiffFiles(diff: string): Array<{ path: string; added: number; removed: number }> {
  const files: Array<{ path: string; added: number; removed: number }> = [];
  let current: { path: string; added: number; removed: number } | undefined;
  for (const line of diff.split('\n')) {
    const m = /^diff --git a\/(.+?) b\/(.+)$/.exec(line);
    if (m) {
      if (current) { files.push(current); }
      current = { path: m[2], added: 0, removed: 0 };
      continue;
    }
    if (!current) { continue; }
    if (line.startsWith('+++') || line.startsWith('---')) { continue; }
    if (line.startsWith('+')) { current.added += 1; continue; }
    if (line.startsWith('-')) { current.removed += 1; }
  }
  if (current) { files.push(current); }
  return files.slice(0, 12);
}

async function loadDashboardDetail(sessionId: string): Promise<SessionDetail | null> {
  try {
    const session = await runRelayJson<any>(`session ${sessionId}`);
    const timeline = await runRelayJson<any[]>(`timeline ${sessionId}`);
    const evidence = await runRelayJson<any>(`evidence ${sessionId}`);
    const transcript = await runRelayJson<{ session_id: string; transcript: string }>(`transcript ${sessionId}`);
    const diff = await runRelay(`session-diff ${sessionId}`);
    const transcriptPreview = (transcript.transcript || '')
      .split(/\r?\n/)
      .filter(Boolean)
      .slice(-8);
    return {
      session,
      timeline,
      evidence,
      transcriptPreview,
      changedFiles: parseDiffFiles(diff),
      diffAvailable: diff.trim().length > 0,
    };
  } catch {
    return null;
  }
}

interface RepoEntry { name: string; path: string; board?: string; }

export function activate(ctx: vscode.ExtensionContext): void {
  const provider = new WorkersProvider();
  ctx.subscriptions.push(vscode.window.registerTreeDataProvider('relayWorkers', provider));

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  status.command = 'relay.openDashboard';
  ctx.subscriptions.push(status);

  // The active repo scopes pull/dispatch/board to one entry in the relay repo registry.
  // Persisted per-workspace so the choice survives reloads. Click it to switch.
  const REPO_KEY = 'relay.activeRepo';
  const activeRepo = (): RepoEntry | undefined => ctx.workspaceState.get<RepoEntry>(REPO_KEY);
  const repoFlag = (): string => { const r = activeRepo(); return r ? ` --repo ${r.name}` : ''; };
  const repoStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
  repoStatus.command = 'relay.selectRepo';
  ctx.subscriptions.push(repoStatus);
  const updateRepoStatus = (): void => {
    const r = activeRepo();
    repoStatus.text = `$(repo) ${r ? r.name : 'all repos'}`;
    repoStatus.tooltip = r ? `Relay active repo: ${r.name} (${r.path}) — click to switch` : 'Relay: all registered repos — click to pick one';
    repoStatus.show();
  };
  updateRepoStatus();

  // Fast, file-cheap: the tree + status bar (relay status reads disk).
  const refresh = async (): Promise<void> => {
    const ws = await provider.load();
    const active = ws.filter(w => !['done', 'approved', 'terminated'].includes(w.state)).length;
    const held = ws.filter(w => w.state === 'held').length;
    const needs = ws.filter(w => w.state === 'needs_decision').length;
    status.text = `$(rocket) relay: ${active} active${needs ? ` · ${needs} needs decision` : held ? ` · ${held} held` : ''}`;
    status.tooltip = 'Relay mission control';
    status.show();
  };

  // Slower, gh-backed: the kanban board (Ready/Review hit the board API).
  const refreshBoard = async (): Promise<void> => {
    if (!Dashboard.current) { return; }
    let b: Board = { ready: [], active: [], review: [] };
    try { b = (await runRelayJson<Board>(`board${repoFlag()}`)) ?? b; } catch { /* keep last */ }
    Dashboard.current.update(b);
    Dashboard.current.setRepo(activeRepo()?.name || '');
  };

  const reg = (id: string, fn: (...a: any[]) => any) =>
    ctx.subscriptions.push(vscode.commands.registerCommand(id, fn));

  reg('relay.refresh', () => { refresh(); refreshBoard(); });
  const handleDashboardMessage = async (m: any): Promise<void> => {
    if (!m || typeof m.type !== 'string') { return; }
    if (m.type === 'command' && typeof m.command === 'string') {
      await vscode.commands.executeCommand(`relay.${m.command}`, m.args);
      return;
    }
    if (m.type === 'openUrl' && m.url) {
      vscode.env.openExternal(vscode.Uri.parse(m.url));
      return;
    }
    if (m.type === 'dispatchId') {
      await dispatch(m.id, m.repo);
      return;
    }
    if (m.type === 'selectSession' && m.sessionId && Dashboard.current) {
      Dashboard.current.updateDetail(await loadDashboardDetail(m.sessionId));
      return;
    }
    if (m.type === 'sessionCommand' && m.sessionId) {
      const arg = { session_id: m.sessionId, task_id: m.taskId || '' };
      await vscode.commands.executeCommand(`relay.${m.command}`, arg);
      if (Dashboard.current) {
        Dashboard.current.updateDetail(await loadDashboardDetail(m.sessionId));
      }
    }
  };

  reg('relay.openDashboard', () => Dashboard.show(ctx, handleDashboardMessage, () => { refresh(); refreshBoard(); }));

  const dispatch = async (id?: string, repo?: string): Promise<void> => {
    if (!id) { id = await vscode.window.showInputBox({ prompt: 'Issue id to dispatch' }); }
    if (!id) { return; }
    const lane = await vscode.window.showQuickPick(
      ['(auto)', 'claude', 'agy', 'copilot', 'codex'], { placeHolder: 'Lane' });
    const laneArg = lane && lane !== '(auto)' ? ` --lane ${lane}` : '';
    const scoped = repo || activeRepo()?.name;      // card repo wins; else the active repo
    const repoArg = scoped ? ` --repo ${scoped}` : '';
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

  reg('relay.selectRepo', async () => {
    let entries: RepoEntry[] = [];
    try { entries = (await runRelayJson<RepoEntry[]>('repo list')) ?? []; }
    catch (e: any) { vscode.window.showErrorMessage(`relay repo list: ${e.message}`); return; }
    if (!entries.length) {
      vscode.window.showWarningMessage('No repos registered. Add one with: relay repo add <owner/name> [path]');
      return;
    }
    const current = activeRepo()?.name;
    const items = [
      { label: '$(list-flat) All repos', description: 'pull & board across the whole registry', e: undefined as RepoEntry | undefined },
      ...entries.map(e => ({
        label: (e.name === current ? '$(check) ' : '$(repo) ') + e.name,
        description: e.path,
        e,
      })),
    ];
    const pick = await vscode.window.showQuickPick(items, {
      placeHolder: 'Select the active Relay repo (scopes pull, dispatch & board)',
      matchOnDescription: true,
    });
    if (!pick) { return; }
    await ctx.workspaceState.update(REPO_KEY, pick.e);
    updateRepoStatus();
    vscode.window.showInformationMessage(`Relay repo: ${pick.e ? pick.e.name : 'all repos'}`);
    refresh(); refreshBoard();
  });

  reg('relay.pull', async () => {
    let rows: any[] = [];
    try { rows = (await runRelayJson<any[]>(`pull${repoFlag()}`)) ?? []; }
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

  reg('relay.viewTimeline', async (arg: any) => {
    const s = sessionOf(arg);
    if (!s) { return; }
    let timeline = '';
    try { timeline = await runRelay(`timeline ${s}`); } catch (e: any) { vscode.window.showErrorMessage(e.message); return; }
    const doc = await vscode.workspace.openTextDocument({
      content: timeline.trim() || '(no timeline events)', language: 'plaintext',
    });
    vscode.window.showTextDocument(doc, { preview: true });
  });

  reg('relay.viewEvidence', async (arg: any) => {
    const s = sessionOf(arg);
    if (!s) { return; }
    let evidence = '';
    try { evidence = await runRelay(`evidence ${s}`); } catch (e: any) { vscode.window.showErrorMessage(e.message); return; }
    const doc = await vscode.workspace.openTextDocument({
      content: evidence.trim() || '(no evidence)', language: 'json',
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

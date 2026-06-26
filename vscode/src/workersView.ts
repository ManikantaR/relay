import * as vscode from 'vscode';
import { runRelayJson } from './relay';

// Mirrors relay's `sessions --json` row from the v2 session store.
export interface Worker {
  session_id: string; task_id: string; repo: string; role: string; lane: string;
  tier: string; state: string; provider: string; model: string; effort: string;
  review_round?: number; worktree_path?: string;
}

const ICON: Record<string, string> = {
  running: 'play-circle', rate_limited: 'sync', error: 'error',
  held: 'lock', done: 'pass', needs_decision: 'question', paused: 'debug-pause',
  review_requested: 'git-pull-request', approved: 'pass-filled', changes_requested: 'comment-discussion',
};

export class WorkersProvider implements vscode.TreeDataProvider<Worker> {
  private _onDidChange = new vscode.EventEmitter<Worker | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChange.event;
  workers: Worker[] = [];

  async load(): Promise<Worker[]> {
    try { this.workers = (await runRelayJson<Worker[]>('sessions')) ?? []; }
    catch { this.workers = []; }
    this._onDidChange.fire();
    return this.workers;
  }

  getChildren(): Worker[] { return this.workers; }

  getTreeItem(w: Worker): vscode.TreeItem {
    const repo = (w.repo || '').split('/').pop() || '-';
    const label = w.task_id || w.session_id;
    const it = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    it.description = `${repo} · ${w.role} · ${w.state}`;
    it.tooltip = new vscode.MarkdownString(
      `**${label}** · ${repo} · ${w.role} · ${w.state}\n\n` +
      `lane: \`${w.lane || '-'}\` · model: \`${w.model || '-'}\` · effort: \`${w.effort || '-'}\`\n\n` +
      `session: \`${w.session_id}\``);
    it.command = { command: 'relay.peek', title: 'Peek', arguments: [w] };   // click row -> peek
    it.iconPath = new vscode.ThemeIcon(ICON[w.state] || 'circle-outline');
    it.contextValue = w.state === 'held' ? 'worker-held' : 'worker';
    return it;
  }
}

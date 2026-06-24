import * as vscode from 'vscode';
import { runRelayJson } from './relay';

// Mirrors relay's `status --json` row (py/relay_cli.py::_workers).
export interface Worker {
  task: string; repo: string; issue: string; lane: string;
  tier: string; state: string; line: string; branch: string;
}

const ICON: Record<string, string> = {
  PROGRESS: 'play-circle', RATE_LIMITED: 'sync', ERROR: 'error',
  HELD: 'lock', DONE: 'pass', MISSING: 'question',
};

export class WorkersProvider implements vscode.TreeDataProvider<Worker> {
  private _onDidChange = new vscode.EventEmitter<Worker | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChange.event;
  workers: Worker[] = [];

  async load(): Promise<Worker[]> {
    try { this.workers = (await runRelayJson<Worker[]>('status')) ?? []; }
    catch { this.workers = []; }
    this._onDidChange.fire();
    return this.workers;
  }

  getChildren(): Worker[] { return this.workers; }

  getTreeItem(w: Worker): vscode.TreeItem {
    const repo = (w.repo || '').split('/').pop() || '-';
    const it = new vscode.TreeItem(w.task, vscode.TreeItemCollapsibleState.None);
    it.description = `${repo} · ${w.lane || '-'} · ${w.state}`;
    it.tooltip = new vscode.MarkdownString(`**${w.task}**\n\n${w.line}\n\n\`${w.branch}\``);
    it.iconPath = new vscode.ThemeIcon(ICON[w.state] || 'circle-outline');
    it.contextValue = w.state === 'HELD' ? 'worker-held' : 'worker';
    return it;
  }
}

import * as vscode from 'vscode';
import { runRelayJson } from './relay';

export interface Worker {
  session_id: string;
  task_id: string;
  repo: string;
  role: string;
  lane: string;
  tier: string;
  state: string;
  provider: string;
  model: string;
  effort: string;
  review_round?: number;
  worktree_path?: string;
}

type GroupKey = 'attention' | 'active' | 'done';
type Node = GroupNode | Worker;

interface GroupNode {
  kind: 'group';
  key: GroupKey;
  label: string;
  description: string;
  children: Worker[];
}

const ICON: Record<string, string> = {
  running: 'play-circle',
  rate_limited: 'sync',
  error: 'error',
  held: 'lock',
  done: 'pass',
  needs_decision: 'question',
  paused: 'debug-pause',
  review_requested: 'git-pull-request',
  approved: 'pass-filled',
  changes_requested: 'comment-discussion',
  terminated: 'circle-slash',
};

function repoOf(w: Worker): string {
  return (w.repo || '').split('/').pop() || '-';
}

function groupFor(w: Worker): GroupKey {
  if (['needs_decision', 'error', 'held'].includes(w.state)) { return 'attention'; }
  if (['done', 'terminated', 'approved'].includes(w.state)) { return 'done'; }
  return 'active';
}

function sortWorkers(rows: Worker[]): Worker[] {
  const rank: Record<string, number> = {
    needs_decision: 0,
    error: 1,
    held: 2,
    running: 3,
    review_requested: 4,
    changes_requested: 5,
    paused: 6,
    rate_limited: 7,
    done: 8,
    approved: 9,
    terminated: 10,
  };
  return rows.slice().sort((a, b) => {
    const ra = rank[a.state] ?? 99;
    const rb = rank[b.state] ?? 99;
    if (ra !== rb) { return ra - rb; }
    return (a.task_id || a.session_id).localeCompare(b.task_id || b.session_id);
  });
}

export class WorkersProvider implements vscode.TreeDataProvider<Node> {
  private _onDidChange = new vscode.EventEmitter<Node | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChange.event;
  workers: Worker[] = [];
  groups: GroupNode[] = [];

  async load(): Promise<Worker[]> {
    try { this.workers = sortWorkers((await runRelayJson<Worker[]>('sessions')) ?? []); }
    catch { this.workers = []; }
    this.groups = [
      { kind: 'group', key: 'attention', label: 'Needs Decision', description: '', children: [] },
      { kind: 'group', key: 'active', label: 'Active', description: '', children: [] },
      { kind: 'group', key: 'done', label: 'Done', description: '', children: [] },
    ];
    for (const w of this.workers) {
      this.groups.find(g => g.key === groupFor(w))?.children.push(w);
    }
    this.groups = this.groups
      .map(g => ({ ...g, description: `${g.children.length}`, children: sortWorkers(g.children) }))
      .filter(g => g.children.length > 0);
    this._onDidChange.fire();
    return this.workers;
  }

  getChildren(element?: Node): Node[] {
    if (!element) { return this.groups; }
    return 'kind' in element ? element.children : [];
  }

  getTreeItem(node: Node): vscode.TreeItem {
    if ('kind' in node) {
      const item = new vscode.TreeItem(node.label, vscode.TreeItemCollapsibleState.Expanded);
      item.description = node.description;
      item.contextValue = 'group';
      item.iconPath = new vscode.ThemeIcon(
        node.key === 'attention' ? 'warning' : node.key === 'active' ? 'pulse' : 'history',
      );
      return item;
    }

    const label = node.task_id || node.session_id;
    const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
    item.description = `${repoOf(node)} · ${node.state}`;
    item.tooltip = new vscode.MarkdownString(
      `**${label}** · ${repoOf(node)}\n\n` +
      `role: \`${node.role || '-'}\` · lane: \`${node.lane || '-'}\` · model: \`${node.model || '-'}\`\n\n` +
      `state: \`${node.state}\` · session: \`${node.session_id}\``,
    );
    item.command = { command: 'relay.peek', title: 'Peek', arguments: [node] };
    item.iconPath = new vscode.ThemeIcon(ICON[node.state] || 'circle-outline');
    item.contextValue = ['done', 'approved', 'terminated'].includes(node.state) ? 'worker-done' : 'worker';
    return item;
  }
}

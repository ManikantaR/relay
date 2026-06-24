import { exec } from 'child_process';
import * as vscode from 'vscode';

// The transport-agnostic seam: every relay invocation goes through `relay.execPrefix`.
//   ""                              -> run locally (or inside a Remote-SSH host = the NAS)
//   "ssh nas docker exec -i relay"  -> drive the NAS container from a local VS Code
function ctx(): { prefix: string; cwd: string } {
  const cfg = vscode.workspace.getConfiguration('relay');
  const cwd = cfg.get<string>('cwd') || vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
  return { prefix: cfg.get<string>('execPrefix', ''), cwd };
}

export function execPrefix(): string {
  return vscode.workspace.getConfiguration('relay').get<string>('execPrefix', '');
}

export function runRelay(args: string): Promise<string> {
  const { prefix, cwd } = ctx();
  const cmd = `${prefix} relay ${args}`.trim();
  return new Promise((resolve, reject) => {
    exec(cmd, { cwd, maxBuffer: 1 << 20 }, (err, stdout, stderr) => {
      if (err) { reject(new Error((stderr || err.message).trim())); } else { resolve(stdout); }
    });
  });
}

export async function runRelayJson<T>(args: string): Promise<T> {
  const out = await runRelay(`${args} --json`);
  return JSON.parse(out.trim() || 'null') as T;
}

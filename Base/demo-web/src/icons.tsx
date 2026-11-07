// Agent avatars use the model vendor's logo (provider-logos.tsx); roles and tools use lucide.
import {BookOpen, Bot, Bug, Compass, FilePen, FileText, FolderOpen, Image, MessageSquareText, Package, Play, ScrollText,
  Send, SquareTerminal, Terminal, Workflow, Wrench, type LucideIcon} from 'lucide-react';
import {VendorLogo} from './provider-logos';
import type {NodeKind} from './types';

/** The model vendor's logo, or a role icon for nodes that are not LLM agents (the runtime, the pipeline). */
export function Avatar({provider, kind}: {provider: string; kind: NodeKind}) {
  if (kind === 'run' || kind === 'executor') return <SquareTerminal size={18} strokeWidth={1.7} color="#4a4a4a"/>;
  if (kind === 'pipeline') return <Workflow size={18} strokeWidth={1.7} color="#2E7CF6"/>;
  return <VendorLogo vendor={provider} size={20}/>;
}

export const ROLE_ICONS: Record<NodeKind, LucideIcon> = {
  agent: Bot, pipeline: Workflow, planner: Compass, env: Package, executor: Terminal, answer: MessageSquareText,
  worker: Wrench, run: Play, debug: Bug,
};

export const TOOL_ICONS: Record<string, LucideIcon> = {
  run_shell: Terminal, read_file: FileText, list_dir: FolderOpen, write_file: FilePen, view_image: Image,
  read_log: ScrollText, read_skill: BookOpen, submit: Send, run_task: Play,
};

export function toolIcon(name: string) {
  const Icon = TOOL_ICONS[name] ?? Wrench;
  return <Icon size={14} strokeWidth={1.8}/>;
}

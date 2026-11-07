// 模型菜单里悬停某个模型时弹出的信息卡。
// 卡片外观照搬 21st Nav List Card（@arihantcodes_1f7b8c4d，demo 29949）：16px 圆角、三层细阴影、
// 顶部一行小号标题、下面一列 h-8 的圆角行（hover 时 spring 右移 2px）。行内容换成模型的五项信息，
// 行不可点击，所以按钮换成了普通行；悬停交给 Radix HoverCard。
// 用户要求：行前不放图标，只在「模型信息」标题前放一个；卡片保持原始大小（缩小后看不清）。
import type {ReactNode} from 'react';
import {HoverCard} from 'radix-ui';
import {motion} from 'motion/react';
import {Info} from 'lucide-react';

export type ModelInput = 'text' | 'image' | 'video' | 'audio';
export interface ModelInfo {name: string; inputs?: readonly ModelInput[]; reasoning?: boolean; contextWindow?: number}

const INPUT_LABEL: Record<ModelInput, string> = {text: 'Text', image: 'Image', video: 'Video', audio: 'Audio'};

/** 上下文长度：不到 1M 用 k；到了 1M 用 M（1M、2M、1.5M） */
export function formatContext(tokens?: number) {
  if (!tokens) return 'Unknown';
  if (tokens >= 1_000_000) return `${Number((tokens / 1_000_000).toFixed(1))}M`;
  return `${Math.round(tokens / 1000)}k`;
}

function Row({label, value}: {label: string; value: string}) {
  return (
    <li>
      <motion.span
        whileHover={{x: 2}}
        transition={{type: 'spring', bounce: 0.4, duration: 0.3}}
        className="flex h-8 items-center gap-2 rounded-full px-2.5 transition-colors hover:bg-neutral-100 dark:hover:bg-neutral-900"
      >
        <span className="shrink-0 text-sm leading-5 text-foreground/70">{label}</span>
        <span className="ml-auto truncate pl-3 text-sm leading-5 text-foreground">{value}</span>
      </motion.span>
    </li>
  );
}

export function ModelInfoCard({model, provider}: {model: ModelInfo; provider: string}) {
  const inputs = (model.inputs?.length ? model.inputs : (['text'] as const)).map((i) => INPUT_LABEL[i] ?? i).join(' / ');
  return (
    <div className="w-[248px] rounded-[16px] bg-white pb-2 pt-4 shadow-[0_0_0_1px_rgba(10,10,10,0.05),0_1px_3px_0_rgba(0,0,0,0.1),0_1px_2px_-1px_rgba(0,0,0,0.1)] dark:bg-neutral-950 dark:shadow-[0_0_0_1px_rgba(255,255,255,0.12),0_1px_3px_0_rgba(0,0,0,0.5)]">
      <p className="flex items-center gap-1.5 px-5 text-xs font-medium leading-4 text-foreground/70"><Info className="h-3.5 w-3.5"/>Model info</p>
      <ul className="mt-2 space-y-1 px-2">
        <Row label="Model" value={model.name}/>
        <Row label="Provider" value={provider}/>
        <Row label="Input" value={inputs}/>
        <Row label="Reasoning" value={model.reasoning ? 'Yes' : 'No'}/>
        <Row label="Context" value={formatContext(model.contextWindow)}/>
      </ul>
    </div>
  );
}

/** 包住模型行：悬停 400ms 后在右侧弹出信息卡 */
export function ModelInfoHover({model, provider, children}: {model: ModelInfo; provider: string; children: ReactNode}) {
  return (
    <HoverCard.Root openDelay={400} closeDelay={80}>
      <HoverCard.Trigger asChild>{children}</HoverCard.Trigger>
      <HoverCard.Portal>
        <HoverCard.Content side="right" align="start" sideOffset={14} collisionPadding={12} className="z-[120] outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95">
          <ModelInfoCard model={model} provider={provider}/>
        </HoverCard.Content>
      </HoverCard.Portal>
    </HoverCard.Root>
  );
}

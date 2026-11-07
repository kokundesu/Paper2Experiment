// 来源：21st Reasoning Effort，@syeddhasnainn，demo 36560。
// 改动：本地 cn、中文状态；levels 接入各模型实际档位；向上浮层/z60 适配嵌套 Model Picker。原布局、Solar 图标、Base UI Slider 与动效数值保留。
'use client'

import ChevronDownIcon from '@solar-icons/react/arrows/AltArrowDown'
import ChevronRightIcon from '@solar-icons/react/arrows/AltArrowRight'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import * as React from 'react'
import { useState } from 'react'
import { Popover as PopoverPrimitive } from '@base-ui/react/popover'
import { cn } from '@/lib/utils'
import { Slider as SliderPrimitive } from '@base-ui/react/slider'

function Popover({ ...props }: PopoverPrimitive.Root.Props) {
  return <PopoverPrimitive.Root data-slot="popover" {...props} />
}

function PopoverTrigger({ ...props }: PopoverPrimitive.Trigger.Props) {
  return <PopoverPrimitive.Trigger data-slot="popover-trigger" {...props} />
}

function PopoverContent({
  className,
  align = 'center',
  alignOffset = 0,
  side = 'top',
  sideOffset = 4,
  ...props
}: PopoverPrimitive.Popup.Props &
  Pick<PopoverPrimitive.Positioner.Props, 'align' | 'alignOffset' | 'side' | 'sideOffset'>) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Positioner
        align={align}
        alignOffset={alignOffset}
        side={side}
        sideOffset={sideOffset}
        className="isolate z-[60]"
      >
        <PopoverPrimitive.Popup
          data-slot="popover-content"
          data-reasoning-layer=""
          className={cn(
            'z-50 flex w-72 origin-(--transform-origin) flex-col gap-2.5 rounded-[16px] bg-popover p-2.5 text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden duration-100 data-[side=bottom]:slide-in-from-top-2 data-[side=inline-end]:slide-in-from-left-2 data-[side=inline-start]:slide-in-from-right-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95',
            className,
          )}
          {...props}
        />
      </PopoverPrimitive.Positioner>
    </PopoverPrimitive.Portal>
  )
}

function PopoverHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      data-slot="popover-header"
      className={cn('flex flex-col gap-0.5 text-sm', className)}
      {...props}
    />
  )
}

function PopoverTitle({ className, ...props }: PopoverPrimitive.Title.Props) {
  return (
    <PopoverPrimitive.Title
      data-slot="popover-title"
      className={cn('font-medium', className)}
      {...props}
    />
  )
}

function PopoverDescription({ className, ...props }: PopoverPrimitive.Description.Props) {
  return (
    <PopoverPrimitive.Description
      data-slot="popover-description"
      className={cn('text-muted-foreground', className)}
      {...props}
    />
  )
}

function Slider({
  className,
  defaultValue,
  value,
  min = 0,
  max = 100,
  ...props
}: SliderPrimitive.Root.Props) {
  const _values = Array.isArray(value)
    ? value
    : Array.isArray(defaultValue)
      ? defaultValue
      : [min, max]

  return (
    <SliderPrimitive.Root
      className={cn('data-horizontal:w-full data-vertical:h-full', className)}
      data-slot="slider"
      defaultValue={defaultValue}
      value={value}
      min={min}
      max={max}
      thumbAlignment="edge"
      {...props}
    >
      <SliderPrimitive.Control className="relative flex w-full touch-none items-center select-none data-disabled:opacity-50 data-vertical:h-full data-vertical:min-h-40 data-vertical:w-auto data-vertical:flex-col">
        <SliderPrimitive.Track
          data-slot="slider-track"
          className="relative grow overflow-hidden rounded-full bg-muted select-none data-horizontal:h-1 data-horizontal:w-full data-vertical:h-full data-vertical:w-1"
        >
          <SliderPrimitive.Indicator
            data-slot="slider-range"
            className="bg-primary select-none data-horizontal:h-full data-vertical:w-full"
          />
        </SliderPrimitive.Track>
        {Array.from({ length: _values.length }, (_, index) => (
          <SliderPrimitive.Thumb
            data-slot="slider-thumb"
            key={index}
            className="relative block size-3 shrink-0 rounded-full border border-ring bg-white ring-ring/50 transition-[color,box-shadow] select-none after:absolute after:-inset-2 hover:ring-3 focus-visible:ring-3 focus-visible:outline-hidden active:ring-3 disabled:pointer-events-none disabled:opacity-50"
          />
        ))}
      </SliderPrimitive.Control>
    </SliderPrimitive.Root>
  )
}

const effortLevels = ['Instant', 'Medium', 'High', 'Extra High', 'Pro'] as const

interface ReasoningEffortProps {
  className?: string
  onChange?: (value: number) => void
  value: number
  levels?: readonly string[]
}

function ReasoningEffort({ className, onChange, value, levels = effortLevels }: ReasoningEffortProps) {
  const effortLevels = levels;
  const selectedLevel = Math.min(effortLevels.length - 1, Math.max(0, Math.round(value)))
  const [isOpen, setIsOpen] = useState(false)
  const [draftLevel, setDraftLevel] = useState(selectedLevel)
  const reducedMotion = useReducedMotion()
  const textMotion = reducedMotion
    ? { duration: 0 }
    : { duration: 0.16, ease: [0.23, 1, 0.32, 1] as const }

  function handleOpenChange(open: boolean) {
    if (open) setDraftLevel(selectedLevel)
    else if (draftLevel !== selectedLevel) onChange?.(draftLevel)

    setIsOpen(open)
  }

  return (
    <Popover onOpenChange={handleOpenChange} open={isOpen}>
      <PopoverTrigger
        aria-label="Thinking effort"
        className={className}
        render={
          <button
            className="inline-flex h-9 items-center gap-1.5 rounded-full bg-muted px-3 font-sans text-sm font-[450] tracking-[-0.05px] text-muted-foreground transition-[background-color,scale] duration-150 hover:bg-muted/80 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none active:scale-[0.97]"
            type="button"
          >
            <span className="relative grid justify-items-center">
              {['Thinking effort', ...effortLevels].map((label) => (
                <span aria-hidden="true" className="invisible col-start-1 row-start-1" key={label}>
                  {label}
                </span>
              ))}
              <AnimatePresence initial={false} mode="popLayout">
                <motion.span
                  animate={{ filter: 'blur(0px)', opacity: 1, transform: 'translateY(0px)' }}
                  className="col-start-1 row-start-1"
                  exit={{ filter: 'blur(2px)', opacity: 0, transform: 'translateY(2px)' }}
                  initial={{ filter: 'blur(2px)', opacity: 0, transform: 'translateY(-2px)' }}
                  key={isOpen ? 'open' : effortLevels[selectedLevel]}
                  transition={textMotion}
                >
                  {isOpen ? 'Thinking effort' : effortLevels[selectedLevel]}
                </motion.span>
              </AnimatePresence>
            </span>
            <motion.span
              animate={{ transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}
              className="flex"
              transition={textMotion}
            >
              <ChevronDownIcon weight="Linear" className="size-3.5 text-muted-foreground" />
            </motion.span>
          </button>
        }
      />
      <PopoverContent
        align="end"
        className="w-65 rounded-[16px] border-0 bg-card p-2.5 font-sans text-sm font-[450] tracking-[-0.05px] text-muted-foreground shadow-card ring-0"
      >
        <motion.div
          animate={{ opacity: 1, transform: 'translateY(0px) scale(1)' }}
          initial={
            reducedMotion ? false : { opacity: 0, transform: 'translateY(-3px) scale(0.98)' }
          }
          transition={textMotion}
        >
          <div className="flex items-center justify-center gap-1 card-heading">
            <AnimatePresence initial={false} mode="popLayout">
              <motion.span
                animate={{ filter: 'blur(0px)', opacity: 1, transform: 'translateY(0px)' }}
                exit={{ filter: 'blur(2px)', opacity: 0, transform: 'translateY(2px)' }}
                initial={{ filter: 'blur(2px)', opacity: 0, transform: 'translateY(-2px)' }}
                key={effortLevels[draftLevel]}
                transition={textMotion}
              >
                {effortLevels[draftLevel]}
              </motion.span>
            </AnimatePresence>
            <ChevronRightIcon weight="Linear" className="size-3.5 text-muted-foreground" />
          </div>
          <div className="relative mx-3.5 mt-1">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute -inset-x-3.5 top-1/2 h-6 -translate-y-1/2 overflow-hidden rounded-full bg-foreground/10"
            >
              <div className="absolute inset-y-0 right-3.5 left-3.5">
                <motion.div
                  animate={{
                    transform: `translateX(${(draftLevel / (effortLevels.length - 1) - 1) * 50}%)`,
                  }}
                  className="absolute inset-y-0 right-0 w-[200%] bg-blue-500"
                  initial={false}
                  transition={textMotion}
                />
              </div>
            </div>
            <motion.div
              aria-hidden="true"
              animate={{
                transform: `translateX(${(draftLevel / (effortLevels.length - 1)) * 100}%)`,
              }}
              className="pointer-events-none absolute inset-x-0 top-1/2 z-30"
              initial={false}
              transition={textMotion}
            >
              <span className="absolute top-0 left-0 size-7 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow-md" />
            </motion.div>
            <div className="pointer-events-none absolute inset-x-0 top-1/2 z-20">
              {effortLevels.map((level, index) => (
                <span
                  aria-hidden="true"
                  className={cn(
                    'absolute size-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground/25 transition-colors duration-150',
                    index < draftLevel && 'bg-primary-foreground/45',
                    index === draftLevel && 'opacity-0',
                  )}
                  key={level}
                  style={{ left: `${(index / (effortLevels.length - 1)) * 100}%` }}
                />
              ))}
            </div>
            <Slider
              aria-label={`Thinking effort: ${effortLevels[draftLevel]}, ${draftLevel + 1} of ${effortLevels.length}`}
              className="*:py-1 [&_[data-slot=slider-range]]:bg-transparent [&_[data-slot=slider-thumb]]:z-30 [&_[data-slot=slider-thumb]]:size-7 [&_[data-slot=slider-thumb]]:border-0 [&_[data-slot=slider-thumb]]:bg-transparent [&_[data-slot=slider-thumb]]:shadow-none [&_[data-slot=slider-thumb]]:!ring-0 [&_[data-slot=slider-thumb]]:!outline-none [&_[data-slot=slider-thumb]]:after:hidden [&_[data-slot=slider-track]]:h-6 [&_[data-slot=slider-track]]:bg-transparent"
              max={effortLevels.length - 1}
              min={0}
              onClick={(event) => {
                if (event.detail === 0) return

                const { left, width } = event.currentTarget.getBoundingClientRect()
                const position = Math.min(1, Math.max(0, (event.clientX - left) / width))
                setDraftLevel(Math.round(position * (effortLevels.length - 1)))
              }}
              onValueChange={(value) => setDraftLevel(Array.isArray(value) ? value[0] : value)}
              step={1}
              value={[draftLevel]}
            />
          </div>
        </motion.div>
      </PopoverContent>
    </Popover>
  )
}

export { ReasoningEffort, effortLevels }
export type { ReasoningEffortProps }
export default ReasoningEffort


// C04：按用户要求直接嵌入原拖动条；移除 Popover 与二次入口，即时提交档位。
export function ReasoningEffortTrack({className, value, onChange, levels = effortLevels}: ReasoningEffortProps) {
  const effortLevels = levels;
  const draftLevel = Math.max(0, Math.min(levels.length - 1, value));
  const setDraftLevel = (next: number) => onChange?.(next);
  const reducedMotion = useReducedMotion();
  const textMotion = reducedMotion ? {duration: 0} : {duration: 0.16, ease: [0.23,1,0.32,1] as const};
  return (
        <motion.div className={cn("w-full py-3", className)}
          animate={{ opacity: 1, transform: 'translateY(0px) scale(1)' }}
          initial={
            reducedMotion ? false : { opacity: 0, transform: 'translateY(-3px) scale(0.98)' }
          }
          transition={textMotion}
        >
          <div className="relative mx-3.5 mt-1">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute -inset-x-3.5 top-1/2 h-6 -translate-y-1/2 overflow-hidden rounded-full bg-foreground/10"
            >
              <div className="absolute inset-y-0 right-3.5 left-3.5">
                <motion.div
                  animate={{
                    transform: `translateX(${(draftLevel / (effortLevels.length - 1) - 1) * 50}%)`,
                  }}
                  className="absolute inset-y-0 right-0 w-[200%] bg-blue-500"
                  initial={false}
                  transition={textMotion}
                />
              </div>
            </div>
            <motion.div
              aria-hidden="true"
              animate={{
                transform: `translateX(${(draftLevel / (effortLevels.length - 1)) * 100}%)`,
              }}
              className="pointer-events-none absolute inset-x-0 top-1/2 z-30"
              initial={false}
              transition={textMotion}
            >
              <span className="absolute top-0 left-0 size-7 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow-md" />
            </motion.div>
            <div className="pointer-events-none absolute inset-x-0 top-1/2 z-20">
              {effortLevels.map((level, index) => (
                <span
                  aria-hidden="true"
                  className={cn(
                    'absolute size-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground/25 transition-colors duration-150',
                    index < draftLevel && 'bg-primary-foreground/45',
                    index === draftLevel && 'opacity-0',
                  )}
                  key={level}
                  style={{ left: `${(index / (effortLevels.length - 1)) * 100}%` }}
                />
              ))}
            </div>
            <Slider
              aria-label={`Thinking effort: ${effortLevels[draftLevel]}, ${draftLevel + 1} of ${effortLevels.length}`}
              className="*:py-1 [&_[data-slot=slider-range]]:bg-transparent [&_[data-slot=slider-thumb]]:z-30 [&_[data-slot=slider-thumb]]:size-7 [&_[data-slot=slider-thumb]]:border-0 [&_[data-slot=slider-thumb]]:bg-transparent [&_[data-slot=slider-thumb]]:shadow-none [&_[data-slot=slider-thumb]]:!ring-0 [&_[data-slot=slider-thumb]]:!outline-none [&_[data-slot=slider-thumb]]:after:hidden [&_[data-slot=slider-track]]:h-6 [&_[data-slot=slider-track]]:bg-transparent"
              max={effortLevels.length - 1}
              min={0}
              onClick={(event) => {
                if (event.detail === 0) return

                const { left, width } = event.currentTarget.getBoundingClientRect()
                const position = Math.min(1, Math.max(0, (event.clientX - left) / width))
                setDraftLevel(Math.round(position * (effortLevels.length - 1)))
              }}
              onValueChange={(value) => setDraftLevel(Array.isArray(value) ? value[0] : value)}
              step={1}
              value={[draftLevel]}
            />
          </div>
        </motion.div>
  );
}

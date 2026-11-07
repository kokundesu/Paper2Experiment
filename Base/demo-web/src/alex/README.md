Components reused from Alex (`~/Documents/Projects/Alex/apps/web/src`), at the same relative paths so their imports
work unchanged (`@/` is `modules/chat`, see `vite.config.ts`):

- `modules/chat/components/ui/model-picker.tsx`, `reasoning-effort.tsx`: the model picker in the message box
- `modules/chat/components/ui/loader.tsx`, `shining-text.tsx`: the "thinking" row (newton loader + shining text)
- `modules/chat/lib/utils.ts`, `ease.ts`, `lib/model-info-card.tsx`: what those import
- `theme.css`: Alex's `theme.css` plus the parts of its `styles.css` these components rely on (Tailwind, the `@theme`
  mapping, popover and model-picker animations, `.assistant-avatar`)

The only change is the visible text, translated to English (the demo's language); code comments are Alex's.

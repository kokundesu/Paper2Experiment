// The page's language (English or Chinese), chosen in the top bar and remembered in the browser. Every component reads
// it with useLang(); text is written in both languages where it is used, as L('English', '中文'), so a translation sits
// next to the text it translates. Content that comes from the server (tasks, agent steps, errors) stays as written.
import {createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode} from 'react';

export type Lang = 'en' | 'zh';
const KEY = 'p2e-lang';

function initial(): Lang {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === 'en' || saved === 'zh') return saved;
  } catch { /* private mode */ }
  return typeof navigator !== 'undefined' && /^zh\b/i.test(navigator.language) ? 'zh' : 'en';
}

type Ctx = {lang: Lang; setLang: (l: Lang) => void; L: <T>(en: T, zh: T) => T};
const LangContext = createContext<Ctx>({lang: 'en', setLang: () => undefined, L: en => en});

export function LangProvider({children}: {children: ReactNode}) {
  const [lang, setLangState] = useState<Lang>(initial);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try { localStorage.setItem(KEY, l); } catch { /* private mode */ }
  }, []);
  useEffect(() => { document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en'; }, [lang]);
  const value = useMemo<Ctx>(() => ({lang, setLang, L: (en, zh) => lang === 'zh' ? zh : en}), [lang, setLang]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

/** The current language, its setter, and L(en, zh), which returns the text in the current language. */
export const useLang = () => useContext(LangContext);

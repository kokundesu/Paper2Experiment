import {createRoot} from 'react-dom/client';
import {App} from './App';
import {ErrorBoundary} from './ErrorBoundary';
import {Gate} from './Gate';
import {LangProvider} from './i18n';
import './alex/theme.css';
import './app.css';

createRoot(document.getElementById('root')!).render(<ErrorBoundary><LangProvider><Gate><App/></Gate></LangProvider></ErrorBoundary>);

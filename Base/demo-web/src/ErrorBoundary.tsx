// A render error must not leave a blank page: show the error and a way back to an empty chat.
import {Component, type ReactNode} from 'react';

type State = {error: Error | null};

export class ErrorBoundary extends Component<{children: ReactNode}, State> {
  state: State = {error: null};

  static getDerivedStateFromError(error: Error): State {
    return {error};
  }

  componentDidCatch(error: Error, info: {componentStack?: string | null}) {
    console.error('Paper2Exp demo crashed', error, info.componentStack);
  }

  render() {
    const {error} = this.state;
    if (!error) return this.props.children;
    return <div className="crash">
      <h1>The page hit an error</h1>
      <p>Copy the message below and send it along; “Start over” returns to an empty chat.</p>
      <pre>{String(error.stack || error.message || error)}</pre>
      <div className="row">
        <button type="button" className="btn primary sm" onClick={() => { window.location.hash = ''; window.location.reload(); }}>Start over</button>
        <button type="button" className="btn ghost sm" onClick={() => this.setState({error: null})}>Try again</button>
      </div>
    </div>;
  }
}

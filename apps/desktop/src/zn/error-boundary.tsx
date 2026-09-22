import { Component, type ReactNode } from 'react'

type Props = {
  children: ReactNode
}

type State = {
  failed: boolean
}

export class ZnDesktopErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  render() {
    if (!this.state.failed) return this.props.children

    return (
      <main className="zn-render-fallback" role="alert">
        <section className="zn-render-fallback-card">
          <span className="zn-eyebrow">ZN desktop</span>
          <h1>ZN needs to reload this view</h1>
          <p>
            The desktop view stopped rendering. Durable Work lives outside this renderer, so reloading reconnects to the same ZN state rather than starting another task. Text you had not sent may need to be entered again.
          </p>
          <button className="zn-primary" type="button" onClick={() => window.location.reload()}>
            Reload ZN
          </button>
        </section>
      </main>
    )
  }
}

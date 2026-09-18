// PanelHeader — the shared header bar for the app's main panels (Basket, Meal Planner).
// This is the design system anchor: both panels render through it so their headers
// can never drift apart. It's purely presentational — a big Nighty title, a muted
// subtitle beside it, and a right-side slot for the panel's primary action.
export default function PanelHeader({ title, subtitle, children }) {
  return (
    <header className="flex shrink-0 items-center justify-between gap-3 border-b border-bp-jambalaya/10 bg-bp-linen/70 px-5 py-3">
      <div className="flex items-baseline gap-3">
        <div className="font-['Nighty'] text-[2.75rem] leading-none text-bp-jambalaya">{title}</div>
        {subtitle && <div className="text-sm text-bp-domino">{subtitle}</div>}
      </div>

      {children && <div className="flex items-center gap-3">{children}</div>}
    </header>
  );
}

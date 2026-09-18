import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Renders an assistant message as Markdown. Claude/CLI agents emit Markdown
// (not HTML), so we parse it into real elements instead of showing raw `**`.
// react-markdown is XSS-safe by default (no dangerouslySetInnerHTML), and
// remark-gfm adds tables, strikethrough, task lists, and autolinks.
//
// The `components` map below styles ONLY the tags Claude actually sends, using
// the app's Boppai brand palette (flamingo/jambalaya/domino on linen).
// Anything not listed falls
// back to the plain HTML tag. Kept small on purpose: rich stuff (cards, big
// lists) is planned for a future canvas pane, so chat needs only light styling.
const components = {
  // Text + spacing
  p: (props) => <p className="mb-2 leading-relaxed last:mb-0" {...props} />,
  strong: (props) => <strong className="font-semibold" {...props} />,
  em: (props) => <em className="italic" {...props} />,
  del: (props) => <del className="line-through opacity-70" {...props} />,

  // Headings (h4–h6 are rare; they fall back to the default tag)
  h1: (props) => <h1 className="mb-2 mt-1 text-base font-semibold" {...props} />,
  h2: (props) => <h2 className="mb-2 mt-1 text-base font-semibold" {...props} />,
  h3: (props) => <h3 className="mb-1.5 mt-1 text-sm font-semibold" {...props} />,

  // Lists — Tailwind resets bullets/numbers, so we add them back
  ul: (props) => <ul className="mb-2 list-disc space-y-0.5 pl-5 last:mb-0" {...props} />,
  ol: (props) => <ol className="mb-2 list-decimal space-y-0.5 pl-5 last:mb-0" {...props} />,
  li: (props) => <li className="leading-relaxed" {...props} />,

  // Links — open in a new tab, and never leak the referrer
  a: (props) => (
    <a
      className="text-bp-flamingo underline underline-offset-2 hover:text-bp-jambalaya"
      target="_blank"
      rel="noopener noreferrer"
      {...props}
    />
  ),

  // Inline code → soft brown-tinted pill
  code: (props) => (
    <code className="rounded bg-bp-jambalaya/8 px-1 py-0.5 text-[13px] font-mono text-bp-jambalaya" {...props} />
  ),
  // Code block wrapper → brown-tinted rounded box that scrolls sideways instead
  // of breaking the layout. (react-markdown puts a <code> inside this <pre>.)
  pre: (props) => (
    <pre
      className="mb-2 overflow-x-auto rounded-lg bg-bp-jambalaya/8 p-3 text-[13px] leading-relaxed last:mb-0 [&_code]:bg-transparent [&_code]:p-0"
      {...props}
    />
  ),

  // Quotes + dividers
  blockquote: (props) => (
    <blockquote className="my-2 border-l-2 border-bp-geraldine pl-3 text-bp-domino italic" {...props} />
  ),
  hr: () => <hr className="my-3 border-bp-jambalaya/15" />,

  // GFM tables — scroll horizontally if wide
  table: (props) => (
    <div className="mb-2 overflow-x-auto last:mb-0">
      <table className="w-full border-collapse text-[13px]" {...props} />
    </div>
  ),
  th: (props) => <th className="border border-bp-jambalaya/15 bg-bp-linen px-2 py-1 text-left font-semibold" {...props} />,
  td: (props) => <td className="border border-bp-jambalaya/15 px-2 py-1 align-top" {...props} />,
};

export default function MarkdownMessage({ text }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
      {text}
    </ReactMarkdown>
  );
}

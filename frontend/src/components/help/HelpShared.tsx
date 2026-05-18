import { useState, useEffect, useRef } from 'react';
import { Copy, Check } from 'lucide-react';

export function useBaseUrl() {
  if (typeof window !== 'undefined') {
    return window.location.origin;
  }
  return 'http://localhost:8000'; // SSR fallback
}

export interface TocItem { id: string; label: string; indent?: boolean }

// ---------- CopyButton ----------

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
      className="absolute top-3 right-3 p-1.5 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-300 hover:text-white transition-colors"
      title="复制"
    >
      {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
    </button>
  );
}

// ---------- CodeBlock ----------

export function CodeBlock({ code, lang = 'json' }: { code: string; lang?: string }) {
  return (
    <div className="relative">
      <pre className={`language-${lang} bg-slate-900 text-slate-100 rounded-xl p-4 pr-12 text-sm overflow-x-auto leading-relaxed`}>
        <code>{code}</code>
      </pre>
      <CopyButton text={code} />
    </div>
  );
}

// ---------- SectionCard ----------

interface SectionCardProps {
  id: string;
  title: string;
  description: string;
  badge?: string;
  badgeColor?: string;
  children: React.ReactNode;
}

export function SectionCard({ id, title, description, badge, badgeColor, children }: SectionCardProps) {
  return (
    <div id={id} className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden scroll-mt-4">
      <div className="p-6 border-b border-slate-100">
        <div className="flex items-center gap-3 mb-1">
          <h3 className="text-lg font-semibold text-slate-800">{title}</h3>
          {badge && <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${badgeColor}`}>{badge}</span>}
        </div>
        <p className="text-sm text-slate-500">{description}</p>
      </div>
      <div className="p-6 space-y-4">{children}</div>
    </div>
  );
}

// ---------- CurlSection ----------

export function CurlSection({ body, endpoint }: { body: string; endpoint?: string }) {
  const baseUrl = useBaseUrl();
  const [show, setShow] = useState(false);
  const actualEndpoint = endpoint ?? `${baseUrl}/v1/responses`;
  const curl = `curl -X POST ${actualEndpoint} \\\n  -H "Authorization: Bearer <YOUR_API_KEY>" \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`;
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide">请求体</span>
        <button onClick={() => setShow(v => !v)} className="text-xs text-blue-500 hover:text-blue-700 underline underline-offset-2">
          {show ? '隐藏 cURL' : '查看 cURL'}
        </button>
      </div>
      <CodeBlock code={body} />
      {show && (
        <div className="mt-3">
          <span className="text-xs font-semibold text-slate-500 uppercase tracking-wide block mb-2">cURL 示例</span>
          <CodeBlock code={curl} lang="bash" />
        </div>
      )}
    </div>
  );
}

// ---------- TableOfContents ----------

export function TableOfContents({ items, accentColor = 'cyan' }: { items: TocItem[]; accentColor?: string }) {
  const [active, setActive] = useState(items[0]?.id ?? '');
  const scrollRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    scrollRef.current = document.querySelector('main') as HTMLElement;
    const container = scrollRef.current;
    if (!container) return;
    const onScroll = () => {
      let cur = items[0]?.id ?? '';
      for (const item of items) {
        const el = document.getElementById(item.id);
        if (el) {
          const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top;
          if (top <= 80) cur = item.id;
        }
      }
      setActive(cur);
    };
    container.addEventListener('scroll', onScroll, { passive: true });
    return () => container.removeEventListener('scroll', onScroll);
  }, [items]);

  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    const container = scrollRef.current;
    if (el && container) {
      const top = el.getBoundingClientRect().top - container.getBoundingClientRect().top;
      container.scrollTo({ top: container.scrollTop + top - 16, behavior: 'smooth' });
    }
  };

  const colorMap: Record<string, { bg: string; text: string; border: string }> = {
    cyan:    { bg: 'bg-cyan-50',    text: 'text-cyan-600',    border: 'border-cyan-500' },
    blue:    { bg: 'bg-blue-50',    text: 'text-blue-600',    border: 'border-blue-500' },
  };
  const c = colorMap[accentColor] ?? colorMap.cyan;

  return (
    <aside className="w-52 flex-shrink-0 hidden xl:block">
      <div className="sticky top-0 max-h-screen overflow-y-auto">
        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest mb-3 px-1">本页内容</p>
        <nav className="space-y-0.5">
          {items.map((item) => (
            <button
              key={item.id}
              onClick={() => scrollTo(item.id)}
              className={`w-full text-left rounded-lg text-sm transition-all duration-150 ${
                active === item.id
                  ? `${c.bg} ${c.text} font-medium border-l-2 ${c.border}`
                  : 'text-slate-500 hover:text-slate-800 hover:bg-slate-50'
              } ${item.indent ? 'pl-5 pr-2 py-1' : 'px-3 py-1.5'}`}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </div>
    </aside>
  );
}
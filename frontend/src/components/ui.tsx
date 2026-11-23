import { useRef, useState, type ReactNode } from "react";
import { ChevronDown, type LucideIcon } from "lucide-react";

export type Tone = "emerald" | "rose" | "amber" | "sky" | "zinc";

const toneClasses: Record<Tone, string> = {
  emerald: "bg-emerald-400/10 text-emerald-300 ring-1 ring-inset ring-emerald-400/20",
  rose: "bg-rose-400/10 text-rose-300 ring-1 ring-inset ring-rose-400/20",
  amber: "bg-amber-400/10 text-amber-300 ring-1 ring-inset ring-amber-400/20",
  sky: "bg-sky-400/10 text-sky-300 ring-1 ring-inset ring-sky-400/20",
  zinc: "bg-white/[0.06] text-zinc-300 ring-1 ring-inset ring-white/[0.08]",
};

export function Badge({ children, tone = "zinc", className = "", dashed = false }: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
  dashed?: boolean;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium leading-none ${toneClasses[tone]} ${dashed ? "border border-dashed border-amber-400/50 !bg-transparent" : ""} ${className}`}>
      {children}
    </span>
  );
}

export function Chip({ children, tone = "zinc", className = "", onClick, title, ariaLabel }: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
  onClick?: () => void;
  title?: string;
  ariaLabel?: string;
}) {
  const classes = `inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium leading-none transition-colors ${toneClasses[tone]} ${onClick ? "cursor-pointer hover:brightness-125 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40" : ""} ${className}`;
  if (onClick) {
    return <button type="button" className={classes} onClick={onClick} title={title} aria-label={ariaLabel}>{children}</button>;
  }
  return <span className={classes} title={title}>{children}</span>;
}

export function MetricTile({ label, value, sub, tone = "zinc", prominent = false, children }: {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
  prominent?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className={`min-w-0 rounded-lg bg-[#161D27] px-3 py-2.5 ${prominent ? "min-w-[126px]" : "min-w-[112px]"}`}>
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-zinc-500">{label}</div>
      <div className={`mt-1 font-mono tabular-nums leading-none tracking-tight ${prominent ? "text-[24px]" : "text-[20px]"} ${tone === "emerald" ? "text-emerald-300" : tone === "rose" ? "text-rose-300" : tone === "amber" ? "text-amber-300" : tone === "sky" ? "text-sky-300" : "text-zinc-200"}`}>
        {value}
      </div>
      {sub ? <div className="mt-1.5 break-words text-[10px] leading-4 text-zinc-400" title={sub}>{sub}</div> : null}
      {children}
    </div>
  );
}

export function SectionLabel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <h3 className={`text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500 ${className}`}>{children}</h3>;
}

export function Collapse({ title, children, className = "", initialOpen = false, icon: Icon, trailing }: {
  title: ReactNode;
  children: ReactNode;
  className?: string;
  initialOpen?: boolean;
  icon?: LucideIcon;
  trailing?: ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(initialOpen);
  const root = useRef<HTMLDivElement>(null);
  const toggle = () => {
    const opening = !isOpen;
    setIsOpen(opening);
    // Once the expand transition has run, make sure the newly revealed content is actually visible.
    if (opening) window.setTimeout(() => root.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 180);
  };
  return (
    <div ref={root} className={`${className} scroll-mb-4`}>
      <button
        type="button"
        aria-expanded={isOpen}
        onClick={toggle}
        className="group flex w-full items-center gap-2 rounded-lg text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-sky-500/40"
      >
        {Icon ? <Icon aria-hidden="true" size={15} strokeWidth={1.75} className="shrink-0 text-zinc-400" /> : null}
        <span className="min-w-0 flex-1">{title}</span>
        {trailing}
        <ChevronDown aria-hidden="true" size={15} className={`shrink-0 text-zinc-500 transition-transform duration-150 ${isOpen ? "rotate-180" : ""}`} />
      </button>
      <div className={`grid transition-[grid-template-rows,opacity] duration-150 ease-out ${isOpen ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`}>
        <div className="overflow-hidden" aria-hidden={!isOpen}>
          <div className="pt-3">{children}</div>
        </div>
      </div>
    </div>
  );
}

export function IconButton({ icon: Icon, label, onClick, className = "", disabled = false }: {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-white/[0.07] hover:text-zinc-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40 disabled:cursor-not-allowed disabled:opacity-40 ${className}`}
    >
      <Icon aria-hidden="true" size={16} strokeWidth={1.75} />
    </button>
  );
}

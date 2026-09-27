"use client";

import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, ArrowRight, ChevronDown, CircleHelp, Command, PanelLeftClose, PanelLeftOpen, Search, ShieldCheck, X } from "lucide-react";
import type { DisplayState } from "@deeptutor/api-contracts";

export type NavItem = { label: string; href: string; icon?: ReactNode };
export type NavGroup = { label: string; items: NavItem[] };
export type TableColumn<T> = { key: string; label: string; render: (row: T) => ReactNode; width?: string };
export type TableRowAction = { label: string; onClick: () => void; disabled?: boolean };

function subscribeLocationSearch(onChange: () => void) {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
}

export function useLocationSearch() {
  return useSyncExternalStore(subscribeLocationSearch, () => window.location.search, () => "");
}

export function useSessionFilter(key: string, initial: string): [string, (value: string) => void] {
  const [stored, setStored] = useState({ key, value: initial, ready: false });
  useEffect(() => {
    const saved = sessionStorage.getItem(`deeptutor-prototype:filter:${key}`);
    const timer = window.setTimeout(() => setStored(current => current.key === key && current.ready ? current : { key, value: saved ?? initial, ready: true }), 0);
    return () => window.clearTimeout(timer);
  }, [key, initial]);
  useEffect(() => {
    if (stored.ready && stored.key === key) sessionStorage.setItem(`deeptutor-prototype:filter:${key}`, stored.value);
  }, [key, stored]);
  return [stored.key === key ? stored.value : initial, value => setStored({ key, value, ready: true })];
}

export function AdminShell({ product, subtitle, scope, groups, path, onNavigate, children }: {
  product: string; subtitle: string; scope: string; groups: NavGroup[]; path: string;
  onNavigate: (href: string) => void; children: ReactNode;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [sidebarPreference, setSidebarPreference] = useState({ product, collapsed: false, ready: false });
  const collapsed = sidebarPreference.product === product && sidebarPreference.collapsed;
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem(`deeptutor-prototype:sidebar:${product}`); } catch { /* 禁用本地存储时仍可手动切换 */ }
    const timer = window.setTimeout(() => setSidebarPreference(current => current.product === product && current.ready ? current : { product, collapsed: saved === "collapsed", ready: true }), 0);
    return () => window.clearTimeout(timer);
  }, [product]);
  useEffect(() => {
    if (!sidebarPreference.ready || sidebarPreference.product !== product) return;
    try { localStorage.setItem(`deeptutor-prototype:sidebar:${product}`, sidebarPreference.collapsed ? "collapsed" : "expanded"); } catch { /* 偏好无法保存不影响导航 */ }
  }, [product, sidebarPreference]);
  const activeHref = groups.flatMap(group => group.items).reduce((match, item) =>
    (path === item.href || path.startsWith(`${item.href}/`)) && item.href.length > match.length ? item.href : match, "");
  return <div className={`admin-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
    <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
      <div className="brand"><span className="brand-mark"><Command size={19}/></span><span className="brand-copy"><strong>智能体基座</strong><small>{subtitle}</small></span><button type="button" className="sidebar-toggle" onClick={() => setSidebarPreference({ product, collapsed: !collapsed, ready: true })} aria-label={collapsed ? "展开侧栏" : "收起侧栏"} aria-expanded={!collapsed} title={collapsed ? "展开侧栏" : "收起侧栏"}>{collapsed ? <PanelLeftOpen size={18}/> : <PanelLeftClose size={18}/>}</button></div>
      <div className="workspace-switch" aria-label={scope} title={collapsed ? scope : undefined}><span className="workspace-dot"/><span>{scope}</span></div>
      <nav aria-label={`${subtitle}导航`} className="sidebar-nav">
        {groups.map(group => <div className="nav-group" key={group.label}><div className="nav-group-title">{group.label}</div>
          {group.items.map(item => <button key={item.href} type="button" className={`nav-item ${activeHref === item.href ? "active" : ""}`} aria-label={item.label} aria-current={activeHref === item.href ? "page" : undefined} title={collapsed ? item.label : undefined} onClick={() => { onNavigate(item.href); setMenuOpen(false); }}>{item.icon ?? <span className="nav-fallback" aria-hidden="true">{item.label.slice(0, 1)}</span>}<span className="nav-label">{item.label}</span></button>)}
        </div>)}
      </nav>
      <div className="sidebar-bottom" title={collapsed ? "仅本地演示 · 不连接生产数据" : undefined}><ShieldCheck size={15}/><span>仅本地演示 · 不连接生产数据</span></div>
    </aside>
    <div className="main-column">
      <header className="topbar"><button type="button" className="mobile-menu" onClick={() => setMenuOpen(!menuOpen)} aria-label="切换导航" aria-expanded={menuOpen}>☰</button><span className="topbar-product">{subtitle}</span><span className="topbar-separator"/><span className="topbar-context">{scope}</span><div className="topbar-right"><span className="demo-indicator">演示环境</span><CircleHelp size={17}/><span className="avatar">{product[0]}</span></div></header>
      <main className="content">{children}</main>
    </div>
  </div>;
}

export function PageHead({ eyebrow, title, description, actions, breadcrumbs }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode; breadcrumbs?: { label: string; onClick?: () => void }[] }) {
  return <div className="page-head">
    {breadcrumbs && <div className="breadcrumbs">{breadcrumbs.map((crumb, index) => <span key={index}>{index > 0 && <span className="crumb-divider">/</span>}{crumb.onClick ? <button onClick={crumb.onClick}>{crumb.label}</button> : <span>{crumb.label}</span>}</span>)}</div>}
    {eyebrow && breadcrumbs && <div className="eyebrow">{eyebrow}</div>}
    <div className="page-head-row"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="head-actions">{actions}</div>}</div>
  </div>;
}

export function Button({ children, onClick, variant = "secondary", disabled = false }: { children: ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "quiet"; disabled?: boolean }) {
  return <button className={`button button-${variant}`} type="button" onClick={onClick} disabled={disabled}>{children}</button>;
}

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: "good" | "warn" | "bad" | "neutral" | "info" }) {
  return <span className={`status status-${tone}`}><span className="status-dot"/>{children}</span>;
}

export function MetricStrip({ items }: { items: { label: string; value: string; note?: string; tone?: string }[] }) {
  return <div className="metric-strip">{items.map(item => <div className="metric" key={item.label}><span>{item.label}</span><strong className={item.tone}>{item.value}</strong>{item.note && <small>{item.note}</small>}</div>)}</div>;
}

export function DataTable<T extends { id: string }>({ rows, columns, searchLabel = "搜索", searchText, filters, pageSize = 8, onOpen, openLabel, rowActions, persistKey, state = "ready", emptyText = "没有符合条件的记录" }: {
  rows: T[]; columns: TableColumn<T>[]; searchLabel?: string; searchText?: (row: T) => string; filters?: { label: string; value: string; options: { label: string; value: string }[]; onChange: (value: string) => void }[];
  pageSize?: number; onOpen?: (row: T) => void; openLabel?: (row: T) => string; rowActions?: (row: T) => TableRowAction[]; persistKey?: string; state?: DisplayState; emptyText?: string;
}) {
  const [stored, setStored] = useState({ key: persistKey, query: "", page: 1, ready: !persistKey });
  const query = stored.key === persistKey ? stored.query : "";
  const page = stored.key === persistKey ? stored.page : 1;
  useEffect(() => {
    if (!persistKey) return;
    const saved = sessionStorage.getItem(`deeptutor-prototype:${persistKey}`);
    let restored = { query: "", page: 1 };
    if (saved) {
      try {
        const value = JSON.parse(saved) as { query?: string; page?: number };
        restored = { query: typeof value.query === "string" ? value.query : "", page: Number.isSafeInteger(value.page) && (value.page ?? 0) > 0 ? value.page! : 1 };
      } catch { /* 非可信浏览器状态丢弃 */ }
    }
    const timer = window.setTimeout(() => setStored(current => current.key === persistKey && current.ready ? current : { key: persistKey, ...restored, ready: true }), 0);
    return () => window.clearTimeout(timer);
  }, [persistKey]);
  useEffect(() => {
    if (persistKey && stored.key === persistKey && stored.ready) sessionStorage.setItem(`deeptutor-prototype:${persistKey}`, JSON.stringify({ query: stored.query, page: stored.page }));
  }, [persistKey, stored]);
  const updateQuery = (next: string) => setStored({ key: persistKey, query: next, page: 1, ready: true });
  const updatePage = (next: number) => setStored({ key: persistKey, query, page: next, ready: true });
  const filtered = useMemo(() => rows.filter(row => !query || (searchText ? searchText(row) : JSON.stringify(row)).toLocaleLowerCase().includes(query.toLocaleLowerCase())), [rows, query, searchText]);
  const count = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(page, count);
  const visible = filtered.slice((current - 1) * pageSize, current * pageSize);
  return <div className="table-card">
    <div className="table-toolbar"><label className="search-field"><Search size={17}/><input type="search" aria-label={searchLabel} placeholder={searchLabel} value={query} onChange={event => updateQuery(event.target.value)}/></label>
      <div className="filter-row">{filters?.map(filter => <label className="select-wrap" key={filter.label}><span>{filter.label}</span><select aria-label={filter.label} value={filter.value} onChange={event => { filter.onChange(event.target.value); updatePage(1); }}>{filter.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select><ChevronDown size={14}/></label>)}</div>
    </div>
    {state !== "ready" ? <StatePanel state={state}/> : filtered.length === 0 ? <StatePanel state="empty" message={emptyText}/> : <><div className="table-scroll"><table><thead><tr>{columns.map(column => <th key={column.key} style={{ width: column.width }}>{column.label}</th>)}{(rowActions || onOpen) && <th className={rowActions ? "action-col action-col-multiple" : "action-col"}>操作</th>}</tr></thead><tbody>{visible.map(row => <tr key={row.id}>{columns.map(column => <td key={column.key} data-label={column.label}>{column.render(row)}</td>)}{(rowActions || onOpen) && <td data-label="操作"><div className="table-actions">{rowActions ? rowActions(row).map(action => <button key={action.label} type="button" className="table-link" disabled={action.disabled} onClick={action.onClick}>{action.label}</button>) : onOpen && <button type="button" className="table-link" aria-label={openLabel?.(row)} onClick={() => onOpen(row)}>查看详情 <ArrowRight size={14}/></button>}</div></td>}</tr>)}</tbody></table></div><div className="table-footer"><span>共 {filtered.length} 条记录 · 第 {current} / {count} 页</span><div><button onClick={() => updatePage(Math.max(1, current - 1))} disabled={current === 1} aria-label="上一页"><ArrowLeft size={16}/></button><button onClick={() => updatePage(Math.min(count, current + 1))} disabled={current === count} aria-label="下一页"><ArrowRight size={16}/></button></div></div></>}
  </div>;
}

export function StatePanel({ state, message }: { state: DisplayState; message?: string }) {
  const copy = { loading: ["正在载入", "请稍候，正在读取演示数据。"], empty: ["暂无记录", message || "当前筛选条件下没有数据。"], error: ["暂时无法读取", "请稍后重试，或检查演示场景。"], forbidden: ["没有访问权限", "当前角色无权查看此内容。"], pending: ["用量待核对", "供应商结果尚未确认，不能将未知用量当作零。"], ready: ["", ""] };
  return <div className="state-panel"><div className="state-symbol">{state === "loading" ? "◌" : state === "error" ? "!" : state === "forbidden" ? "×" : state === "pending" ? "…" : "—"}</div><strong>{copy[state][0]}</strong><p>{message || copy[state][1]}</p></div>;
}

export function DetailGrid({ rows }: { rows: { label: string; value: ReactNode }[] }) {
  return <dl className="detail-grid">{rows.map(row => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl>;
}

export function Section({ title, subtitle, children, action }: { title?: string; subtitle?: string; children: ReactNode; action?: ReactNode }) {
  return <section className="section">{(title || subtitle || action) && <div className="section-head"><div>{title && <h2>{title}</h2>}{subtitle && <p>{subtitle}</p>}</div>{action}</div>}{children}</section>;
}

export function Tabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (tab: string) => void }) {
  return <div className="tabs" role="tablist">{tabs.map(tab => <button type="button" role="tab" aria-selected={active === tab} className={active === tab ? "selected" : ""} key={tab} onClick={() => onChange(tab)}>{tab}</button>)}</div>;
}

export function Notice({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "warn" | "bad" }) {
  return <div className={`notice notice-${tone}`}>{children}</div>;
}

function useOverlayKeyboard(ref: React.RefObject<HTMLDivElement | null>, onClose: () => void, suspended = false, active = true) {
  const closeRef = useRef(onClose);
  useEffect(() => { closeRef.current = onClose; }, [onClose]);
  useEffect(() => {
    if (suspended || !active) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    ref.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.stopPropagation(); closeRef.current(); return; }
      if (event.key !== "Tab") return;
      const focusable = [...(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])') ?? [])];
      if (!focusable.length) { event.preventDefault(); ref.current?.focus(); return; }
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => { document.removeEventListener("keydown", onKeyDown); previous?.focus(); };
  }, [ref, suspended, active]);
}

export function Drawer({ title, children, onClose, suspended = false }: { title: string; children: ReactNode; onClose: () => void; suspended?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useOverlayKeyboard(ref, onClose, suspended);
  useEffect(() => { const previous = document.body.style.overflow; document.body.style.overflow = "hidden"; return () => { document.body.style.overflow = previous; }; }, []);
  return <div className="overlay-layer drawer-layer"><div className="overlay-backdrop" onClick={onClose}/><div ref={ref} role="dialog" aria-modal={suspended ? undefined : "true"} aria-hidden={suspended} aria-label={title} tabIndex={-1} className="drawer-panel"><div className="overlay-header"><strong>{title}</strong><button type="button" aria-label="关闭抽屉" onClick={onClose}><X size={18}/></button></div><div className="drawer-body">{children}</div></div></div>;
}

const subscribeDocumentBody = () => () => {};

export function FormModal({ title, children, onClose, suspended = false }: { title: string; children: ReactNode; onClose: () => void; suspended?: boolean }) {
  const host = useSyncExternalStore(subscribeDocumentBody, () => document.body, () => null);
  const ref = useRef<HTMLDivElement>(null);
  useOverlayKeyboard(ref, onClose, suspended, !!host);
  useEffect(() => {
    if (!host) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [host]);
  if (!host) return null;
  return createPortal(<div className="overlay-layer modal-layer form-modal-layer" hidden={suspended}>
    <div className="overlay-backdrop" onClick={onClose}/>
    <div ref={ref} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} className="modal-panel form-modal-panel">
      <div className="overlay-header"><strong>{title}</strong><button type="button" aria-label="关闭操作框" onClick={onClose}><X size={18}/></button></div>
      <div className="form-modal-body">{children}</div>
    </div>
  </div>, host);
}

export function ConfirmModal({ title, description, confirmLabel = "确认", onConfirm, onCancel }: { title: string; description: string; confirmLabel?: string; onConfirm: () => void; onCancel: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useOverlayKeyboard(ref, onCancel);
  return <div className="overlay-layer modal-layer"><div className="overlay-backdrop" onClick={onCancel}/><div ref={ref} role="alertdialog" aria-modal="true" aria-label={title} aria-describedby="confirm-description" tabIndex={-1} className="modal-panel"><div className="overlay-header"><strong>{title}</strong><button type="button" aria-label="关闭确认框" onClick={onCancel}><X size={18}/></button></div><p id="confirm-description">{description}</p><div className="form-actions"><Button onClick={onCancel}>取消</Button><Button variant="primary" onClick={onConfirm}>{confirmLabel}</Button></div></div></div>;
}

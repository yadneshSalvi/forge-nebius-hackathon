import { useEffect, useRef } from "react";
import { ArrowRight, Check, Circle, LoaderCircle, X } from "lucide-react";
import type { ReactNode } from "react";
import { formatValue, human, record, str, tone } from "./data";

export function Status({ value, label }: { value: unknown; label?: string }) {
  const labelText = label || human(value);
  return (
    <span className={`status status-${tone(value)}`}>
      <span className="status-dot" aria-hidden="true" />
      {labelText}
    </span>
  );
}
export function Eyebrow({ children }: { children: ReactNode }) {
  return <div className="eyebrow">{children}</div>;
}
export function Empty({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-cross" aria-hidden="true">
        +
      </div>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function Loading({ label = "Loading evidence" }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle className="spin" size={18} />
      <span>{label}</span>
    </div>
  );
}
export function PageHeading({
  number,
  label,
  title,
  description,
  actions,
}: {
  number: string;
  label: string;
  title: string;
  description: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        <Eyebrow>
          <span>{number}</span>
          <span className="eyebrow-line" />
          {label}
        </Eyebrow>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {actions ? <div className="heading-actions">{actions}</div> : null}
    </header>
  );
}
export function SectionTitle({
  eyebrow,
  title,
  detail,
  children,
}: {
  eyebrow?: string;
  title: string;
  detail?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
        <h2>{title}</h2>
        {detail ? <p>{detail}</p> : null}
      </div>
      {children}
    </div>
  );
}
export function ActionLink({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className="text-button" onClick={onClick}>
      {children}
      <ArrowRight size={15} />
    </button>
  );
}
export function Panel({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return <section className={`panel ${className}`}>{children}</section>;
}
export function DefinitionList({
  entries,
}: {
  entries: [string, ReactNode][];
}) {
  return (
    <dl className="definition-list">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
export function JsonDetails({
  value,
  label = "Technical details",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="json-details">
      <summary>{label}</summary>
      <pre tabIndex={0}>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function DataDetails({ value }: { value: unknown }) {
  if (value == null) return <span className="muted">Not recorded</span>;
  if (typeof value !== "object") return <span>{formatValue(value)}</span>;
  return (
    <dl className="data-details">
      {Object.entries(record(value)).map(([key, v]) => (
        <div key={key}>
          <dt>{human(key)}</dt>
          <dd>
            {typeof v === "object" && v !== null ? (
              <pre tabIndex={0}>{JSON.stringify(v, null, 2)}</pre>
            ) : (
              formatValue(v)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function Drawer({
  title,
  eyebrow,
  children,
  onClose,
  footer,
  wide = false,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  onClose: () => void;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      previous?.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialogRef}
      className={`drawer ${wide ? "drawer-wide" : ""}`}
      aria-labelledby="drawer-title"
      onCancel={(event) => {
        event.preventDefault();
        closeRef.current();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) closeRef.current();
      }}
    >
      <div className="drawer-inner">
        <header className="drawer-header">
          <div>
            {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
            <h2 id="drawer-title">{title}</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        <div className="drawer-content">{children}</div>
        {footer ? <footer className="drawer-footer">{footer}</footer> : null}
      </div>
    </dialog>
  );
}
export function StageCheck({
  state,
  label,
  number,
}: {
  state: "done" | "current" | "pending";
  label: string;
  number: number;
}) {
  return (
    <div className={`stage-check stage-${state}`}>
      <span className="stage-check-icon">
        {state === "done" ? (
          <Check size={13} />
        ) : state === "current" ? (
          <Circle size={11} />
        ) : (
          String(number).padStart(2, "0")
        )}
      </span>
      <span>{label}</span>
    </div>
  );
}
export function ErrorMessage({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <div className="inline-error" role="alert">
      <span>{str(error, "Something interrupted this request.")}</span>
      {retry ? (
        <button className="text-button" onClick={retry}>
          Try again
          <ArrowRight size={14} />
        </button>
      ) : null}
    </div>
  );
}

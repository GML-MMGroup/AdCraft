import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import "./catalog-toolbar.css";

export function CatalogToolbar({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`catalog-toolbar ${className}`}>{children}</div>;
}

export function CatalogFilterButton({ className = "", active = false, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return <button type="button" {...props} className={`filter-btn clear-glass-control${active ? " is-active" : ""} ${className}`} />;
}

export function CatalogSearch({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="catalog-search-shell">
      <svg className="catalog-search-icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
        <circle cx="8.5" cy="8.5" r="5.25" />
        <path d="m12.5 12.5 4 4" />
      </svg>
      <input {...props} className={`catalog-search search-box clear-glass-control is-active ${className}`} />
    </label>
  );
}

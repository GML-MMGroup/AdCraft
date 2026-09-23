import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";
import "./catalog-toolbar.css";

export function CatalogToolbar({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`catalog-toolbar ${className}`}>{children}</div>;
}

export function CatalogFilterButton({ className = "", active = false, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return <button type="button" {...props} className={`filter-btn clear-glass-control${active ? " is-active" : ""} ${className}`} />;
}

export function CatalogSearch({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`catalog-search search-box clear-glass-control is-active ${className}`} />;
}

import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, SelectHTMLAttributes, TableHTMLAttributes } from "react";
import styles from "./ui.module.css";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  const variantClass = variant === "primary" ? "" : styles[variant];
  return <button className={`${styles.control} ${styles.button} ${variantClass} ${className}`} {...props} />;
}
export function IconButton(props: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return <Button {...props} className={`${styles.iconButton} ${props.className ?? ""}`} />;
}
export function Input({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${styles.control} ${styles.field} ${className}`} {...props} />;
}
export function Select({ className = "", ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={`${styles.control} ${styles.field} ${className}`} {...props} />;
}
export function Panel({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`${styles.panel} ${className}`} {...props} />;
}
export function Badge({ tone = "neutral", className = "", ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "success" | "warning" | "danger" }) {
  const toneClass = tone === "success" ? styles.badgeSuccess : tone === "warning" ? styles.badgeWarning : tone === "danger" ? styles.badgeDanger : "";
  return <span className={`${styles.badge} ${toneClass} ${className}`} {...props} />;
}
export function EmptyState({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`${styles.empty} ${className}`} {...props} />;
}
export function Table({ className = "", ...props }: TableHTMLAttributes<HTMLTableElement>) {
  return <table className={`${styles.table} ${className}`} {...props} />;
}
export { default as Dialog } from "@/components/ConfirmModal";
export { default as Toast } from "@/components/Toast";
export { default as RouteLoading } from "@/components/RouteLoading";

import styles from "./Toast.module.css";

type ToastProps = { message: string; tone?: "success" | "error"; onDismiss?: () => void };

export default function Toast({ message, tone = "success", onDismiss }: ToastProps) {
  return (
    <div className={`${styles.toast} ${tone === "error" ? styles.error : ""}`} role={tone === "error" ? "alert" : "status"}>
      <span>{message}</span>
      {onDismiss && <button onClick={onDismiss} aria-label="Dismiss notification">×</button>}
    </div>
  );
}

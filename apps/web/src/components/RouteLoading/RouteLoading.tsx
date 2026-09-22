import styles from "./RouteLoading.module.css";

export default function RouteLoading() {
  return (
    <main className={styles.page} aria-live="polite" aria-busy="true">
      <span className={styles.mark} aria-hidden="true" />
      <span>Loading Cerebro…</span>
    </main>
  );
}

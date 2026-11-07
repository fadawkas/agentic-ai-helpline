import type { Readiness } from "../../types/api";

type SystemStatusProps = { health: Readiness | null; isChecking: boolean };

export function SystemStatus({ health, isChecking }: SystemStatusProps) {
  const services = [
    ["Backend API", health ? "Terhubung" : isChecking ? "Memeriksa…" : "Tidak tersedia"],
    ["PostgreSQL", health?.dependencies.postgresql === "ok" ? "Terhubung" : isChecking ? "Memeriksa…" : "Tidak tersedia"],
    ["Qdrant", health?.dependencies.qdrant === "ok" ? "Terhubung" : isChecking ? "Memeriksa…" : "Tidak tersedia"],
    ["Asterisk ARI", health?.dependencies.asterisk_ari === "disabled" ? "Nonaktif" : health?.dependencies.asterisk_ari === "ok" ? "Terhubung" : isChecking ? "Memeriksa…" : "Tidak tersedia"],
  ];
  return <section className="grid gap-5" aria-labelledby="system-title">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><span className="eyebrow">PEMANTAUAN</span><h2 id="system-title" className="mt-2 font-display text-xl font-semibold text-forest-900 sm:text-2xl">Layanan Ruang Mara</h2></div><span className="text-xs text-stone-500">Pembaruan otomatis · 10 detik</span></div>
    <div className="grid gap-3 sm:grid-cols-2">{services.map(([name, status], index) => <article key={name} className="flex min-h-20 items-center gap-3 rounded-xl border border-stone-200 bg-paper-50 p-4"><span className={`service-icon icon-${index}`} aria-hidden="true">{["↗", "◉", "◇", "⌁"][index]}</span><div className="min-w-0 flex-1"><h3 className="text-sm font-medium text-stone-700">{name}</h3><p className="mt-1 text-sm font-semibold text-forest-900">{status}</p></div><span className={`status-indicator ${status === "Terhubung" ? "is-online" : ""}`} aria-label={status} /></article>)}</div>
     {health?.dependencies.asterisk_ari !== "disabled" && <div className="call-panel"><div className="call-copy"><span className="eyebrow">UJI AUDIO LOKAL</span><h2>Uji koneksi panggilan.</h2><p>Hubungkan Linphone ke server lokal dan hubungi ekstensi gema untuk memastikan audio berfungsi.</p><div className="call-instructions"><span className="instruction-icon" aria-hidden="true">↳</span><span>Daftar sebagai <b>1001</b>, lalu hubungi <b>7001</b> untuk uji gema.</span></div></div><div className="call-visual" aria-hidden="true"><div className="call-ring ring-back" /><div className="call-ring ring-front"><span>♫</span></div><span className="call-spark">✳</span></div></div>}
  </section>;
}

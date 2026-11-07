import type { Readiness } from "../../types/api";

export function LandingPage({ health, isChecking }: { health: Readiness | null; isChecking: boolean }) {
  const services = [
    ["Backend API", health ? "Terhubung" : isChecking ? "Memeriksa…" : "Tidak tersedia"],
    ["PostgreSQL", health?.dependencies.postgresql === "ok" ? "Terhubung" : isChecking ? "Memeriksa…" : "Tidak tersedia"],
    ["Qdrant", health?.dependencies.qdrant === "ok" ? "Terhubung" : isChecking ? "Memeriksa…" : "Tidak tersedia"],
    ["Asterisk ARI", health?.dependencies.asterisk_ari === "disabled" ? "Nonaktif" : health?.dependencies.asterisk_ari === "ok" ? "Terhubung" : isChecking ? "Memeriksa…" : "Tidak tersedia"],
  ];
  return <>
    <section className="status-section" aria-labelledby="landing-status-title"><div className="section-heading"><div><span className="eyebrow">SISTEM</span><h2 id="landing-status-title">Status layanan</h2></div><span className="status-updated">Pembaruan otomatis · 10 detik</span></div><div className="status-grid">{services.map(([name, status], index) => <article className="status-card" key={name}><div className={`service-icon icon-${index}`} aria-hidden="true">{["↗", "◉", "◇", "⌁"][index]}</div><div className="service-info"><span>{name}</span><strong>{status}</strong></div><span className={`status-indicator ${status === "Terhubung" ? "is-online" : ""}`} /></article>)}</div></section>
    {health?.dependencies.asterisk_ari !== "disabled" && <section className="call-panel"><div className="call-copy"><span className="eyebrow">UJI AUDIO LOKAL</span><h2>Pastikan jalur suara siap.</h2><p>Hubungkan Linphone ke server lokal dan lakukan panggilan diagnostik untuk menguji koneksi audio.</p><div className="call-instructions"><span className="instruction-icon" aria-hidden="true">↳</span><span>Daftar sebagai <b>1001</b>, lalu hubungi <b>7001</b> untuk uji gema.</span></div></div><div className="call-visual" aria-hidden="true"><div className="call-ring ring-back" /><div className="call-ring ring-front"><span>♫</span></div><span className="call-spark">✳</span></div></section>}
    <footer><span>Ruang Mara</span><span className="disclaimer">Bukan pengganti layanan kesehatan mental profesional.</span></footer>
  </>;
}

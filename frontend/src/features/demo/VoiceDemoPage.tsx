import { Brand } from "../../components/Brand";
import { Notice } from "../../components/Notice";
import { useVoiceDemo } from "./useVoiceDemo";

export function VoiceDemoPage() {
  const { phase, message, error, connect, disconnect } = useVoiceDemo();
  const isActive = phase !== "idle";
  return <main className="page-shell min-h-screen">
    <header className="topbar"><Brand /><a className="demo-link" href="/">← Kembali ke beranda</a></header>
    <div className="mx-auto grid max-w-5xl items-center gap-10 py-12 md:grid-cols-2 md:gap-16 md:py-20">
      <section className="welcome-panel" aria-labelledby="demo-title">
        <span className="eyebrow"><span className="eyebrow-dot" /> RUANG UNTUK DIDENGARKAN</span>
        <div className="welcome-copy"><h1 id="demo-title">Mulai dari<br /><em>ceritamu.</em></h1><p>Bicarakan apa yang sedang kamu rasakan bersama AI Ruang Mara. Ambil waktu sejenak, mulai dengan ceritamu, dan lanjutkan sesuai kenyamananmu.</p></div>
        <ol className="mt-8 grid gap-4 text-sm leading-relaxed text-[#526965]">
          <li><b className="mr-3 text-[#b97449]">01</b> Tekan hubungkan dan izinkan akses mikrofon.</li>
          <li><b className="mr-3 text-[#b97449]">02</b> Mulai bicara dalam Bahasa Indonesia.</li>
          <li><b className="mr-3 text-[#b97449]">03</b> Dengarkan jawaban AI, lalu lanjutkan ceritamu.</li>
        </ol>
      </section>
      <section className="rounded-xl border border-[#dce5e1] bg-white p-6 text-center shadow-sm sm:p-10" aria-labelledby="voice-title">
        <div className={`mx-auto mb-7 flex h-28 w-28 items-center justify-center rounded-full border ${phase === "connected" ? "border-[#32866a] bg-[#e6f1eb]" : "border-[#dce5e1] bg-[#f2f5f3]"}`} aria-hidden="true">
          <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="#1d4d49" strokeWidth="1.5" strokeLinecap="round"><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4M8 22h8" /></svg>
        </div>
        <span className="eyebrow">PERCAKAPAN DENGAN AI</span>
        <h2 id="voice-title" className="mt-3 text-2xl font-semibold tracking-tight text-[#173739]">{phase === "connected" ? "Ruang untuk suaramu." : phase === "connecting" ? "Menyiapkan ruang…" : "Siap untuk didengarkan?"}</h2>
        <p className="mt-3 min-h-12 text-sm leading-relaxed text-[#526965]" role="status" aria-live="polite">{message || "Mikrofon hanya aktif selama kamu terhubung. Gunakan headphone untuk suara yang lebih jernih."}</p>
        <div className="mt-6 grid gap-3">
          {phase === "idle" ? <button className="primary-button w-full" onClick={() => void connect()}>Hubungkan dengan AI</button> : <>
            <span className="text-sm font-medium text-[#28564c]">{phase === "connected" ? "● Terhubung · Mikrofon aktif" : "Menghubungkan…"}</span>
            <button className="quiet-button w-full" onClick={disconnect}>{phase === "connecting" ? "Batalkan" : "Akhiri percakapan"}</button>
          </>}
        </div>
        {error && <div className="mt-4 text-left"><Notice tone="error">{error}</Notice></div>}
        <p className="mt-6 border-t border-[#e6ece9] pt-4 text-xs leading-relaxed text-[#6b807a]">{isActive ? "Kamu dapat mengakhiri percakapan kapan saja." : "Izinkan akses mikrofon saat kamu siap berbicara."}<br />Durasi percakapan hingga 5 menit per sesi.</p>
      </section>
    </div>
    <aside className="mx-auto mb-12 max-w-5xl rounded-lg border border-[#d5e1dc] bg-[#e5eeea] p-5 text-sm leading-relaxed text-[#526965]"><strong className="text-[#173739]">Sebelum mulai</strong><p className="mt-1">Kamu berbicara dengan AI, bukan tenaga kesehatan mental profesional. Ruang Mara bukan layanan darurat. Audio diproses oleh layanan AI yang digunakan Ruang Mara. Hindari membagikan informasi pribadi yang sensitif.</p></aside>
    <footer><span>Ruang Mara</span><span className="disclaimer">Ruang untuk bercerita, waktu untuk dirimu.</span></footer>
  </main>;
}

import { documentCategories, type KnowledgeDocument } from "../../types/api";

export function DocumentFormFields({ document }: { document?: KnowledgeDocument }) {
  return <>
    <label className="field-label">File sumber<input className="field-control" type="file" name="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" required /></label>
    <label className="field-label">Judul {!document && <span className="font-normal text-stone-500">(opsional)</span>}<input className="field-control" name="title" defaultValue={document?.title} placeholder={document ? undefined : "Otomatis diisi dari nama file"} required={!!document} /></label>
    <div className="grid gap-4 sm:grid-cols-2">
      <label className="field-label">Penerbit<input className="field-control" name="publisher" defaultValue={document?.publisher} placeholder="Contoh: WHO" required /></label>
      <label className="field-label">Kategori<select className="field-control" name="category" defaultValue={document?.category ?? "mental_health_education"}>{documentCategories.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
    </div>
    <label className="field-label">URL sumber resmi<input className="field-control" type="url" name="source_url" defaultValue={document?.source_url} placeholder="https://..." required /></label>
    <label className="field-label">Tanggal verifikasi sumber<input className="field-control" type="date" name="verified_at" defaultValue={document?.verified_at} required /></label>
    <details className="rounded-xl border border-stone-200 p-4" open={!!document}>
      <summary className="cursor-pointer text-sm font-semibold text-forest-800">Informasi rujukan <span className="font-normal text-stone-500">(opsional)</span></summary>
      <div className="mt-4 grid gap-4">
        <label className="field-label">Wilayah layanan<input className="field-control" name="region" defaultValue={document?.region ?? ""} placeholder="Contoh: Nasional atau Jawa Barat" /></label>
        <label className="field-label">Kontak resmi<input className="field-control" name="contact_details" defaultValue={document?.contact_details ?? ""} placeholder="Nomor atau URL resmi" /></label>
        <label className="field-label">Syarat akses<input className="field-control" name="eligibility" defaultValue={document?.eligibility ?? ""} placeholder="Kelompok pengguna atau syarat layanan" /></label>
      </div>
    </details>
  </>;
}

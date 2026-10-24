import { documentCategories, type DocumentAction, type KnowledgeDocument } from "../../types/api";
import { ValidationReport } from "./ValidationReport";

const statusLabels: Record<KnowledgeDocument["status"], string> = {
  ACTIVE: "Aktif", EXTRACTING: "Mengekstrak teks", OCR: "Menjalankan OCR", VALIDATING: "Memvalidasi", PROCESSING: "Mengindeks", FAILED: "Gagal", DISABLED: "Nonaktif", REJECTED: "Ditolak", UNVERIFIABLE: "Belum terverifikasi",
};

type DocumentRowProps = {
  document: KnowledgeDocument;
  isBusy: boolean;
  onEdit: () => void;
  onAction: (action: DocumentAction) => void;
};

export function DocumentRow({ document, isBusy, onEdit, onAction }: DocumentRowProps) {
  return <article className="flex flex-col gap-4 border-b border-stone-100 p-4 last:border-0 sm:p-5 lg:flex-row lg:items-start lg:justify-between">
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2"><h3 className="break-words text-sm font-semibold leading-6 text-forest-900">{document.title}</h3>{document.is_baseline && <span className="rounded-full bg-sage-100 px-2 py-1 text-[10px] font-bold tracking-wide text-forest-800">SUMBER DASAR</span>}</div>
      <p className="mt-1 text-xs leading-5 text-stone-600">{document.publisher} · {documentCategories.find(([key]) => key === document.category)?.[1] ?? document.category.replaceAll("_", " ")} · {document.chunk_count} bagian · Diperbarui {new Intl.DateTimeFormat("id-ID", { dateStyle: "medium" }).format(new Date(document.updated_at))}</p>
      {document.error_message && <p className="mt-2 rounded-lg bg-red-50 px-3 py-2 text-xs text-red-800">{document.error_message}</p>}
      <ValidationReport document={document} />
    </div>
    <div className="flex flex-wrap items-center gap-2 lg:max-w-[18rem] lg:justify-end">
      <span className={`document-status status-${document.status.toLowerCase()}`}>{statusLabels[document.status]}</span>
      <button className="row-action" onClick={onEdit} disabled={isBusy}>Perbarui</button>
      {(["DISABLED", "FAILED", "REJECTED", "UNVERIFIABLE"] as string[]).includes(document.status)
        ? <button className="row-action" onClick={() => onAction("enable")} disabled={isBusy}>{isBusy ? "Memproses…" : "Validasi ulang"}</button>
        : <button className="row-action" onClick={() => onAction("disable")} disabled={isBusy}>{isBusy ? "Memproses…" : "Nonaktifkan"}</button>}
      <button className="row-action row-action-danger" onClick={() => onAction("delete")} disabled={isBusy}>{isBusy ? "Memproses…" : "Hapus"}</button>
    </div>
  </article>;
}

import { useMemo, useState } from "react";
import type { DocumentAction, KnowledgeDocument } from "../../types/api";
import { documentStatuses } from "../../types/api";
import { Notice } from "../../components/Notice";
import { DocumentRow } from "./DocumentRow";

type DocumentLibraryProps = {
  documents: KnowledgeDocument[];
  isLoading: boolean;
  loadError: string;
  busyDocumentId: string | null;
  onAdd: () => void;
  onEdit: (document: KnowledgeDocument) => void;
  onRefresh: () => void;
  onAction: (id: string, action: DocumentAction) => void;
};

export function DocumentLibrary({ documents, isLoading, loadError, busyDocumentId, onAdd, onEdit, onRefresh, onAction }: DocumentLibraryProps) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("ALL");
  const filteredDocuments = useMemo(() => documents.filter((document) => {
    const matchesStatus = status === "ALL" || document.status === status;
    const searchable = `${document.title} ${document.publisher} ${document.category.replaceAll("_", " ")}`.toLocaleLowerCase();
    return matchesStatus && searchable.includes(query.trim().toLocaleLowerCase());
  }), [documents, query, status]);
  const active = documents.filter((document) => document.status === "ACTIVE").length;
  const processing = documents.filter((document) => ["EXTRACTING", "OCR", "VALIDATING", "PROCESSING"].includes(document.status)).length;
  const attention = documents.filter((document) => ["FAILED", "DISABLED", "REJECTED", "UNVERIFIABLE"].includes(document.status)).length;

  return <div className="grid gap-5">
    <div className="grid gap-3 sm:grid-cols-3">
      <StatCard label="Dokumen aktif" count={active} note="Digunakan Mara" />
      <StatCard label="Sedang diproses" count={processing} note="Ekstraksi atau validasi" />
      <StatCard label="Perlu perhatian" count={attention} note="Perlu ditinjau" />
    </div>
    <section className="overflow-hidden rounded-2xl border border-stone-200 bg-paper-50" aria-labelledby="documents-title">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-5">
        <div><h2 id="documents-title" className="font-display text-lg font-semibold text-forest-900">Semua dokumen</h2><p className="mt-1 text-xs text-stone-500">Menampilkan {filteredDocuments.length} dari {documents.length}</p></div>
        <button className="quiet-button" onClick={onRefresh} disabled={isLoading}>{isLoading ? "Memuat…" : "Muat ulang"}</button>
      </div>
      <div className="grid gap-2 border-y border-stone-100 bg-paper-100 p-4 sm:grid-cols-[minmax(0,1fr)_13rem]">
        <label className="sr-only" htmlFor="document-search">Cari dokumen</label>
        <input id="document-search" className="field-control bg-white" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Cari judul, penerbit, atau kategori…" />
        <label className="sr-only" htmlFor="document-status">Filter status</label>
        <select id="document-status" className="field-control bg-white" value={status} onChange={(event) => setStatus(event.target.value)}>{documentStatuses.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
      </div>
      {loadError && <div className="px-4 pt-4 sm:px-5"><Notice tone="error">{loadError}</Notice><button className="row-action mt-3" onClick={onRefresh}>Coba muat ulang</button></div>}
      {isLoading && !documents.length ? <div className="p-8 text-center text-sm text-stone-600" role="status">Memuat pustaka dokumen…</div>
        : !filteredDocuments.length ? <div className="flex min-h-56 flex-col items-center justify-center p-6 text-center"><span aria-hidden="true" className="text-2xl text-sage-600">▤</span><h3 className="mt-2 font-semibold text-forest-900">{documents.length ? "Tidak ada dokumen yang cocok" : "Belum ada dokumen"}</h3><p className="mt-1 max-w-sm text-sm leading-6 text-stone-600">{documents.length ? "Coba ubah kata kunci atau filter status." : "Tambahkan sumber tepercaya pertama untuk Mara."}</p>{!documents.length && <button className="primary-button mt-4" onClick={onAdd}>Tambah dokumen</button>}</div>
          : filteredDocuments.map((document) => <DocumentRow key={document.document_id} document={document} isBusy={busyDocumentId === document.document_id} onEdit={() => onEdit(document)} onAction={(action) => onAction(document.document_id, action)} />)}
    </section>
  </div>;
}

function StatCard({ label, count, note }: { label: string; count: number; note: string }) {
  return <article className="grid grid-cols-[1fr_auto] items-center gap-x-3 rounded-xl border border-stone-200 bg-paper-50 p-4">
    <span className="text-xs font-medium text-stone-600">{label}</span><strong className="row-span-2 font-display text-2xl text-forest-900">{count}</strong><span className="mt-1 text-[11px] text-stone-500">{note}</span>
  </article>;
}

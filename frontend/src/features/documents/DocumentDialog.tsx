import { useState, type FormEvent } from "react";
import { Dialog } from "../../components/Dialog";
import { Notice } from "../../components/Notice";
import type { KnowledgeDocument } from "../../types/api";
import { DocumentFormFields } from "./DocumentFormFields";

type DocumentDialogProps = {
  document?: KnowledgeDocument;
  isSaving: boolean;
  onClose: () => void;
  onSave: (form: HTMLFormElement) => Promise<{ ok: boolean; message: string }>;
};

export function DocumentDialog({ document, isSaving, onClose, onSave }: DocumentDialogProps) {
  const [error, setError] = useState("");
  const title = document ? "Perbarui dokumen" : "Tambah dokumen";
  const close = () => { if (!isSaving) onClose(); };
  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    const result = await onSave(event.currentTarget);
    if (result.ok) onClose();
    else setError(result.message);
  };

  return <Dialog titleId="document-dialog-title" onClose={close}>
    <form onSubmit={handleSubmit} className="grid gap-4">
      <div className="flex items-start justify-between gap-4"><div><h2 id="document-dialog-title" className="font-display text-xl font-semibold text-forest-900">{title}</h2><p className="mt-1 text-sm leading-6 text-stone-600">{document ? "Dokumen aktif tetap tersedia saat versi baru diproses." : "Tambahkan sumber resmi untuk pengetahuan Mara."}</p></div><button type="button" className="quiet-button shrink-0" onClick={close} disabled={isSaving}>Tutup</button></div>
      <h3 className="border-b border-stone-200 pb-2 text-xs font-bold uppercase tracking-wider text-stone-500">File dan sumber</h3>
      <DocumentFormFields document={document} />
      {error && <Notice tone="error">{error}</Notice>}
      <button type="submit" className="primary-button min-h-11 text-sm" disabled={isSaving}>{isSaving ? "Mengunggah…" : document ? "Simpan dan indeks versi baru" : "Unggah dan indeks dokumen"}</button>
      <p className="text-xs leading-5 text-stone-500">PDF (maks. 100 halaman), DOCX, TXT, Markdown, PNG, atau JPEG. Pemrosesan teks dan OCR berjalan otomatis.</p>
    </form>
  </Dialog>;
}

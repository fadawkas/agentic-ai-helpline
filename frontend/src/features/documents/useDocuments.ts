import { useCallback, useEffect, useRef, useState } from "react";
import { AdminApiError, errorText, getDocuments, performDocumentAction, submitDocument } from "../../api/admin";
import type { DocumentAction, KnowledgeDocument } from "../../types/api";

export function useDocuments(isEnabled: boolean) {
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [sessionExpired, setSessionExpired] = useState(false);
  const [busyDocumentId, setBusyDocumentId] = useState<string | null>(null);
  const requestInFlight = useRef(false);
  const requestGeneration = useRef(0);

  const refresh = useCallback(async () => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    const generation = requestGeneration.current;
    try {
      const nextDocuments = await getDocuments();
      if (generation === requestGeneration.current) {
        setDocuments(nextDocuments);
        setLoadError("");
        setSessionExpired(false);
      }
    } catch (reason) {
      if (generation === requestGeneration.current) {
        setLoadError(errorText(reason, "Dokumen gagal dimuat."));
        if (reason instanceof AdminApiError && reason.status === 401) setSessionExpired(true);
      }
    } finally {
      requestInFlight.current = false;
      if (generation === requestGeneration.current) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!isEnabled) {
      requestGeneration.current += 1;
      setDocuments([]);
      setLoadError("");
      setSessionExpired(false);
      setIsLoading(true);
      return;
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [isEnabled, refresh]);

  const save = async (form: HTMLFormElement, documentId?: string) => {
    setBusyDocumentId(documentId ?? "upload");
    try {
      await submitDocument(form, documentId);
      if (!documentId) form.reset();
      await refresh();
      return { ok: true, message: documentId ? "Versi baru sedang diproses; versi aktif tetap tersedia hingga selesai." : "Dokumen diterima. Ekstraksi dan indexing berjalan otomatis." };
    } catch (reason) {
      if (reason instanceof AdminApiError && reason.status === 401) setSessionExpired(true);
      return { ok: false, message: errorText(reason, "Dokumen gagal disimpan. Periksa koneksi lalu coba lagi.") };
    } finally {
      setBusyDocumentId(null);
    }
  };

  const runAction = async (documentId: string, action: DocumentAction) => {
    setBusyDocumentId(documentId);
    try {
      const performed = await performDocumentAction(documentId, action);
      if (performed) await refresh();
      return { ok: performed, message: performed ? "" : "" };
    } catch (reason) {
      if (reason instanceof AdminApiError && reason.status === 401) setSessionExpired(true);
      return { ok: false, message: errorText(reason, "Aksi dokumen gagal. Periksa koneksi lalu coba lagi.") };
    } finally {
      setBusyDocumentId(null);
    }
  };

  return { documents, isLoading, loadError, sessionExpired, busyDocumentId, refresh, save, runAction };
}

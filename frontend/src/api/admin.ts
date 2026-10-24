import type { DocumentAction, KnowledgeDocument, Readiness, SearchResult } from "../types/api";

type ApiError = { detail?: string };

export class AdminApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "AdminApiError";
  }
}

async function errorMessage(response: Response, fallback: string) {
  try {
    const result = (await response.json()) as ApiError;
    return new AdminApiError(result.detail ?? fallback, response.status);
  } catch {
    return new AdminApiError(fallback, response.status);
  }
}

export async function getSession() {
  const response = await fetch("/api/admin/session");
  if (!response.ok) return null;
  return (await response.json()) as { username: string };
}

export async function loginAdmin(username: string, password: string) {
  const response = await fetch("/api/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!response.ok) throw await errorMessage(response, "Login gagal. Periksa nama pengguna dan kata sandi.");
  return (await response.json()) as { username: string };
}

export async function logoutAdmin() {
  const response = await fetch("/api/admin/logout", { method: "POST" });
  if (!response.ok) throw new Error("Tidak dapat keluar. Coba lagi.");
}

export async function getDocuments() {
  const response = await fetch("/api/admin/documents");
  if (!response.ok) throw await errorMessage(response, "Dokumen gagal dimuat.");
  return (await response.json()) as KnowledgeDocument[];
}

export async function submitDocument(form: HTMLFormElement, documentId?: string) {
  const response = await fetch(documentId ? `/api/admin/documents/${encodeURIComponent(documentId)}` : "/api/admin/documents", {
    method: documentId ? "PUT" : "POST",
    body: new FormData(form),
  });
  if (!response.ok) throw await errorMessage(response, documentId ? "Pembaruan dokumen gagal." : "Dokumen gagal diproses.");
}

export async function performDocumentAction(documentId: string, action: DocumentAction) {
  if (action === "delete" && !window.confirm("Hapus dokumen dan indeksnya secara permanen?")) return false;
  const response = await fetch(`/api/admin/documents/${encodeURIComponent(documentId)}${action === "delete" ? "" : `/${action}`}`, {
    method: action === "delete" ? "DELETE" : "POST",
  });
  if (!response.ok) throw await errorMessage(response, "Aksi dokumen gagal.");
  return true;
}

export async function searchKnowledge(query: string) {
  const response = await fetch("/api/admin/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
  if (!response.ok) throw await errorMessage(response, "Pencarian belum dapat dilakukan.");
  return ((await response.json()) as { results: SearchResult[] }).results;
}

export async function getReadiness() {
  const response = await fetch("/api/health/ready");
  if (!response.ok) throw new Error("Status sistem tidak tersedia.");
  return (await response.json()) as Readiness;
}

export function errorText(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

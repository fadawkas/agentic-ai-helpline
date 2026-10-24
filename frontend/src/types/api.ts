export type Readiness = { status: string; dependencies: Record<string, string> };

export type DocumentStatus = "EXTRACTING" | "OCR" | "VALIDATING" | "PROCESSING" | "ACTIVE" | "FAILED" | "DISABLED" | "REJECTED" | "UNVERIFIABLE";

export type KnowledgeDocument = {
  document_id: string;
  title: string;
  publisher: string;
  category: string;
  status: DocumentStatus;
  error_message: string | null;
  chunk_count: number;
  is_baseline: boolean;
  source_url: string;
  verified_at: string;
  region: string | null;
  contact_details: string | null;
  eligibility: string | null;
  validation_report: {
    outcome: string;
    reason_codes: string[];
    explanation: string;
    assessment?: {
      supporting_evidence: { supported_claim: string; document_excerpt: string; source_excerpt: string }[];
      findings: { code: string; severity: string; explanation: string }[];
    } | null;
  } | null;
  updated_at: string;
};

export type SearchResult = { title: string; text: string; source_url: string; score: number };
export type AdminSection = "library" | "search" | "status";
export type DocumentAction = "disable" | "enable" | "delete";

export const documentStatuses: { value: DocumentStatus | "ALL"; label: string }[] = [
  { value: "ALL", label: "Semua status" },
  { value: "ACTIVE", label: "Aktif" },
  { value: "EXTRACTING", label: "Mengekstrak teks" },
  { value: "OCR", label: "Menjalankan OCR" },
  { value: "PROCESSING", label: "Mengindeks" },
  { value: "VALIDATING", label: "Memvalidasi" },
  { value: "FAILED", label: "Gagal" },
  { value: "DISABLED", label: "Nonaktif" },
  { value: "REJECTED", label: "Ditolak" },
  { value: "UNVERIFIABLE", label: "Belum terverifikasi" },
];

export const documentCategories = [
  ["mental_health_education", "Edukasi kesehatan mental"],
  ["emotional_wellbeing", "Kesejahteraan emosional"],
  ["coping_strategy", "Strategi coping"],
  ["help_seeking", "Mencari bantuan"],
  ["referral_resource", "Sumber rujukan"],
] as const;

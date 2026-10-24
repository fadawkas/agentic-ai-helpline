import { useEffect, useRef, useState } from "react";
import { AdminApiError, errorText, logoutAdmin, searchKnowledge } from "./api/admin";
import { Brand } from "./components/Brand";
import { Notice } from "./components/Notice";
import { AdminWorkspace } from "./features/admin/AdminWorkspace";
import { useAdminSession } from "./features/auth/useAdminSession";
import { LoginPage } from "./features/auth/LoginPage";
import { DocumentDialog } from "./features/documents/DocumentDialog";
import { DocumentLibrary } from "./features/documents/DocumentLibrary";
import { useDocuments } from "./features/documents/useDocuments";
import { KnowledgeSearch } from "./features/knowledge/KnowledgeSearch";
import { LandingPage } from "./features/landing/LandingPage";
import { SystemStatus } from "./features/system/SystemStatus";
import { useSystemHealth } from "./features/system/useSystemHealth";
import type { AdminSection, KnowledgeDocument, SearchResult } from "./types/api";

export default function App() {
  const { username, setUsername, isChecking } = useAdminSession();
  const { health, isChecking: isCheckingHealth } = useSystemHealth();
  const [section, setSection] = useState<AdminSection>("library");
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [editingDocument, setEditingDocument] = useState<KnowledgeDocument | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [logoutError, setLogoutError] = useState("");
  const searchRequestId = useRef(0);
  const documentsState = useDocuments(!!username);

  useEffect(() => {
    if (documentsState.sessionExpired) {
      setUsername(null);
      setActionNotice("Sesi admin berakhir. Silakan masuk kembali.");
    }
  }, [documentsState.sessionExpired, setUsername]);

  const openUpload = () => { setActionNotice(""); setIsUploadOpen(true); };
  const handleSaveDocument = async (form: HTMLFormElement, documentId?: string) => {
    const result = await documentsState.save(form, documentId);
    if (result.ok) {
      setActionNotice(result.message);
      if (documentId) setEditingDocument(null);
      else setIsUploadOpen(false);
    }
    return result;
  };

  const handleSearch = async (query: string) => {
    const requestId = ++searchRequestId.current;
    setSearchError("");
    setSearchResults([]);
    setIsSearching(true);
    try {
      const results = await searchKnowledge(query);
      if (requestId === searchRequestId.current) setSearchResults(results);
    } catch (error) {
      if (requestId !== searchRequestId.current) return;
      if (error instanceof AdminApiError && error.status === 401) {
        setUsername(null);
        setActionNotice("Sesi admin berakhir. Silakan masuk kembali.");
        return;
      }
      setSearchError(errorText(error, "Pencarian belum dapat dilakukan. Periksa koneksi lalu coba lagi."));
    } finally {
      if (requestId === searchRequestId.current) setIsSearching(false);
    }
  };

  const handleLogout = async () => {
    setLogoutError("");
    try {
      await logoutAdmin();
      searchRequestId.current += 1;
      setUsername(null);
      setSection("library");
      setSearchResults([]);
      setSearchError("");
      setIsSearching(false);
      setActionNotice("");
    } catch (error) {
      setLogoutError(errorText(error, "Tidak dapat keluar. Coba lagi."));
    }
  };

  const handleDocumentAction = async (documentId: string, action: "disable" | "enable" | "delete") => {
    const result = await documentsState.runAction(documentId, action);
    setActionNotice(result.message);
  };

  return <main className={`page-shell min-h-screen ${username ? "admin-shell" : ""}`}>
    <header className="topbar"><Brand />{username ? <span className="environment"><i /> Ruang admin</span> : <span className="environment"><i /> Manajemen pengetahuan</span>}</header>
    {isChecking ? <div className="mx-auto mt-20 max-w-md text-center text-sm text-stone-600" role="status">Memeriksa sesi admin…</div>
      : username ? <>
        {logoutError && <div className="mx-auto mt-4 max-w-5xl"><Notice tone="error">{logoutError}</Notice></div>}
        {actionNotice && <div className="mx-auto mt-4 max-w-5xl"><Notice>{actionNotice}</Notice></div>}
        <AdminWorkspace username={username} section={section} onSectionChange={(nextSection) => { if (nextSection !== section) { searchRequestId.current += 1; setSearchResults([]); setSearchError(""); setIsSearching(false); } setSection(nextSection); setActionNotice(""); }} onAddDocument={openUpload} onLogout={() => void handleLogout()}>
          {section === "library" && <DocumentLibrary documents={documentsState.documents} isLoading={documentsState.isLoading} loadError={documentsState.loadError} busyDocumentId={documentsState.busyDocumentId} onAdd={openUpload} onEdit={(document) => setEditingDocument(document)} onRefresh={() => void documentsState.refresh()} onAction={(id, action) => void handleDocumentAction(id, action)} />}
          {section === "search" && <KnowledgeSearch results={searchResults} searching={isSearching} error={searchError} onSearch={handleSearch} />}
          {section === "status" && <SystemStatus health={health} isChecking={isCheckingHealth} />}
        </AdminWorkspace>
        {isUploadOpen && <DocumentDialog isSaving={documentsState.busyDocumentId === "upload"} onClose={() => setIsUploadOpen(false)} onSave={(form) => handleSaveDocument(form)} />}
        {editingDocument && <DocumentDialog document={editingDocument} isSaving={documentsState.busyDocumentId === editingDocument.document_id} onClose={() => setEditingDocument(null)} onSave={(form) => handleSaveDocument(form, editingDocument.document_id)} />}
      </> : <>
        <div className="signed-out-layout">
          <section className="welcome-panel" aria-labelledby="welcome-title">
            <span className="eyebrow"><span className="eyebrow-dot" /> DUKUNGAN SUARA · INDONESIA</span>
            <div className="welcome-copy"><h1 id="welcome-title">Ruang untuk<br /><em>didengarkan.</em></h1><p>Pendamping suara untuk percakapan yang suportif, informasi kesehatan mental, dan rujukan tepercaya.</p></div>
            <p className="welcome-note">AI ini bukan pengganti layanan kesehatan mental profesional.</p>
          </section>
          <LoginPage notice={actionNotice} onLogin={(admin) => { setUsername(admin); setActionNotice(""); }} />
        </div>
        <LandingPage health={health} isChecking={isCheckingHealth} />
      </>}
  </main>;
}

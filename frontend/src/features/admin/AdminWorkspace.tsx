import type { ReactNode } from "react";
import type { AdminSection } from "../../types/api";

type AdminWorkspaceProps = {
  username: string;
  section: AdminSection;
  onSectionChange: (section: AdminSection) => void;
  onAddDocument: () => void;
  onLogout: () => void;
  children: ReactNode;
};

const navigation: { key: AdminSection; icon: string; label: string }[] = [
  { key: "library", icon: "▤", label: "Pustaka dokumen" },
  { key: "search", icon: "⌕", label: "Uji pengetahuan" },
  { key: "status", icon: "◉", label: "Status sistem" },
];

const sectionText: Record<AdminSection, { eyebrow: string; heading: string; description: string }> = {
  library: { eyebrow: "PUSTAKA", heading: "Pustaka dokumen.", description: "Kelola sumber tepercaya yang digunakan Mara untuk membantu pengguna." },
  search: { eyebrow: "UJI PENGETAHUAN", heading: "Uji pengetahuan.", description: "Pastikan sumber yang tepat mudah ditemukan dari pertanyaan sehari-hari." },
  status: { eyebrow: "STATUS SISTEM", heading: "Status sistem.", description: "Pantau koneksi layanan yang mendukung Ruang Mara." },
};

export function AdminWorkspace({ username, section, onSectionChange, onAddDocument, onLogout, children }: AdminWorkspaceProps) {
  const page = sectionText[section];
  return <section className="knowledge-admin">
    <div className="workspace">
      <nav className="workspace-nav" aria-label="Navigasi ruang admin">
        <span className="nav-caption">RUANG KERJA</span>
        {navigation.map((item) => <button key={item.key} className={section === item.key ? "nav-item selected" : "nav-item"} onClick={() => onSectionChange(item.key)} aria-current={section === item.key ? "page" : undefined}><span aria-hidden="true">{item.icon}</span>{item.label}</button>)}
        <div className="nav-account"><span className="account-avatar" aria-hidden="true">{username.slice(0, 1).toUpperCase()}</span><span><b title={username}>{username}</b><small>Administrator</small></span><button className="signout-button" onClick={onLogout} aria-label="Keluar">↗</button></div>
      </nav>
      <section className="workspace-content" role="region" aria-label="Konten admin" tabIndex={0}>
        <header className="admin-heading"><div><span className="eyebrow">RUANG MARA / {page.eyebrow}</span><h1>{section === "library" ? <>Pustaka <em>dokumen.</em></> : section === "search" ? <>Uji <em>pengetahuan.</em></> : <>Status <em>sistem.</em></>}</h1><p>{page.description}</p></div>{section === "library" && <button className="primary-button add-document" onClick={onAddDocument}>＋ Tambah dokumen</button>}</header>
        {children}
      </section>
    </div>
  </section>;
}

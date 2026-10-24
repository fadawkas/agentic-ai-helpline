import { useState, type FormEvent } from "react";
import { loginAdmin, errorText } from "../../api/admin";
import { Notice } from "../../components/Notice";

type LoginPageProps = { onLogin: (username: string) => void; notice?: string };

export function LoginPage({ onLogin, notice }: LoginPageProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const result = await loginAdmin(username, password);
      setPassword("");
      onLogin(result.username);
    } catch (reason) {
      setError(errorText(reason, "Tidak dapat masuk. Periksa koneksi lalu coba lagi."));
    } finally {
      setSubmitting(false);
    }
  };

  return <section className="admin-login" aria-labelledby="login-title">
    <span className="eyebrow">RUANG KERJA · ADMINISTRATOR</span>
    <div><h2 id="login-title">Masuk ke<br /><em>ruang kerja.</em></h2><p>Kelola sumber tepercaya dan pastikan pengetahuan Mara tetap terverifikasi.</p></div>
    {notice && <Notice>{notice}</Notice>}
    <form onSubmit={submit} className="grid gap-4">
      <label className="field-label">Nama pengguna<input className="field-control" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
      <label className="field-label">Kata sandi<input className="field-control" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
      {error && <Notice tone="error">{error}</Notice>}
      <button type="submit" className="primary-button min-h-11 text-sm" disabled={submitting}>{submitting ? "Memeriksa…" : "Masuk ke ruang kerja"}<span aria-hidden="true"> →</span></button>
    </form>
    <p className="text-xs leading-6 text-stone-500">Akses khusus administrator. Pengguna berinteraksi dengan layanan melalui telepon.</p>
  </section>;
}

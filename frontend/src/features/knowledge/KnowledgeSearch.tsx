import { useState, type FormEvent } from "react";
import { Notice } from "../../components/Notice";
import type { SearchResult } from "../../types/api";

type KnowledgeSearchProps = {
  results: SearchResult[];
  searching: boolean;
  error: string;
  onSearch: (query: string) => Promise<void>;
};

export function KnowledgeSearch({ results, searching, error, onSearch }: KnowledgeSearchProps) {
  const [query, setQuery] = useState("");
  const [hasSearched, setHasSearched] = useState(false);
  const [submittedQuery, setSubmittedQuery] = useState("");

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmittedQuery(query.trim());
    setHasSearched(true);
    await onSearch(query.trim());
  };

  return <section className="grid min-w-0 gap-5 rounded-2xl border border-stone-200 bg-paper-50 p-5 sm:p-7" aria-labelledby="search-title">
    <div><span className="eyebrow">UJI RETRIEVAL SUMBER</span><h2 id="search-title" className="mt-2 font-display text-xl font-semibold text-forest-900 sm:text-2xl">Temukan sumber dari pertanyaan</h2><p className="mt-2 max-w-2xl text-sm leading-6 text-stone-600">Uji apakah dokumen yang tepat muncul untuk pertanyaan seperti yang diajukan pengguna kepada Mara.</p></div>
    <form onSubmit={submit} className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
      <label className="sr-only" htmlFor="knowledge-query">Pertanyaan untuk diuji</label>
      <input id="knowledge-query" className="field-control min-h-12 bg-white text-sm" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Contoh: Di mana saya bisa mencari bantuan?" required minLength={2} maxLength={1200} />
      <button className="primary-button min-h-12 text-sm" type="submit" disabled={searching}>{searching ? "Mencari sumber…" : "Cari sumber"}</button>
    </form>
    {error && <Notice tone="error">{error}</Notice>}
    {results.length > 0 && <div aria-live="polite" className="min-w-0"><p className="mb-3 text-xs font-medium text-stone-500">Hasil untuk: “{submittedQuery}” · {results.length} sumber ditemukan</p><div className="divide-y divide-stone-100">{results.map((result, index) => <article key={`${result.source_url}-${index}`} className="min-w-0 py-4 first:pt-1"><div className="flex min-w-0 flex-wrap items-baseline justify-between gap-2"><h3 className="min-w-0 break-words font-semibold text-forest-900">{result.title}</h3><span className="text-xs text-stone-500">Skor retrieval {result.score.toFixed(2)}</span></div><p className="mt-2 min-w-0 text-sm leading-6 text-stone-600 [overflow-wrap:anywhere]">{result.text}</p><a className="mt-2 inline-flex min-h-10 max-w-full items-center break-all text-sm font-semibold text-forest-800 underline-offset-4 hover:underline" href={result.source_url} target="_blank" rel="noreferrer">Lihat sumber resmi ↗</a></article>)}</div></div>}
    {!searching && hasSearched && !error && !results.length && <div className="rounded-xl bg-paper-100 p-5" role="status"><h3 className="font-semibold text-forest-900">Belum ada sumber yang cocok</h3><p className="mt-1 text-sm leading-6 text-stone-600">Coba gunakan kata kunci atau susunan pertanyaan lain.</p></div>}
  </section>;
}

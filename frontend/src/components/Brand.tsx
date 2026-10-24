export function Brand() {
  return <a className="inline-flex items-center gap-3 font-display text-lg font-extrabold tracking-tight text-forest-900 no-underline" href="/" aria-label="Ruang Mara">
    <span className="brand-mark" aria-hidden="true">{[1, 2, 3, 4, 5].map((bar) => <i key={bar} />)}</span>
    <span>Ruang <span className="font-medium text-sage-700">Mara</span></span>
  </a>;
}

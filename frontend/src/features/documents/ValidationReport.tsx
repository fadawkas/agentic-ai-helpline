import type { KnowledgeDocument } from "../../types/api";

export function ValidationReport({ document }: { document: KnowledgeDocument }) {
  const report = document.validation_report;
  if (!report) return null;
  return <details className="mt-3 text-xs text-stone-600">
    <summary className="cursor-pointer font-semibold text-forest-800">Detail validasi · {report.outcome}</summary>
    <div className="mt-2 grid gap-2 border-l-2 border-sage-500 bg-paper-100 p-3 leading-5">
      <p><strong>Hasil: {report.outcome}</strong>{report.reason_codes.length > 0 && <> · {report.reason_codes.join(", ")}</>}</p>
      <p>{report.explanation}</p>
      {report.assessment?.findings.map((finding, index) => <p key={`finding-${index}`}><strong>{finding.severity} · {finding.code}:</strong> {finding.explanation}</p>)}
      {report.assessment?.supporting_evidence.map((evidence, index) => <details key={`evidence-${index}`} className="border-t border-stone-200 pt-2">
        <summary className="cursor-pointer text-forest-800">{evidence.supported_claim}</summary>
        <p className="mt-2"><strong>Kutipan dokumen:</strong> “{evidence.document_excerpt}”</p>
        <p className="mt-1"><strong>Kutipan sumber resmi:</strong> “{evidence.source_excerpt}”</p>
      </details>)}
    </div>
  </details>;
}

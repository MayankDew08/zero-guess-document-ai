import { useState } from 'react'
import type { Claim } from '../types'
import { Badge, type Tone } from './ui'
import { CitationChip, QuoteButton } from './CitationChip'
import { toEvidenceRef, type OpenEvidence } from './evidence'

const claimStatus: Record<Claim['status'], { label: string; tone: Tone; dot: string }> = {
  supported: { label: 'supported', tone: 'emerald', dot: 'bg-emerald-400' },
  contradicted: { label: 'contradicted', tone: 'rose', dot: 'bg-rose-400' },
  unsupported: { label: 'unsupported', tone: 'amber', dot: 'bg-amber-400' },
  abstained: { label: 'abstained', tone: 'zinc', dot: 'bg-zinc-400' },
  blocked: { label: 'blocked', tone: 'rose', dot: 'bg-rose-400' },
}

export function NliBadge({ label }: { label: string }) {
  const n = label.toLowerCase()
  return <Badge tone={n.includes('entail') ? 'emerald' : n.includes('contrad') ? 'rose' : 'zinc'} className="capitalize">NLI {label}</Badge>
}

export function ClaimCard({ claim, onOpenEvidence }: { claim: Claim; onOpenEvidence: OpenEvidence }) {
  const [showEn, setShowEn] = useState(false)
  const st = claimStatus[claim.status] ?? claimStatus.unsupported
  return (
    <div className="rounded-lg bg-[#161D27] px-3.5 py-3">
      <div className="flex items-start gap-2.5">
        <span aria-hidden="true" className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${st.dot}`} />
        <div className="min-w-0 flex-1">
          <p className="text-[14px] leading-6 text-zinc-200">{claim.text}</p>
          {claim.language === 'hi' && claim.text_en ? (
            <div className="mt-1.5">
              <button type="button" aria-expanded={showEn} onClick={() => setShowEn(v => !v)} className="text-[11px] text-sky-300 underline decoration-sky-300/30 underline-offset-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-500/40">
                {showEn ? 'Hide EN gloss' : 'Show EN gloss'}
              </button>
              {showEn ? <p className="mt-1 text-xs italic text-zinc-400">{claim.text_en}</p> : null}
            </div>
          ) : null}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <Badge tone={st.tone}><span className={`h-1.5 w-1.5 rounded-full ${st.dot}`} />{st.label}</Badge>
            {claim.citations.map(c => <CitationChip key={c.sentence_id} citation={c} onOpenEvidence={onOpenEvidence} compact />)}
          </div>
          {claim.citations.map(c => (
            <div key={`${claim.claim_id}-${c.sentence_id}`} className="mt-2 rounded-r-md bg-[#10151D] px-3 py-2.5">
              <QuoteButton evidenceRef={toEvidenceRef(c)} onOpenEvidence={onOpenEvidence} />
              <div className="mt-2 flex flex-wrap items-center gap-2 pl-3">
                <code className="text-[10px] text-zinc-600">{c.sentence_id}</code>
                {c.nli_label ? <NliBadge label={c.nli_label} /> : null}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

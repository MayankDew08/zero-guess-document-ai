import { ShieldAlert } from 'lucide-react'
import type { Claim } from '../types'
import { Badge, Collapse } from './ui'
import { CitationChip } from './CitationChip'
import type { OpenEvidence } from './evidence'

export function BlockedClaims({ claims, onOpenEvidence }: { claims: Claim[]; onOpenEvidence: OpenEvidence }) {
  return (
    <Collapse title={<span className="text-xs font-semibold text-rose-200">Blocked claims (never shown as answer) · {claims.length}</span>} className="rounded-lg bg-rose-400/[0.06] px-3.5 py-3" icon={ShieldAlert}>
      <div className="space-y-2.5">
        {claims.map(c => (
          <div key={c.claim_id} className="rounded-lg bg-[#10151D] px-3 py-2.5">
            <p className="text-[13px] leading-5 text-zinc-500 line-through decoration-rose-400/60">{c.text}</p>
            {c.reason ? <Badge tone="rose" className="mt-2 max-w-full whitespace-normal break-words leading-4">{c.reason}</Badge> : null}
            {c.citations.length ? <div className="mt-2.5 flex flex-wrap gap-1.5">{c.citations.map(ct => <CitationChip key={ct.sentence_id} citation={ct} onOpenEvidence={onOpenEvidence} compact />)}</div> : null}
          </div>
        ))}
      </div>
    </Collapse>
  )
}

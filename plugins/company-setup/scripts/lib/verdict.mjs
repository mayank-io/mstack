// Aggregate per-source CheckResults into a single overall verdict + markdown report.

/**
 * @param {import('./types.mjs').CheckResult[]} results
 * @param {{ candidate: string, targetClasses?: number[] }} ctx
 * @returns {{ overall: import('./types.mjs').OverallVerdict, risks: any[], reportMd: string }}
 */
export function aggregate(results, ctx) {
  const risks = [];
  const perSource = Object.fromEntries(results.map((r) => [r.source, r]));

  // USPTO scoring
  const uspto = perSource['uspto'];
  let usptoVerdict = 'unknown';
  if (uspto) {
    if (uspto.status === 'ok') {
      const liveInTarget = uspto.records.filter(
        (m) =>
          m.status === 'live' &&
          (!ctx.targetClasses || m.classes.some((c) => ctx.targetClasses.includes(c))),
      );
      const liveRegInTarget = liveInTarget.filter((m) => m.detail === 'registered');
      if (liveRegInTarget.length > 0) {
        usptoVerdict = 'blocked';
        risks.push({
          source: 'uspto',
          severity: 'high',
          note: `${liveRegInTarget.length} live registered mark(s) in target class — risk of §2(d) refusal or opposition`,
        });
      } else if (liveInTarget.length > 0) {
        usptoVerdict = 'crowded';
        risks.push({
          source: 'uspto',
          severity: 'medium',
          note: `${liveInTarget.length} live pending mark(s) in target class`,
        });
      } else if (uspto.totalCount > 0) {
        usptoVerdict = 'crowded';
        risks.push({
          source: 'uspto',
          severity: 'low',
          note: `${uspto.totalCount} mark(s) using the same wordmark in other classes — brand-recall noise`,
        });
      } else {
        usptoVerdict = 'available';
      }
    } else {
      usptoVerdict = 'inconclusive';
      risks.push({
        source: 'uspto',
        severity: 'medium',
        note: uspto.note ?? 'uspto check returned non-ok status',
      });
    }
  }

  // WA SoS scoring
  const wa = perSource['wa-sos'];
  let waVerdict = 'unknown';
  if (wa) {
    if (wa.status === 'ok') {
      // Match "Active" / "Active Pending" exactly — not "Inactive" or "Administratively Dissolved".
      const activeMatches = wa.records.filter((e) => {
        const s = String(e.status).toLowerCase().trim();
        return s === 'active' || s === 'active pending';
      });
      if (activeMatches.length === 0) {
        waVerdict = 'available';
      } else {
        const exact = activeMatches.find(
          (e) => normalizeName(e.name) === normalizeName(ctx.candidate),
        );
        if (exact) {
          waVerdict = 'blocked';
          risks.push({
            source: 'wa-sos',
            severity: 'high',
            note: `Active entity "${exact.name}" (UBI ${exact.ubi}) — name not distinguishable per RCW 23.95.305`,
          });
        } else {
          waVerdict = 'crowded';
          risks.push({
            source: 'wa-sos',
            severity: 'medium',
            note: `${activeMatches.length} active WA entity(ies) contain the same base term — possible distinguishability scrutiny`,
          });
        }
      }
    } else if (wa.status === 'blocked') {
      waVerdict = 'inconclusive';
      risks.push({
        source: 'wa-sos',
        severity: 'high',
        note: `WA SoS check did not complete (${wa.blockReason ?? 'blocked'}) — manual verification required before filing`,
      });
    } else {
      waVerdict = 'inconclusive';
      risks.push({
        source: 'wa-sos',
        severity: 'medium',
        note: wa.note ?? 'wa-sos check returned non-ok status',
      });
    }
  }

  // Domain scoring (informational only — never blocks)
  const dom = perSource['domain'];
  let domainNote = '';
  if (dom?.status === 'ok') {
    const taken = dom.records.filter((d) => d.registered);
    const free = dom.records.filter((d) => !d.registered);
    if (taken.length > 0) {
      risks.push({
        source: 'domain',
        severity: taken.length === dom.records.length ? 'medium' : 'low',
        note: `${taken.length}/${dom.records.length} TLDs registered`,
      });
    }
    domainNote = `${free.length} of ${dom.records.length} TLDs available`;
  }

  const overall = worstOf([usptoVerdict, waVerdict]);
  const reportMd = renderReport({ ctx, overall, risks, perSource, domainNote });

  return { overall, risks, reportMd };
}

function normalizeName(n) {
  return String(n)
    .toLowerCase()
    .replace(/,/g, '')
    .replace(/\b(llc|l\.l\.c\.|inc|inc\.|corp|corp\.|incorporated|limited liability company|co\.?)\b/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function worstOf(verdicts) {
  const order = ['blocked', 'inconclusive', 'crowded', 'available', 'unknown'];
  for (const v of order) {
    if (verdicts.includes(v)) return v === 'unknown' ? 'inconclusive' : v;
  }
  return 'inconclusive';
}

function renderReport({ ctx, overall, risks, perSource, domainNote }) {
  const lines = [];
  lines.push(`# Name availability report — ${ctx.candidate}`);
  lines.push('');
  lines.push(`Generated: ${new Date().toISOString()}`);
  if (ctx.targetClasses) {
    lines.push(`USPTO target classes: ${ctx.targetClasses.join(', ')}`);
  }
  lines.push('');
  lines.push('## Per-source results');
  lines.push('');
  lines.push('| Source | Status | Confidence | Records | Note |');
  lines.push('| --- | --- | --- | --- | --- |');
  for (const r of Object.values(perSource)) {
    lines.push(
      `| ${r.source} | ${r.status} | ${r.confidence} | ${r.totalCount} | ${(r.note ?? '').replace(/\n/g, ' ').slice(0, 80)} |`,
    );
  }
  lines.push('');

  // USPTO detail
  const uspto = perSource['uspto'];
  if (uspto?.status === 'ok' && uspto.records.length > 0) {
    lines.push('### USPTO marks (live first, then dead)');
    lines.push('');
    lines.push('| Serial | Wordmark | Status | Detail | Classes | Owner |');
    lines.push('| --- | --- | --- | --- | --- | --- |');
    const sorted = [...uspto.records].sort((a, b) => {
      if (a.status === b.status) return 0;
      return a.status === 'live' ? -1 : 1;
    });
    for (const m of sorted.slice(0, 30)) {
      lines.push(
        `| ${m.serial} | ${m.wordmark} | ${m.status} | ${m.detail} | ${m.classes.join(',') || '—'} | ${m.owner.name || '—'} |`,
      );
    }
    if (uspto.records.length > 30) {
      lines.push(`| ... | ... | ... | ... | ... | (${uspto.records.length - 30} more) |`);
    }
    lines.push('');
  }

  // WA SoS detail
  const wa = perSource['wa-sos'];
  if (wa?.status === 'ok' && wa.records.length > 0) {
    lines.push('### WA SoS entities');
    lines.push('');
    lines.push('| Entity | UBI | Type | Status | City |');
    lines.push('| --- | --- | --- | --- | --- |');
    for (const e of wa.records) {
      lines.push(`| ${e.name} | ${e.ubi} | ${e.type} | ${e.status} | ${e.city ?? '—'} |`);
    }
    lines.push('');
  }

  // Domain detail
  const dom = perSource['domain'];
  if (dom?.status === 'ok') {
    lines.push('### Domains');
    lines.push('');
    lines.push('| Domain | Registered | Registrar | Expires |');
    lines.push('| --- | --- | --- | --- |');
    for (const d of dom.records) {
      lines.push(
        `| ${d.domain} | ${d.registered ? 'yes' : 'no'} | ${d.registrar ?? '—'} | ${d.expiresAt ?? '—'} |`,
      );
    }
    lines.push('');
  }

  // Risks
  if (risks.length > 0) {
    lines.push('## Risks');
    lines.push('');
    for (const r of risks) {
      lines.push(`- **${r.source}** (${r.severity}) — ${r.note}`);
    }
    lines.push('');
  }

  lines.push(`## Overall verdict: \`${overall}\``);
  if (domainNote) {
    lines.push('');
    lines.push(`Domains: ${domainNote}`);
  }
  return lines.join('\n');
}

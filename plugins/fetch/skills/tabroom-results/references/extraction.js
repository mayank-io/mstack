/*
 * CANONICAL Tabroom competitor-history extraction — SINGLE SOURCE OF TRUTH.
 *
 * Page: tabroom.com/user/student/history.mhtml?tourn_id=<n>&student_id=<n>
 * Loaded by `scripts/tabroom_results.py` (injected into the page through gstack)
 * and by `scripts/tests/test_tabroom_results.py` (run under jsdom against a
 * fixture with the live page's structure). It is plain synchronous DOM code, so
 * any browser driver that can evaluate a script can run it. Do not copy these
 * functions elsewhere.
 *
 *   __tabroom.extract() -> {student, tournament, tourn_id, account, entries: [
 *       {event, code, columns, rounds: [
 *           {fields: {Round, Start, Room, ...}, judges: [{judge, scores: [{label, value}]}],
 *            feedback: [{judge, label, sections: [{heading, blocks: [{type, text|items}]}]}]}]}]}
 *   __tabroom.tournamentInfo() -> {dates_label, location}   (run on the tournament page)
 *
 * How the page is built (read off the live page 2026-11-13):
 *
 * - One results <table> per entry. tablesorter clones it into a second, empty
 *   "sticky header" table; that clone is skipped.
 * - A round is a `tr.row`. Its last cell lists each judge with leaf spans titled
 *   by role: the judge's name (title === text), then "Rank", "Points", ...
 * - The feedback for a round is ALREADY IN THE DOM, in a hidden `tr.feedback`
 *   that the round's button reveals with `toggleView('<id>_feedback')`. Nothing
 *   needs clicking. One block per judge: <h5> judge, <h6> label, then a section
 *   per comment box ("Reason for Rank/Decision", "Comments for you").
 *
 * Text is read with textContent, never innerText: the feedback rows are
 * display:none, and jsdom does not implement innerText at all.
 */
(function () {
  function clean(s) {
    return (s || '').replace(/ /g, ' ').replace(/[ \t\r\n]+/g, ' ').trim();
  }

  // Text of a block with <br> kept as a line break: judges type line-per-thought.
  function textOf(el) {
    let out = '';
    (function walk(n) {
      n.childNodes.forEach((c) => {
        if (c.nodeType === 3) out += c.textContent;
        else if (c.nodeType === 1) {
          if (c.tagName === 'BR') out += '\n';
          else walk(c);
        }
      });
    })(el);
    return out.split('\n').map(clean).filter(Boolean).join('\n');
  }

  function main() {
    return document.querySelector('.main') || document.body;
  }

  function resultTables() {
    return Array.from(main().querySelectorAll('table')).filter((t) =>
      !t.closest('.tablesorter-sticky-wrapper') && !/-sticky$/.test(t.id || '')
      && t.tBodies.length && t.tBodies[0].rows.length);
  }

  function columnsOf(table) {
    const head = table.tHead && table.tHead.rows[0];
    return head ? Array.from(head.cells).map((c) => clean(c.textContent)) : [];
  }

  // Leaf spans carry the role in `title`. A leaf whose title equals its own
  // text is a judge's name and opens a new judge; every other titled leaf is a
  // score of the judge before it. An empty score (no points in an elim) is
  // dropped rather than reported as a value.
  function judgesOf(cell) {
    const judges = [];
    cell.querySelectorAll('span[title]').forEach((s) => {
      if (s.children.length) return;
      const title = clean(s.getAttribute('title'));
      const text = clean(s.textContent);
      if (!title) return;
      if (title === text) {
        judges.push({ judge: text, scores: [] });
      } else if (judges.length && text) {
        judges[judges.length - 1].scores.push({ label: title, value: text });
      }
    });
    return judges;
  }

  function blocksOf(container) {
    const blocks = [];
    Array.from(container.children).forEach((el) => {
      if (el.tagName === 'OL' || el.tagName === 'UL') {
        const items = Array.from(el.children).map(textOf).filter(Boolean);
        if (items.length) blocks.push({ type: el.tagName === 'OL' ? 'ordered' : 'bullets', items });
        return;
      }
      const text = textOf(el);
      if (text) blocks.push({ type: 'paragraph', text });
    });
    return blocks;
  }

  // One ballot per <h5>: climb from the judge heading to the block that is a
  // direct child of the feedback cell. Each direct <div> child of that block is
  // one comment box: its first <p> is the box's heading, the rest is the body.
  function feedbackOf(row) {
    const cell = row && row.cells[0];
    if (!cell) return [];
    return Array.from(cell.querySelectorAll('h5')).map((h5) => {
      let ballot = h5;
      while (ballot.parentElement && ballot.parentElement !== cell) ballot = ballot.parentElement;
      const h6 = ballot.querySelector('h6');
      const sections = Array.from(ballot.children).filter((c) => c.tagName === 'DIV').map((box) => {
        const kids = Array.from(box.children);
        const headingEl = kids.find((k) => k.tagName === 'P');
        const blocks = [];
        kids.filter((k) => k !== headingEl).forEach((k) => {
          const inner = blocksOf(k);
          if (inner.length) blocks.push(...inner);
          else if (textOf(k)) blocks.push({ type: 'paragraph', text: textOf(k) });
        });
        return { heading: clean(headingEl && headingEl.textContent), blocks };
      }).filter((s) => s.heading || s.blocks.length);
      return { judge: clean(h5.textContent), label: clean(h6 && h6.textContent), sections };
    });
  }

  function feedbackRowFor(row) {
    const toggle = Array.from(row.querySelectorAll('[onclick]'))
      .map((a) => /toggleView\(['"]([^'"]+)['"]\)/.exec(a.getAttribute('onclick') || ''))
      .find(Boolean);
    const byId = toggle && document.getElementById(toggle[1]);
    if (byId) return byId;
    const next = row.nextElementSibling;
    return next && next.classList.contains('feedback') ? next : null;
  }

  function roundsOf(table, columns) {
    const judgeCol = columns.findIndex((c) => /judge/i.test(c));
    return Array.from(table.tBodies[0].rows).filter((r) => !r.classList.contains('feedback')).map((r) => {
      const cells = Array.from(r.cells);
      const last = judgeCol >= 0 ? judgeCol : cells.length - 1;
      const fields = {};
      cells.forEach((c, i) => {
        if (i !== last) fields[columns[i] || 'col' + (i + 1)] = clean(c.textContent);
      });
      return { fields, judges: judgesOf(cells[last]), feedback: feedbackOf(feedbackRowFor(r)) };
    });
  }

  // The entry's event and code sit in the row just above its table:
  // "Informative Speaking (INF)" | "Your Code: <school code> <competitor name>".
  function entryHeaderFor(table) {
    const m = main();
    let node = table;
    while (node && node !== m) {
      for (let p = node.previousElementSibling; p; p = p.previousElementSibling) {
        const codeEl = Array.from(p.querySelectorAll('span, div')).reverse()
          .find((e) => /^Your Code:/i.test(clean(e.textContent)));
        if (codeEl) {
          const other = Array.from(codeEl.parentElement.children).find((e) => e !== codeEl);
          return {
            event: clean(other && other.textContent),
            code: clean(codeEl.textContent).replace(/^Your Code:\s*/i, ''),
          };
        }
      }
      node = node.parentElement;
    }
    return { event: '', code: '' };
  }

  function extract() {
    const m = main();
    const tournLink = m.querySelector('a[href*="tourn_id="]');
    const h4 = m.querySelector('h4');
    const h6 = Array.from(m.querySelectorAll('h6')).find((e) => !e.closest('table'));
    // The signed-in account is printed in the site header as an element of its
    // own. Matching an address inside the page's running text instead would
    // swallow whatever word follows it.
    const accountEl = Array.from(document.querySelectorAll('span, a, div, li, td'))
      .find((e) => !e.children.length && /^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$/.test(clean(e.textContent)));
    const account = accountEl ? [clean(accountEl.textContent)] : null;
    return {
      student: clean(h4 && h4.textContent),
      tournament: clean(h6 && h6.textContent),
      tourn_id: tournLink ? (/tourn_id=(\d+)/.exec(tournLink.getAttribute('href')) || [])[1] || '' : '',
      account: account ? account[0] : '',
      entries: resultTables().map((t) => {
        const columns = columnsOf(t);
        return Object.assign(entryHeaderFor(t), { columns, rounds: roundsOf(t, columns) });
      }),
    };
  }

  // The history page prints a weekday and a time ("Sat 5:30 PM") and no date.
  // The tournament's own page (/index/tourn/main.mhtml?tourn_id=<n>) carries
  // the dates as a labelled row and the place in the <h5> under the title
  // ("<year> — <city>, <state>/<country>").
  function tournamentInfo() {
    const label = Array.from(document.querySelectorAll('span, td, th, div'))
      .find((e) => !e.children.length && /^Tournament Dates$/i.test(clean(e.textContent)));
    const value = label && Array.from(label.parentElement.children).find((e) => e !== label);
    const h5 = document.querySelector('h5');
    const place = clean(h5 && h5.textContent).replace(/^\d{4}\s*[—–-]\s*/, '');
    return { dates_label: clean(value && value.textContent), location: place };
  }

  window.__tabroom = { extract, tournamentInfo };
})();

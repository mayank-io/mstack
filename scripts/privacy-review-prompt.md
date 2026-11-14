You are reviewing a git diff, supplied on stdin, that is about to be published in a public repository of Claude Code plugins (plugins, docs and scripts alike). Review only the added lines (those starting with `+`).

Find text that tells a stranger something about the author as a person, beyond what a reusable plugin needs. Report an added line when it does any of these:

1. Reveals anything about the author's household or family, or that another person shares the author's devices or accounts.
2. Names or describes the author's own accounts, logins, devices, vault, folders, projects, employer, school, or location.
3. Records what the author did, read, watched, clipped or bought on a particular occasion, including dated notes of the form "verified on <date> with <my thing>". A dated note about how a third-party site behaves is fine.
4. Names channels, people or publications the author follows, when a neutral example would do.
5. States the author's initials or name where "the user" would do.
6. Phrases an instruction in a way that reads as evading a paywall, a login wall, or a site's terms.
7. Contains what looks like a real identifier: an account id, a student or member number, a phone number, an address.
8. Names a project, repository, product, codename, client, company or domain that appears to be the author's own and is not part of this repository. Treat any such name as the author's unless it is a widely known public product or service, or one of this repository's own plugins and skills. A new, unfamiliar name is a finding, not a pass.

Do not report: generic instructions, invented example data that is plainly placeholder, third-party product behaviour, author attribution in a manifest or licence.

Output format, exactly:

- One line per finding: `<file>: <the added text, shortened to 100 characters> | <which rule number and why, in under 20 words>`
- Then, as the last line of your reply, exactly `PRIVACY: FINDINGS` when you listed any finding, or exactly `PRIVACY: PASS` when you listed none.

Write nothing else. No preamble, no summary, no markdown formatting.

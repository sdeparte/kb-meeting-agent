# Writing a KB the agent reads well

The agent answers from excerpts of your knowledge base, not from whole pages, and a small local model trusts what those excerpts say. These rules keep a KB readable that way. Each one comes from a failure measured on a real project (see [benchmarks.md](benchmarks.md)); a large hosted model forgives more of them, a 9B local model few.

To apply them to your own KB, see [Apply with Claude Code](#apply-with-claude-code).

## How the agent reads a KB

- Every Markdown page not excluded by `exclude` is cut into chunks of about 1,500 characters along its headings. A table cut in parts keeps its header row in each part.
- A question is rewritten into up to 3 search queries. Each one searches by keywords and by meaning, both over the chunk's page path, headings and text, and the two rankings are merged. Keyword search matches any word of the query, so words common in the KB ("list", "what") weigh little and the words naming the subject decide. Pages listed in `authoritative` rank higher.
- The 10 best chunks are given to the model. When a chunk is part of a longer section, the whole section is given instead, if it is under 6,000 characters and the excerpts stay under 30,000 characters; otherwise only the chunk. Sections matching `unexpanded_sections` are always given as found.
- The model answers from these excerpts alone. It sees each excerpt's page, headings, status and verification date.

## Rules

### Values

1. **Write a current value in the present, next to its name and unit.** "`SESSION_TIMEOUT_SECONDS`: 120 s; a user is signed out after 120 s without activity". A value spread over two sentences, or given without its unit, is often answered wrong.
2. **Mark any other value as what it is, in the same sentence.** A former value ("formerly 30 s"), a fallback ("20 s, used only when the server sends none"), a planned one ("planned: 45 s"). Asked for a duration, a model answered with a client fallback written as a plain duration, instead of the reference value.
3. **Rewrite a value or a count that changes; don't add the new one beside the old.** A count lives in one place, the list it counts; elsewhere, link to it. Where a past state must stay (a calibration made at some date), describe it without its old number ("the types of that date"). A KB whose catalogue grew by one kept two historical mentions of the old count, and the agent answered with it.
4. **Keep each value in one page, and list that page in `authoritative`.** Other pages name the setting and link to it. Two pages giving a value are two chances to disagree, and the agent flags contradictions against the KB.
5. **When there is no single value, say so where people would look for one.** After a default became a table per level, "what is the default?" got invented single values. One sentence prevents it: "there is no single default: it depends on the level; without a choice the level is Standard, which gives N s". Likewise, a bound (`*_MIN`, `*_MAX`) says it is not a default.

### Lists

6. **Give every list someone may ask for in a meeting a compact table: name, status, a few short columns.** Details go in each item's page, not in the cells. Keep it under about 4,000 characters, so it is read whole. A 10,000-character roadmap table was read as its first 7 rows.
7. **Put the words people say aloud in the table's heading or in the sentence before it.** Rows that say only `[PROD]` and a heading that says "Catalogue of types" share no word with "which features are in production?": such a catalogue was never found, and the agent listed features from other pages. Write "The features in production, and the ones planned:" before the table, or name the page after it (`features/catalogue.md`).
8. **Give the table its own small page or section, not the middle of a long page.** A list inside a 160 KB page competes with every other section of that page, and the page's other chunks crowd the excerpts.
9. **Tag every row's status, with the tags declared in `statuses`.** The agent tells planned and rejected items from what is in production only through these tags.

### Pages and sections

10. **Keep sections under about 6,000 characters.** Above that, split them into sub-sections with explicit headings, each opening with a sentence that says what it covers: a longer section is read only by the chunk that matched, often its first. If a section must stay long, make its first chunk carry the essentials, or the link to them.
11. **Make headings say what the section answers.** "Default cooldown per security level" rather than "Table 3" or "Details": headings are part of what the semantic search matches.
12. **One topic per page.** A page that answers many questions (a long README) ranks for all of them and helps none.

### What the agent should not read

13. **Move dated reports (audits, retrospectives, meeting notes) to a folder listed in `exclude`.** They describe a past state without saying it is past. Excluding them is also what [`exclude`](configuration.md#general) is for.
14. **Put mockup galleries under a heading matched by `unexpanded_sections`** (for example `## Mockup`). Their image links and alt texts fill the excerpts without informing; matched sections are read as found.
15. **Keep the glossary short and current, and point `glossary` to it.** The query-rewriting model reads its first 4,000 characters to map spoken names to identifiers.

## Apply with Claude Code

In a clone of your KB, start [Claude Code](https://claude.com/claude-code) and ask:

```text
Read https://raw.githubusercontent.com/sdeparte/kb-meeting-agent/main/docs/kb-guidelines.md.
Audit this knowledge base against those rules, starting with the pages people ask about most
(roadmap, catalogues, reference values). For each finding give the file, the line, the rule
and the fix. Then:
1. propose the fixes, one pull request per theme, without changing what the KB says;
2. update .meeting-agent.yml (exclude, authoritative, unexpanded_sections, statuses, glossary)
   if the KB needs it;
3. add a short "Readable by the meeting agent" section to the KB's contribution guide or
   CLAUDE.md, adapting these rules to this KB, so that new pages follow them.
```

Measure the effect with your own questions: replay a meeting where they were asked (`kb-meeting-agent replay`), before and after.

# Writing skill acceptance / 总结文字验收

This is a behavioral review, not a word-count or heading test. Use it after changing `skills/summarize-bilibili-video/SKILL.md`. Keep raw evidence, candidate articles and round-specific snapshots under ignored `.state/skill-writing-eval/` on the project drive. Do not publish private source archives, user feedback or conversation history.

## Independent trial

Start a fresh, lighter writer agent with no conversation fork. Give it only the versioned skill, a realistic request specifying reading strength, the source identity and transcript/evidence files, and an isolated output path. The writer must not see the accepted answer, existing notes, evaluation findings or another writer's output. No network, package installation, media download or paid API calls are needed. Reuse an existing environment with temporary files on the project drive.

Test at least two different sources: a short practical explanation with several examples, and a more technical explanation with unfamiliar terms. A second source checks transfer; success on one familiar article alone is insufficient. After a material revision, use a fresh context rather than coaching the writer through its earlier answer. Preserve raw candidate output before review; never silently polish a failed candidate and call it a skill pass.

Record model, reasoning effort and execution mode for every trial. A read-only/API-like run and a writer that can save and reread a draft are different conditions. Changes across these conditions cannot be attributed to the skill alone. Once a source has informed revisions, treat it as an iteration sample, not an untouched holdout. Preserve regressions and failures; one good candidate cannot establish reliable automatic quality.

## Acceptance questions

1. **Source fidelity.** Does each example that adds a distinct issue survive with its important conditions? Are the author's reasoning order, uncertainty and factual details preserved? Trace claims to evidence; invented stories, numbers or causal certainty are a failure.
2. **First-pass clarity.** Can a reader identify the subject, comparison, conditions and causal connection without rereading earlier paragraphs? Record the actual unclear sentence and missing relationship. Word counts cannot establish clarity.
3. **Paragraph continuity.** Does a paragraph remain with one concrete situation long enough to explain it? Does the transition explain why the next question arises? Look for compressed slogans, excessive one- or two-sentence paragraphs, and padding that repeats a conclusion without explaining it.
4. **Voice and language.** Does the article teach directly using a natural narrator, rather than repeatedly describing what a video or author said? Are unfamiliar terms explained in place, ordinary words complete, and personal anecdotes/claims honestly attributed?
5. **Evidence and presentation.** Are timestamps supported, formula/frame syntax preserved, and figures actually inspected? Does each screenshot, diagram or table clarify a specific operation, relationship or comparison beside the relevant explanation? Look for missed opportunities as well as decorative or repetitive images. Useful headings, comparison tables, parallel lists and operating steps are welcome; do not reward fewer structures or let visuals replace developed prose. Missing visual evidence must not be disguised with invented screenshots. The reading product must omit production commentary, correction logs and evidence-note sections, including in captions, footnotes and source metadata. Genuine limits on conclusions still belong beside the affected claims.

For an HTML handoff, also check **product continuity** against a real original learning page: video player, summary/distillation and established review sections, source/resource links, timestamp seeking, collapsible navigation, image zoom and reading font. Test the original full renderer, not only Markdown conversion or the lightweight course shell. If media is absent, verify its honest online/unavailable state and working fallback. A prose-only candidate cannot establish that these functions survived.

A candidate passes only when the five writing areas and any applicable product checks are acceptable on reading the actual article and checking its evidence. Keep the judgment qualitative and disclose reviewer judgment. Mechanical scans may flag short paragraphs, observer phrases, broken timestamps or missing files; they are supporting checks only.

## Review record

Record the skill snapshot, writer model and reasoning effort, source and intensity, candidate path, examples of the observed problems, revision made, and final judgment. Keep one small local review file across rounds. State which modes were not live-tested; a text-only trial does not verify screenshot selection or multi-part synthesis. Run the skill validator and existing renderer/prompt tests separately to catch integration regressions.

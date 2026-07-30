import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

// starlight-llms-txt@0.11.0's `exclude` option (configured alongside this
// integration in astro.config.mjs, as `starlightLlmsTxt({ exclude: [...] })`)
// is read only by its llms-small.txt route: `llms-small.txt.ts` passes
// `exclude: starlightLllmsTxtContext.exclude` into `generateLlmsTxt`, but
// `llms-full.txt.ts` calls the same `generateLlmsTxt` with no exclude/include
// option at all (verified against the package's source under
// `site/node_modules/starlight-llms-txt/`). So the design record still ends
// up in `llms-full.txt`. No plugin option closes that gap today - this
// integration re-opens the built file afterwards and drops the sections that
// came from a `spec/` or `research/` page, matched by the page's rendered
// `<h1>` title (the same string `generateLlmsTxt` uses as that section's `# `
// heading). Keep the `exclude` option configured too - it is already correct
// for `llms-small.txt`, and becomes correct here as well if a future plugin
// release forwards it to `llms-full.txt`.
//
// A first version of this split on a blank line followed by a `# ` heading -
// the boundary `generateLlmsTxt` puts between pages. That broke on a guide
// page whose body quotes a converted file's contents inside a fenced code
// block: the quoted content included a line that happened to look exactly
// like a page boundary, so the split (and then the title-based filter) took
// unrelated real pages down with the excluded ones. `pageSeparator` (below,
// also passed to `starlightLlmsTxt`) sidesteps that: it is a marker no real
// page content will ever contain, so splitting on it is exact.
export const PAGE_SEPARATOR = '\n\n<!-- mdd-llms-txt-page-separator -->\n\n';

export default function excludeDesignRecordFromLlmsFull() {
	return {
		name: 'exclude-design-record-from-llms-full',
		hooks: {
			'astro:build:done': ({ pages, dir }) => {
				const root = fileURLToPath(dir);
				const excludedTitles = new Set();
				for (const { pathname } of pages) {
					if (!pathname.startsWith('spec/') && !pathname.startsWith('research/')) continue;
					const htmlPath = `${root}${pathname}index.html`;
					if (!existsSync(htmlPath)) continue;
					const match = /<h1[^>]*>(.*?)<\/h1>/s.exec(readFileSync(htmlPath, 'utf8'));
					if (match) excludedTitles.add(match[1].replace(/<[^>]+>/g, '').trim());
				}

				// `llms-small.txt` is already correctly filtered by the plugin's
				// own `exclude` option; it only needs the separator cleaned up.
				const smallPath = `${root}llms-small.txt`;
				if (existsSync(smallPath)) {
					writeFileSync(smallPath, readFileSync(smallPath, 'utf8').replaceAll(PAGE_SEPARATOR, '\n\n'));
				}

				const fullPath = `${root}llms-full.txt`;
				if (!existsSync(fullPath)) return;
				const kept = readFileSync(fullPath, 'utf8')
					.split(PAGE_SEPARATOR)
					.filter((section) => !excludedTitles.has(section.slice(2, section.indexOf('\n')).trim()))
					.join('\n\n');
				writeFileSync(fullPath, kept);
			},
		},
	};
}

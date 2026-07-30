// Maps GitHub's alert blockquote syntax (`> [!NOTE]` and friends) onto
// Starlight asides, so a guide page renders natively on GitHub *and* as a
// coloured aside on the site. Starlight has no native support for GitHub
// alerts because the two variant sets do not map one-to-one; the mapping
// below is this project's explicit choice (see S06's "Markdown dialect for
// guide pages"):
//
//   [!NOTE]      -> note
//   [!TIP]       -> tip
//   [!IMPORTANT] -> caution
//   [!WARNING]   -> caution
//   [!CAUTION]   -> danger
//
// Rather than hand-building the `<aside>` HTML (which would duplicate
// Starlight's icons and translations), this rewrites the matched blockquote
// into the same `containerDirective` mdast node shape that `remark-directive`
// produces for `:::note` syntax. Starlight's own `remarkAsides` plugin already
// runs on every page loaded through `docsLoader()` and renders any such node,
// directive-authored or not, identically.

import { visit } from 'unist-util-visit';

const GITHUB_TO_STARLIGHT = {
	NOTE: 'note',
	TIP: 'tip',
	IMPORTANT: 'caution',
	WARNING: 'caution',
	CAUTION: 'danger',
};

const MARKER = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*/;

/** @type {import('unified').Plugin<[], import('mdast').Root>} */
export const remarkGithubAlerts = () => {
	return (tree) => {
		visit(tree, 'blockquote', (node) => {
			const firstParagraph = node.children[0];
			if (!firstParagraph || firstParagraph.type !== 'paragraph') return;
			const firstText = firstParagraph.children[0];
			if (!firstText || firstText.type !== 'text') return;

			const match = MARKER.exec(firstText.value);
			if (!match) return;
			const variant = GITHUB_TO_STARLIGHT[match[1]];

			// Strip the marker from the leading paragraph. Drop the paragraph
			// entirely if the marker was its only content, which is the common
			// case of `> [!NOTE]` on its own line with the body starting on the
			// next blockquote line.
			const rest = firstText.value.slice(match[0].length);
			if (rest.length > 0) {
				firstText.value = rest;
			} else {
				firstParagraph.children.shift();
				if (firstParagraph.children.length === 0) {
					node.children.shift();
				}
			}

			const directive = /** @type {any} */ (node);
			directive.type = 'containerDirective';
			directive.name = variant;
			directive.attributes = {};
		});
	};
};

export default remarkGithubAlerts;

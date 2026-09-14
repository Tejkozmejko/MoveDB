/** @odoo-module **/

/**
 * A small, deliberately incomplete Markdown renderer for chat replies.
 *
 * Claude answers in Markdown, and showing the raw `##` and `**` was the single
 * ugliest thing about the transcript. A full parser is not worth the weight
 * here, so this covers what actually turns up in an answer: fenced code,
 * headings, lists, tables, blockquotes, inline code, bold, italic and links.
 *
 * Safety: every fragment of the source is escaped *before* any tag is added, so
 * the only HTML in the result is the tags this file writes. Link targets are
 * whitelisted to http, https and mailto, which is what keeps a `javascript:`
 * URL out of an href.
 */

import { escapeHtml, highlight } from "./claude_highlight";

/** Fence languages mapped onto a filename, which is what `highlight` keys on. */
const FENCE_FILENAMES = {
    py: "s.py", python: "s.py", python3: "s.py",
    js: "s.js", javascript: "s.js", node: "s.js",
    xml: "s.xml", html: "s.html", odoo: "s.xml",
    css: "s.css", scss: "s.scss",
    json: "s.json",
    csv: "s.csv",
};

const HEADING = /^(#{1,6})\s+(.*)$/;
const FENCE = /^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$/;
const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const NUMBERED = /^(\s*)(\d{1,3})[.)]\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const TABLE_DIVIDER = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

/** Inline code is pulled out first so `**` inside it stays literal. */
const CODE_SPAN = /`([^`\n]+)`/g;
const PLACEHOLDER = "\u0000";

const LINK = /\[([^\]\n]*)\]\(((?:https?:\/\/|mailto:)[^\s)]+)\)/g;
const BARE_URL = /(^|[\s(])(https?:\/\/[^\s<>()]+[^\s<>().,;:!?])/g;
const BOLD = /\*\*([^\n]+?)\*\*/g;
const BOLD_ALT = /__([^\n_]+?)__/g;
const ITALIC = /(^|[^*\w])\*([^*\n]+?)\*/g;
const ITALIC_ALT = /(^|[^_\w])_([^_\n]+?)_/g;
const STRIKE = /~~([^~\n]+?)~~/g;

/** One anchor, with the only link attributes this renderer ever emits. */
function anchor(href, label) {
    return `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
}

/**
 * Escape `raw`, then turn the inline Markdown in it into tags.
 *
 * Code spans and finished anchors are stashed behind placeholders before the
 * emphasis rules run. Without that, `target="_blank"` is a pair of underscores
 * as far as the italic rule is concerned, and every link comes out broken.
 */
function inline(raw) {
    const kept = [];
    const keep = (html) => `${PLACEHOLDER}${kept.push(html) - 1}${PLACEHOLDER}`;

    const stashed = String(raw).replace(CODE_SPAN, (_match, code) =>
        keep(`<code>${escapeHtml(code)}</code>`)
    );

    // escapeHtml leaves "/" alone, so URLs survive intact and stay matchable.
    let html = escapeHtml(stashed);
    html = html.replace(LINK, (_match, label, href) =>
        keep(anchor(href, label || href))
    );
    html = html.replace(BARE_URL, (_match, lead, href) =>
        `${lead}${keep(anchor(href, href))}`
    );

    html = html.replace(BOLD, "<strong>$1</strong>");
    html = html.replace(BOLD_ALT, "<strong>$1</strong>");
    html = html.replace(STRIKE, "<del>$1</del>");
    html = html.replace(ITALIC, "$1<em>$2</em>");
    html = html.replace(ITALIC_ALT, "$1<em>$2</em>");

    // A stashed anchor can hold a stashed code span, so restore until settled.
    const token = new RegExp(`${PLACEHOLDER}(\\d+)${PLACEHOLDER}`, "g");
    for (let pass = 0; pass < 4 && token.test(html); pass += 1) {
        token.lastIndex = 0;
        html = html.replace(token, (_match, index) => kept[Number(index)] ?? "");
    }
    return html;
}

function codeBlock(body, language) {
    const label = String(language || "").toLowerCase();
    const filename = FENCE_FILENAMES[label];
    const code = filename ? highlight(body, filename) : escapeHtml(body);
    const caption = label
        ? `<span class="o_cc_md_code_lang">${escapeHtml(label)}</span>`
        : "";
    return `<div class="o_cc_md_code">${caption}<pre><code>${code}</code></pre></div>`;
}

/** Split a table row on unescaped pipes, dropping the leading/trailing ones. */
function tableCells(line) {
    const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return trimmed.split("|").map((cell) => cell.trim());
}

function table(headerLine, rows) {
    const head = tableCells(headerLine)
        .map((cell) => `<th>${inline(cell)}</th>`)
        .join("");
    const body = rows
        .map(
            (row) =>
                `<tr>${tableCells(row)
                    .map((cell) => `<td>${inline(cell)}</td>`)
                    .join("")}</tr>`
        )
        .join("");
    return `<div class="o_cc_md_table"><table><thead><tr>${head}</tr></thead>` +
        `<tbody>${body}</tbody></table></div>`;
}

/**
 * Render `source` as HTML.
 * The caller is responsible for wrapping the result in `markup()`.
 */
export function renderMarkdown(source) {
    const text = String(source ?? "")
        .replace(/\u0000/g, "")
        .replace(/\r\n?/g, "\n");
    const lines = text.split("\n");
    const out = [];
    let index = 0;

    while (index < lines.length) {
        const line = lines[index];

        if (!line.trim()) {
            index += 1;
            continue;
        }

        const fence = line.match(FENCE);
        if (fence) {
            const marker = fence[1][0];
            const closing = new RegExp(`^\\s*\\${marker}{3,}\\s*$`);
            const body = [];
            index += 1;
            while (index < lines.length && !closing.test(lines[index])) {
                body.push(lines[index]);
                index += 1;
            }
            index += 1; // step over the closing fence, if there was one
            out.push(codeBlock(body.join("\n"), fence[2]));
            continue;
        }

        const heading = line.match(HEADING);
        if (heading) {
            // Cap at h6 and start at h4: these sit inside a chat bubble, not at
            // the top of a document, so an h1 would tower over the page.
            const level = Math.min(6, heading[1].length + 3);
            out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
            index += 1;
            continue;
        }

        if (RULE.test(line)) {
            out.push("<hr/>");
            index += 1;
            continue;
        }

        // A table is a header row plus a |---|---| divider on the next line.
        if (
            line.includes("|") &&
            index + 1 < lines.length &&
            TABLE_DIVIDER.test(lines[index + 1])
        ) {
            const header = line;
            index += 2;
            const rows = [];
            while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
                rows.push(lines[index]);
                index += 1;
            }
            out.push(table(header, rows));
            continue;
        }

        if (QUOTE.test(line)) {
            const body = [];
            while (index < lines.length && QUOTE.test(lines[index])) {
                body.push(lines[index].match(QUOTE)[1]);
                index += 1;
            }
            out.push(`<blockquote>${inline(body.join("\n")).replace(/\n/g, "<br/>")}</blockquote>`);
            continue;
        }

        if (BULLET.test(line) || NUMBERED.test(line)) {
            const ordered = !BULLET.test(line);
            const items = [];
            while (index < lines.length) {
                const item = lines[index].match(ordered ? NUMBERED : BULLET);
                if (!item) {
                    break;
                }
                const parts = [ordered ? item[3] : item[2]];
                index += 1;
                // A wrapped list item: an indented continuation line that is not
                // itself a new bullet.
                while (
                    index < lines.length &&
                    lines[index].trim() &&
                    /^\s{2,}\S/.test(lines[index]) &&
                    !BULLET.test(lines[index]) &&
                    !NUMBERED.test(lines[index]) &&
                    !FENCE.test(lines[index])
                ) {
                    parts.push(lines[index].trim());
                    index += 1;
                }
                items.push(`<li>${inline(parts.join(" "))}</li>`);
            }
            const tag = ordered ? "ol" : "ul";
            out.push(`<${tag}>${items.join("")}</${tag}>`);
            continue;
        }

        // Anything else is a paragraph, running until a blank line or a block
        // that starts on its own.
        const paragraph = [];
        while (
            index < lines.length &&
            lines[index].trim() &&
            !FENCE.test(lines[index]) &&
            !HEADING.test(lines[index]) &&
            !RULE.test(lines[index]) &&
            !QUOTE.test(lines[index]) &&
            !BULLET.test(lines[index]) &&
            !NUMBERED.test(lines[index])
        ) {
            paragraph.push(lines[index]);
            index += 1;
        }
        out.push(`<p>${inline(paragraph.join("\n")).replace(/\n/g, "<br/>")}</p>`);
    }

    return out.join("");
}

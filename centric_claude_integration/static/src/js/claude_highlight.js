/** @odoo-module **/

/**
 * A small, dependency-free syntax highlighter for the workspace editor.
 *
 * Odoo ships no code-highlighting library on the web client bundle, and pulling
 * one in for a read-only viewer is not worth the weight. This covers the file
 * types an Odoo module actually contains: Python, XML, JavaScript, SCSS/CSS,
 * JSON and CSV.
 *
 * Everything is escaped before any markup is added, and the only markup ever
 * produced is `<span class="tok-*">`, so repository content cannot inject HTML.
 */

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(text) {
    return String(text ?? "").replace(/[&<>"']/g, (char) => ESCAPES[char]);
}

function span(className, text) {
    return `<span class="${className}">${escapeHtml(text)}</span>`;
}

const PY_CONTROL = new Set([
    "if", "elif", "else", "for", "while", "break", "continue", "return", "yield",
    "try", "except", "finally", "raise", "with", "pass", "assert", "await",
]);
const PY_KEYWORD = new Set([
    "def", "class", "import", "from", "as", "in", "is", "not", "and", "or",
    "lambda", "global", "nonlocal", "del", "async", "None", "True", "False",
    "self", "super",
]);

const JS_CONTROL = new Set([
    "if", "else", "for", "while", "do", "switch", "case", "default", "break",
    "continue", "return", "throw", "try", "catch", "finally", "await", "yield",
]);
const JS_KEYWORD = new Set([
    "const", "let", "var", "function", "class", "extends", "new", "this",
    "import", "export", "from", "as", "async", "typeof", "instanceof", "in",
    "of", "delete", "void", "null", "undefined", "true", "false", "static",
    "get", "set", "super",
]);

/**
 * Walk `text` with `pattern`, handing each match to `render` and escaping
 * everything in between. `pattern` must be sticky-free and global.
 */
function scan(text, pattern, render) {
    let out = "";
    let last = 0;
    let match;
    pattern.lastIndex = 0;
    while ((match = pattern.exec(text)) !== null) {
        // A zero-length match would spin forever; nudge past it.
        if (match.index === pattern.lastIndex) {
            pattern.lastIndex += 1;
            continue;
        }
        out += escapeHtml(text.slice(last, match.index));
        out += render(match);
        last = match.index + match[0].length;
    }
    return out + escapeHtml(text.slice(last));
}

function highlightPython(text) {
    const pattern = new RegExp(
        [
            "(#[^\\n]*)",                                              // 1 comment
            "('''[\\s\\S]*?'''|\"\"\"[\\s\\S]*?\"\"\")",               // 2 docstring
            "([rbfu]{0,2}'(?:\\\\.|[^'\\\\\\n])*'|[rbfu]{0,2}\"(?:\\\\.|[^\"\\\\\\n])*\")", // 3 string
            "(@[A-Za-z_][\\w.]*)",                                     // 4 decorator
            "\\b(\\d[\\d_]*(?:\\.\\d+)?(?:[eE][-+]?\\d+)?)\\b",        // 5 number
            "\\b(def|class)\\s+([A-Za-z_]\\w*)",                       // 6 kw + 7 name
            "\\b([A-Za-z_]\\w*)\\b",                                   // 8 word
        ].join("|"),
        "g"
    );
    return scan(text, pattern, (match) => {
        if (match[1]) return span("tok-comment", match[1]);
        if (match[2]) return span("tok-string", match[2]);
        if (match[3]) return span("tok-string", match[3]);
        if (match[4]) return span("tok-decorator", match[4]);
        if (match[5]) return span("tok-number", match[5]);
        if (match[6]) {
            const cls = match[6] === "class" ? "tok-class" : "tok-def";
            return `${span("tok-keyword", match[6])} ${span(cls, match[7])}`;
        }
        const word = match[8];
        if (PY_CONTROL.has(word)) return span("tok-control", word);
        if (PY_KEYWORD.has(word)) return span("tok-keyword", word);
        return escapeHtml(word);
    });
}

function highlightJs(text) {
    const pattern = new RegExp(
        [
            "(\\/\\*[\\s\\S]*?\\*\\/|\\/\\/[^\\n]*)",                  // 1 comment
            "(`(?:\\\\.|[^`\\\\])*`|'(?:\\\\.|[^'\\\\\\n])*'|\"(?:\\\\.|[^\"\\\\\\n])*\")", // 2 string
            "\\b(\\d[\\d_]*(?:\\.\\d+)?)\\b",                          // 3 number
            "\\b(function|class)\\s+([A-Za-z_$][\\w$]*)",              // 4 kw + 5 name
            "\\b([A-Za-z_$][\\w$]*)\\b",                               // 6 word
        ].join("|"),
        "g"
    );
    return scan(text, pattern, (match) => {
        if (match[1]) return span("tok-comment", match[1]);
        if (match[2]) return span("tok-string", match[2]);
        if (match[3]) return span("tok-number", match[3]);
        if (match[4]) {
            const cls = match[4] === "class" ? "tok-class" : "tok-def";
            return `${span("tok-keyword", match[4])} ${span(cls, match[5])}`;
        }
        const word = match[6];
        if (JS_CONTROL.has(word)) return span("tok-control", word);
        if (JS_KEYWORD.has(word)) return span("tok-keyword", word);
        return escapeHtml(word);
    });
}

function highlightXml(text) {
    const pattern = new RegExp(
        [
            "(<!--[\\s\\S]*?-->)",                                     // 1 comment
            "(<\\?[\\s\\S]*?\\?>)",                                    // 2 declaration
            "(<\\/?)([A-Za-z_][\\w:.-]*)",                             // 3 punct + 4 tag
            "([A-Za-z_][\\w:.-]*)(=)(\"[^\"]*\"|'[^']*')",             // 5 attr 6 eq 7 value
            "(\\/?>)",                                                 // 8 punct
        ].join("|"),
        "g"
    );
    return scan(text, pattern, (match) => {
        if (match[1]) return span("tok-comment", match[1]);
        if (match[2]) return span("tok-decorator", match[2]);
        if (match[3]) return span("tok-punct", match[3]) + span("tok-tag", match[4]);
        if (match[5]) {
            return span("tok-attr", match[5]) + span("tok-punct", match[6]) +
                span("tok-string", match[7]);
        }
        return span("tok-punct", match[8]);
    });
}

function highlightCss(text) {
    const pattern = new RegExp(
        [
            "(\\/\\*[\\s\\S]*?\\*\\/|\\/\\/[^\\n]*)",                  // 1 comment
            "('[^'\\n]*'|\"[^\"\\n]*\")",                              // 2 string
            "(#[0-9a-fA-F]{3,8}\\b)",                                  // 3 colour
            "(\\$[\\w-]+|--[\\w-]+)",                                  // 4 variable
            "(@[\\w-]+)",                                              // 5 at-rule
            "\\b(\\d[\\d.]*)(px|rem|em|%|vh|vw|s|ms|deg)?\\b",         // 6 number 7 unit
        ].join("|"),
        "g"
    );
    return scan(text, pattern, (match) => {
        if (match[1]) return span("tok-comment", match[1]);
        if (match[2]) return span("tok-string", match[2]);
        if (match[3]) return span("tok-number", match[3]);
        if (match[4]) return span("tok-attr", match[4]);
        if (match[5]) return span("tok-control", match[5]);
        return span("tok-number", match[6] + (match[7] || ""));
    });
}

function highlightJson(text) {
    const pattern = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d[\d.eE+-]*)/g;
    return scan(text, pattern, (match) => {
        if (match[1]) {
            // A string followed by a colon is a key, not a value.
            return match[2]
                ? span("tok-attr", match[1]) + span("tok-punct", match[2])
                : span("tok-string", match[1]);
        }
        if (match[3]) return span("tok-keyword", match[3]);
        return span("tok-number", match[4]);
    });
}

function highlightCsv(text) {
    return scan(text, /("(?:[^"]|"")*")|(^[^\n,]+)/gm, (match) =>
        match[1] ? span("tok-string", match[1]) : span("tok-attr", match[2])
    );
}

/** Map a file name to a highlighter key. */
export function languageOf(path) {
    const name = String(path || "").toLowerCase();
    const dot = name.lastIndexOf(".");
    const ext = dot === -1 ? "" : name.slice(dot + 1);
    switch (ext) {
        case "py": return "python";
        case "xml": case "html": case "jinja": return "xml";
        case "js": return "javascript";
        case "scss": case "css": return "css";
        case "json": return "json";
        case "csv": return "csv";
        default: return "text";
    }
}

const HIGHLIGHTERS = {
    python: highlightPython,
    xml: highlightXml,
    javascript: highlightJs,
    css: highlightCss,
    json: highlightJson,
    csv: highlightCsv,
};

/**
 * Return highlighted HTML for `code`. Falls back to plain escaped text for
 * unknown languages, and for very large files where tokenising would stall the
 * browser more than it would help.
 */
export function highlight(code, path) {
    const text = String(code ?? "");
    const language = languageOf(path);
    const handler = HIGHLIGHTERS[language];
    if (!handler || text.length > 400000) {
        return escapeHtml(text);
    }
    try {
        return handler(text);
    } catch {
        // A highlighter bug must never cost the user sight of their file.
        return escapeHtml(text);
    }
}

/** Colour a unified diff line by line. */
export function highlightDiff(diffText) {
    const lines = String(diffText ?? "").split("\n");
    return lines
        .map((line) => {
            if (line.startsWith("+++") || line.startsWith("---")) {
                return span("diff-meta", line || " ");
            }
            if (line.startsWith("@@")) return span("diff-hunk", line || " ");
            if (line.startsWith("+")) return span("diff-add", line || " ");
            if (line.startsWith("-")) return span("diff-del", line || " ");
            return escapeHtml(line || " ");
        })
        .join("\n");
}

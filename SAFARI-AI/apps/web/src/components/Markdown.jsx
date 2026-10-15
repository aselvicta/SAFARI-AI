// A small, safe Markdown renderer for answers. It builds React elements only:
// paragraphs, headings, - and 1. lists, **bold**, *italic*, `code`, http(s) links,
// bare URLs and [n] citation markers. Anything else stays literal text.

const INLINE = new RegExp(
  [
    String.raw`\*\*(?<bold>[^*]+?)\*\*`,
    String.raw`\[(?<label>[^\]]+)\]\((?<href>https?:\/\/[^\s)]+)\)`,
    String.raw`\[(?<cite>\d{1,2})\]`,
    String.raw`(?<url>https?:\/\/[^\s<>()]+)`,
    String.raw`\x60(?<code>[^\x60]+)\x60`,
    String.raw`(?<![\w*])\*(?<italic>[^*\s][^*]*?)\*(?![\w*])`,
  ].join("|"),
  "g",
);

function trimUrl(url) {
  const match = url.match(/[.,;:!?'"]+$/);
  if (!match) return [url, ""];
  return [url.slice(0, -match[0].length), match[0]];
}

function ExternalLink({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

function renderInline(text, onCite, keyPrefix = "i") {
  const nodes = [];
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const key = `${keyPrefix}-${index++}`;
    const groups = match.groups;
    if (groups.bold !== undefined) {
      nodes.push(<strong key={key}>{renderInline(groups.bold, onCite, key)}</strong>);
    } else if (groups.href !== undefined) {
      nodes.push(
        <ExternalLink key={key} href={groups.href}>
          {groups.label}
        </ExternalLink>,
      );
    } else if (groups.cite !== undefined) {
      const number = Number(groups.cite);
      nodes.push(
        <button
          key={key}
          type="button"
          className="cite-chip"
          onClick={() => onCite?.(number)}
          aria-label={`Source ${number}`}
        >
          {number}
        </button>,
      );
    } else if (groups.url !== undefined) {
      const [url, tail] = trimUrl(groups.url);
      nodes.push(
        <ExternalLink key={key} href={url}>
          {url.replace(/^https?:\/\/(www\.)?/, "")}
        </ExternalLink>,
      );
      if (tail) nodes.push(tail);
    } else if (groups.code !== undefined) {
      nodes.push(<code key={key}>{groups.code}</code>);
    } else if (groups.italic !== undefined) {
      nodes.push(<em key={key}>{groups.italic}</em>);
    }
    last = match.index + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

const BULLET = /^\s*[-*•]\s+(.*)$/;
const ORDERED = /^\s*(\d+)[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,4}\s+(.*)$/;

function parseBlocks(source) {
  const blocks = [];
  let paragraph = [];
  let list = null;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ type: "p", lines: paragraph });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push(list);
    list = null;
  };

  for (const line of source.replace(/\r\n/g, "\n").split("\n")) {
    const bullet = line.match(BULLET);
    const ordered = line.match(ORDERED);
    const heading = line.match(HEADING);
    if (!line.trim()) {
      flushParagraph();
      flushList();
    } else if (heading) {
      flushParagraph();
      flushList();
      blocks.push({ type: "h", text: heading[1] });
    } else if (bullet || ordered) {
      flushParagraph();
      const type = bullet ? "ul" : "ol";
      if (!list || list.type !== type) {
        flushList();
        list = { type, items: [], start: ordered ? Number(ordered[1]) : 1 };
      }
      list.items.push(bullet ? bullet[1] : ordered[2]);
    } else if (list && /^\s{2,}\S/.test(line)) {
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}

export default function Markdown({ text, onCite }) {
  if (!text) return null;
  return (
    <div className="markdown">
      {parseBlocks(text).map((block, blockIndex) => {
        const key = `b${blockIndex}`;
        if (block.type === "h") return <h4 key={key}>{renderInline(block.text, onCite, key)}</h4>;
        if (block.type === "ul" || block.type === "ol") {
          const Tag = block.type;
          return (
            <Tag key={key} start={block.type === "ol" && block.start !== 1 ? block.start : undefined}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}-${itemIndex}`}>{renderInline(item, onCite, `${key}-${itemIndex}`)}</li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={key}>
            {block.lines.map((line, lineIndex) => (
              <span key={`${key}-${lineIndex}`}>
                {lineIndex > 0 ? <br /> : null}
                {renderInline(line, onCite, `${key}-${lineIndex}`)}
              </span>
            ))}
          </p>
        );
      })}
    </div>
  );
}

import { Fragment, type ReactNode } from "react";
import { Link } from "react-router";

const inlinePattern = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`/g;

function isInternal(href: string) {
  return href.startsWith("/") && !href.startsWith("//");
}

function isSafeExternal(href: string) {
  return /^(https?:|mailto:)/i.test(href);
}

function renderLink(label: string, href: string, key: number): ReactNode {
  if (isInternal(href)) {
    return (
      <Link key={key} to={href}>
        {label}
      </Link>
    );
  }
  if (isSafeExternal(href)) {
    return (
      <a key={key} href={href} target="_blank" rel="noopener noreferrer">
        {label}
      </a>
    );
  }
  return <Fragment key={key}>{label}</Fragment>;
}

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let index = 0;
  for (const match of text.matchAll(inlinePattern)) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const [, linkLabel, href, bold, italic, code] = match;
    index += 1;
    if (linkLabel !== undefined) nodes.push(renderLink(linkLabel, href, index));
    else if (bold !== undefined) nodes.push(<strong key={index}>{bold}</strong>);
    else if (italic !== undefined) nodes.push(<em key={index}>{italic}</em>);
    else nodes.push(<code key={index}>{code}</code>);
    last = match.index + match[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

type Block =
  | { type: "heading"; level: 2 | 3 | 4; text: string }
  | { type: "paragraph"; text: string }
  | { type: "quote"; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "rule" };

const headingLine = /^(#{1,4})\s+(.*)$/;
const bulletLine = /^\s*[-*]\s+(.*)$/;
const orderedLine = /^\s*\d+[.)]\s+(.*)$/;
const quoteLine = /^>\s?(.*)$/;
const ruleLine = /^(-{3,}|\*{3,})$/;

function parse(source: string): Block[] {
  const blocks: Block[] = [];
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length > 0) blocks.push({ type: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };

  for (const line of lines) {
    const trimmed = line.trim();
    const heading = headingLine.exec(trimmed);
    const bullet = bulletLine.exec(line);
    const ordered = orderedLine.exec(line);
    const quote = quoteLine.exec(trimmed);
    const last = blocks[blocks.length - 1];

    if (trimmed === "") {
      flush();
    } else if (heading) {
      flush();
      const level = Math.min(Math.max(heading[1].length, 2), 4) as 2 | 3 | 4;
      blocks.push({ type: "heading", level, text: heading[2] });
    } else if (ruleLine.test(trimmed)) {
      flush();
      blocks.push({ type: "rule" });
    } else if (bullet || ordered) {
      flush();
      const isOrdered = Boolean(ordered);
      const text = (bullet ?? ordered)![1];
      if (last?.type === "list" && last.ordered === isOrdered) last.items.push(text);
      else blocks.push({ type: "list", ordered: isOrdered, items: [text] });
    } else if (quote) {
      flush();
      if (last?.type === "quote") last.text += ` ${quote[1]}`;
      else blocks.push({ type: "quote", text: quote[1] });
    } else {
      paragraph.push(trimmed);
    }
  }
  flush();
  return blocks;
}

export function Markdown({ source }: { source: string }) {
  return (
    <>
      {parse(source).map((block, index) => {
        switch (block.type) {
          case "heading": {
            const Tag = `h${block.level}` as const;
            return <Tag key={index}>{renderInline(block.text)}</Tag>;
          }
          case "paragraph":
            return <p key={index}>{renderInline(block.text)}</p>;
          case "quote":
            return <blockquote key={index}>{renderInline(block.text)}</blockquote>;
          case "rule":
            return <hr key={index} />;
          case "list": {
            const Tag = block.ordered ? "ol" : "ul";
            return (
              <Tag key={index}>
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{renderInline(item)}</li>
                ))}
              </Tag>
            );
          }
        }
      })}
    </>
  );
}

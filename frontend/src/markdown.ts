/**
 * 极简的 Markdown 子集解析：粗体、行内代码、标题、无序列表。
 *
 * 刻意只产出**结构化片段**，由组件用普通的文本插值渲染（`{{ }}` / `<strong>`），
 * 全程不生成 HTML 字符串、不使用 `v-html`——所以既不用做净化，也不存在
 * "净化漏了一处就被注入"的风险。模型的回答是外部输入，这一层边界必须守住。
 */

export type BlockKind = 'paragraph' | 'bullet' | 'heading'

export interface Segment {
  text: string
  bold?: boolean
  code?: boolean
}

export interface Block {
  kind: BlockKind
  segments: Segment[]
}

/** 行内标记：`**粗体**` 与 `` `代码` ``。非贪婪，且不允许跨行。 */
const INLINE = /\*\*([^\n]+?)\*\*|`([^`\n]+)`/g

function parseInline(text: string): Segment[] {
  const segments: Segment[] = []
  let cursor = 0
  let match: RegExpExecArray | null
  INLINE.lastIndex = 0
  while ((match = INLINE.exec(text)) !== null) {
    if (match.index > cursor) {
      segments.push({ text: text.slice(cursor, match.index) })
    }
    if (match[1] !== undefined) {
      segments.push({ text: match[1], bold: true })
    } else {
      segments.push({ text: match[2], code: true })
    }
    cursor = match.index + match[0].length
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor) })
  }
  return segments.filter((segment) => segment.text.length > 0)
}

/**
 * 落单的 `**`（数量为奇数）没法配对，留着就会原样显示成星号。
 * 把最后那个多余的去掉，宁可少一个粗体，也不要让回答里冒出 `**`。
 */
function dropUnmatchedBold(line: string): string {
  const marks = line.match(/\*\*/g)
  if (!marks || marks.length % 2 === 0) return line
  const last = line.lastIndexOf('**')
  return line.slice(0, last) + line.slice(last + 2)
}

export function parseRichText(text: string): Block[] {
  const blocks: Block[] = []
  const lines = (text || '').replace(/\r\n?/g, '\n').split('\n')
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) continue

    const heading = /^#{1,6}\s+(.*)$/.exec(line)
    if (heading) {
      blocks.push({ kind: 'heading', segments: parseInline(dropUnmatchedBold(heading[1])) })
      continue
    }

    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line)
    if (bullet) {
      blocks.push({ kind: 'bullet', segments: parseInline(dropUnmatchedBold(bullet[1])) })
      continue
    }

    blocks.push({ kind: 'paragraph', segments: parseInline(dropUnmatchedBold(line)) })
  }
  return blocks
}

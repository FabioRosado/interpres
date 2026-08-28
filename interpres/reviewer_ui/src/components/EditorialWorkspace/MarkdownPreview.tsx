import { markdownToSafeHtml } from '../../lib/markdown';

interface Props {
  markdown: string;
}

export const MarkdownPreview = ({ markdown }: Props) => (
  <article className="markdown-preview" aria-label="Rendered Markdown preview" dangerouslySetInnerHTML={{ __html: markdownToSafeHtml(markdown) }} />
);

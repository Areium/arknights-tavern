import Markdown from "react-markdown";

interface Props {
  content: string;
}

const baseClasses = {
  h1: "text-2xl font-bold text-gray-100 mt-6 mb-3 border-b border-gray-700 pb-1",
  h2: "text-xl font-semibold text-gray-100 mt-5 mb-2 border-b border-gray-700/50 pb-1",
  h3: "text-lg font-semibold text-gray-200 mt-4 mb-2",
  h4: "text-base font-medium text-gray-200 mt-3 mb-1",
  h5: "text-sm font-medium text-gray-300 mt-3 mb-1",
  h6: "text-xs font-medium text-gray-400 mt-3 mb-1",
  p: "text-sm text-gray-300 leading-relaxed mb-2",
  ul: "text-sm text-gray-300 list-disc pl-6 mb-2 space-y-0.5",
  ol: "text-sm text-gray-300 list-decimal pl-6 mb-2 space-y-0.5",
  li: "pl-1",
  blockquote: "border-l-4 border-blue-600/40 pl-4 py-1 my-2 text-gray-400 italic bg-gray-800/30 rounded-r",
  code: "font-mono text-xs bg-gray-800 text-amber-400 px-1.5 py-0.5 rounded md-code-inline",
  pre: "font-mono text-xs bg-gray-900 text-gray-300 rounded-lg p-4 mb-3 overflow-x-auto border border-gray-700 md-pre-block",
  a: "text-blue-400 hover:text-blue-300 underline",
  hr: "border-gray-700 my-4",
  table: "text-sm text-gray-300 w-full mb-3 border-collapse",
  thead: "bg-gray-800",
  th: "border border-gray-600 px-3 py-1.5 text-left font-semibold text-gray-200",
  td: "border border-gray-600 px-3 py-1.5",
  img: "max-w-full rounded",
  em: "italic",
  strong: "font-bold text-gray-100",
  del: "line-through text-gray-500",
};

export default function MarkdownRenderer({ content }: Props) {
  if (!content || !content.trim()) {
    return <p className="text-sm text-gray-600 italic">（空文档）</p>;
  }

  return (
    <div className="prose-sm max-w-none">
      <Markdown
        components={{
          h1: (props) => <h1 className={baseClasses.h1} {...props} />,
          h2: (props) => <h2 className={baseClasses.h2} {...props} />,
          h3: (props) => <h3 className={baseClasses.h3} {...props} />,
          h4: (props) => <h4 className={baseClasses.h4} {...props} />,
          h5: (props) => <h5 className={baseClasses.h5} {...props} />,
          h6: (props) => <h6 className={baseClasses.h6} {...props} />,
          p: (props) => <p className={baseClasses.p} {...props} />,
          ul: (props) => <ul className={baseClasses.ul} {...props} />,
          ol: (props) => <ol className={baseClasses.ol} {...props} />,
          li: (props) => <li className={baseClasses.li} {...props} />,
          blockquote: (props) => <blockquote className={baseClasses.blockquote} {...props} />,
          code: (props) => {
            const { className, children, ...rest } = props as any;
            const match = /language-(\w+)/.exec(className || "");
            // Inline code (no language class) vs code block
            if (!match) {
              return <code className={baseClasses.code} {...props} />;
            }
            return (
              <pre className={baseClasses.pre}>
                <code className={className} {...rest}>{children}</code>
              </pre>
            );
          },
          pre: (props) => <pre className={baseClasses.pre} {...props} />,
          a: (props) => <a className={baseClasses.a} target="_blank" rel="noopener noreferrer" {...props} />,
          hr: (props) => <hr className={baseClasses.hr} {...props} />,
          table: (props) => <table className={baseClasses.table} {...props} />,
          thead: (props) => <thead className={baseClasses.thead} {...props} />,
          th: (props) => <th className={baseClasses.th} {...props} />,
          td: (props) => <td className={baseClasses.td} {...props} />,
          img: (props) => <img className={baseClasses.img} {...props} />,
          em: (props) => <em className={baseClasses.em} {...props} />,
          strong: (props) => <strong className={baseClasses.strong} {...props} />,
          del: (props) => <del className={baseClasses.del} {...props} />,
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}

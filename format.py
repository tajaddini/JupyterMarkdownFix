import json
import re
import uuid
import argparse
import sys
from pathlib import Path
from markdownify import markdownify as md


# CSS blocks

CSS_BASE = """/* common, general formats */
.rtl-markdown-container {
    direction: rtl;
    text-align: right;
    font-size: 18px;
    line-height: 2;
    font-family: Vazirmatn, IRANSans, sans-serif;
    width: 100%;
}"""

CSS_TABLE = """/* table formats */
.rtl-markdown-container table {
        direction: rtl;
        text-align: right;
        margin-left: auto;
        margin-right: 0;
}

.rtl-markdown-container th, 
.rtl-markdown-container td {
    text-align: center !important;
    direction: rtl;
    font-family: 'Vazirmatn', 'IRANSans', Tahoma, Arial, sans-serif;
}

.rtl-markdown-container th:first-child, 
.rtl-markdown-container td:first-child {
    text-align: right !important;
}"""

CSS_MATH = """/* format maths */
.rtl-markdown-container .math,
.rtl-markdown-container .math-inline,
.rtl-markdown-container .katex,
.rtl-markdown-container .MathJax,
.rtl-markdown-container mjx-container {
    direction: ltr !important;
    text-align: left !important;
    display: inline-block;
}

.rtl-markdown-container .math-display,
.rtl-markdown-container .katex-display,
.rtl-markdown-container .MathJax_Display,
.rtl-markdown-container div.math,
.rtl-markdown-container div.mjx-container {
    display: block !important;
    text-align: center !important;
}"""

CSS_CODE = """/* format code */
.rtl-markdown-container code,
.rtl-markdown-container pre {
    font-family: 'Vazir Code', 'Cascadia Code', Consolas, 'Courier New', monospace !important;
    direction: ltr !important;
}

.rtl-markdown-container code {
    unicode-bidi: embed; 
}

.rtl-markdown-container pre {
    text-align: left !important;
    display: block !important;
    overflow-x: auto; 
    padding: 10px;
}"""



def clean_legacy_wrappers(source):
    # in case of processing the same file twice, remove previously injected wrappers and styles
    source = re.sub(r'<style>.*?</style>\s*', '', source, flags=re.DOTALL)
    source = re.sub(r'<div class="rtl-markdown-container">\s*(.*?)\s*</div>\s*$', r'\1', source, flags=re.DOTALL)
    return source.strip()

def protect_math(text):
    # temporarily replace LaTeX math with safe placeholders so markdownify doesn't escape or ruin it
    math_blocks = {}
    # matches $$...$$, $...$, \begin{...}...\end{...}, \[...\], \(...\)
    # smart enough to not detect something like "$5 and $10"
    pattern = r'(\$\$.*?\$\$|\$(?!\s).*?(?<!\s)\$|\\begin\{.*?\}.*?\\end\{.*?\}|\\\[.*?\\\]|\\\(.*?\\\))'

    def replacer(match):
        placeholder = f"MATHPLACEHOLDER{uuid.uuid4().hex}"
        math_blocks[placeholder] = match.group(1)
        return placeholder
        
    protected_text = re.sub(pattern, replacer, text, flags=re.DOTALL)
    return protected_text, math_blocks

def restore_math(text, math_blocks):
    # lookup for better performance on math-heavy cells
    if not math_blocks:
        return text
    pattern = re.compile('|'.join(re.escape(k) for k in math_blocks))
    return pattern.sub(lambda m: math_blocks[m.group(0)], text)

def build_smart_style_tag(source, has_math=False):
    # build the CSS based on cell contents
    css_parts = [CSS_BASE]
    
    if re.search(r'(?m)^\s*\|[^|]+\|.*$|<table\b', source):  # check for markdown/html tables
        css_parts.append(CSS_TABLE)
    
    if has_math:  # maths are detected earlier, only passed here
        css_parts.append(CSS_MATH)
        
    if '`' in source or '<pre>' in source or '<code>' in source:  # check for code blocks (```) or inline code (`) or HTML pre/code tags
        css_parts.append(CSS_CODE)

    combined_css = "\n\n".join(css_parts)
    return f"<style>\n{combined_css}\n</style>"

def process_notebook(input_path, output_path, skip_empty=False):
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            nb = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse {input_path} as JSON: {e}")
        sys.exit(1)

    if not isinstance(nb, dict) or 'cells' not in nb or 'nbformat' not in nb:
        print(f"Error: {input_path} does not appear to be a valid Jupyter notebook.")
        sys.exit(1)

    for cell in nb.get('cells', []):
        if cell.get('cell_type') == 'markdown':
            source = "".join(cell.get('source', [])) if isinstance(cell.get('source'), list) else cell.get('source', '')
            source = clean_legacy_wrappers(source)

            if skip_empty and not source.strip():
                continue

            source, math_blocks = protect_math(source)

            # convert HTML to markdown
            source = md(source, heading_style="ATX", escape_asterisks=False, escape_underscores=False)

            source = restore_math(source, math_blocks)
            has_math = len(math_blocks) > 0
            style_tag = build_smart_style_tag(source, has_math)

            # build the correct cell contents
            final_source = f'{style_tag}\n\n<div class="rtl-markdown-container">\n\n{source.strip()}\n</div>'

            # update cell source correctly formatted as list of lines
            cell['source'] = [line + '\n' for line in final_source.split('\n')]
            if cell['source']:
                cell['source'][-1] = cell['source'][-1].rstrip('\n')


    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(nb, f, ensure_ascii=False, indent=1)

    print(f"Notebook processed. Result saved to: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rule-based HTML to Markdown conversion and style fixes for Jupyter notebooks.")
    parser.add_argument("input_file", type=Path, help="The input .ipynb file")
    parser.add_argument("-o", "--output", type=Path, help="Path to the output file")
    parser.add_argument("-r", "--replace", action="store_true", help="Overwrite the input file in place")
    parser.add_argument("-s", "--skip-empty", action="store_true", help="Skip empty markdown cells (default: keep)")

    args = parser.parse_args()

    if not args.input_file.exists():
        print(f"Error: The file {args.input_file} does not exist.")
        sys.exit(1)

    # handle ambiguous arguments
    if args.output and args.replace:
        print("Error: --output and --replace are mutually exclusive. Specify one or the other.")
        sys.exit(1)

    # determine the correct output path based on user arguments
    if args.replace:
        out_path = args.input_file
    elif args.output:
        out_path = args.output
    else:
        out_path = args.input_file.with_name(f"{args.input_file.stem}-fixed{args.input_file.suffix}")

    process_notebook(args.input_file, out_path, skip_empty=args.skip_empty)